#!/usr/bin/env python3
"""Parse a Quartus post-fit Verilog netlist (.vo) into postfit_atoms/postfit_conns.

- Grammar seen from quartus_eda 25.1 (--simulation --tool=modelsim --format=verilog).
- Any line shape not listed in parse() is a hard error (db.die), never skipped.
- Nets: escapes removed (`\\q[0]~reg0_q ` -> `q[0]~reg0_q`); bus bits `name[i]`;
  `assign a = b;` aliases resolved to the driver side (b).
- Top-level ports become type "pin" atoms from the "Design Ports Information" table.

Usage: python3.15t scripts/cyclonev_vo_parse.py <postfit.vo>   # parse + print counts only
Called by scripts/cyclonev_corpus_build.py as load_vo(build_id, path).
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import db  # noqa: E402

# Output ports per atom type; every other port of a known type is an input.
OUT_PORTS = {
    "cyclonev_lcell_comb": {"combout", "sumout", "cout", "shareout"},
    "dffeas": {"q"},
    "cyclonev_io_ibuf": {"o"},
    "cyclonev_io_obuf": {"o", "obar"},
    "cyclonev_clkena": {"outclk", "enaout"},
    "cyclonev_mac": {"resulta", "resultb", "chainout", "scanout", "dftout"},
    "cyclonev_ram_block": {"portadataout", "portbdataout", "eccstatus", "dftout"},
    "cyclonev_mlab_cell": {"portbdataout"},
}
CONSTS = {"gnd": "0", "vcc": "1", "unknown": "x"}

_LOC_XYN = re.compile(r"^([A-Z0-9]+)_X(\d+)_Y(\d+)_N(\d+)$")
_LOC_OTHER = re.compile(r"^([A-Z0-9]+)_([A-Z0-9]+)$")
_PIN_LINE = re.compile(r"^// (\S+)\t=>  Location: (PIN_\w+),\t I/O Standard: ([^,]+),"
                       r"\t Current Strength: (.+)$")
_DECL = re.compile(r"^(input|output|inout|wire|tri1)\s+(?:\[(\d+):(\d+)\]\s+)?(.+);$")
_INST = re.compile(r"^([a-z_][a-z0-9_]*) (\\\S+ |[A-Za-z_][\w$]*) ?\($")
_PORT = re.compile(r"^\t\.(\w+)\((.*)\)(,|\);)$")
_DEFPARAM = re.compile(r"^defparam (\\\S+ |[A-Za-z_][\w$]*)\s?\.(\w+) = (.+);$")
_ASSIGN = re.compile(r"^assign (.+) = (.+);$")
_TOK = re.compile(r"\s*(\\\S+\s|\d+'[bhd][0-9a-fA-FxXzZ_]+|[A-Za-z_][\w$]*|\[\d+\]|[!{},])")


def ident(raw):
    """Strip Verilog escape: `\\foo ` -> `foo`."""
    return raw[1:].rstrip() if raw.startswith("\\") else raw


def parse_loc(loc):
    m = _LOC_XYN.match(loc)
    if m:
        return m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
    m = _LOC_OTHER.match(loc)
    if m:
        return m.group(1), None, None, None
    db.die(f"unrecognised location {loc!r}")


def literal_bits(tok):
    width, rest = tok.split("'", 1)
    base, digits = rest[0], rest[1:].replace("_", "")
    if base == "b":
        bits = digits
    elif base == "h":
        bits = "".join(format(int(c, 16), "04b") for c in digits)
    else:
        bits = format(int(digits), "b")
    bits = bits.rjust(int(width), "0")[-int(width):]
    return [(None, False, b) for b in reversed(bits)]  # LSB first


class Vo:
    def __init__(self):
        self.module = None
        self.widths = {}        # bus name -> (msb, lsb)
        self.port_dirs = {}     # top-level port bit -> "input" | "output" | "inout"
        self.pins = []          # (port, location, io_standard, current_strength)
        self.atoms = {}         # name -> {type, location, params, conns}
        self.alias = {}         # net -> driver-side net

    # ── expressions ─────────────────────────────────────────────────────
    def tokens(self, text):
        out, pos = [], 0
        text = text.rstrip() + " "   # an escaped identifier ends at whitespace
        while text[pos:].strip():
            m = _TOK.match(text, pos)
            if not m:
                db.die(f"unrecognised expression {text!r} at {pos}")
            out.append(m.group(1))
            pos = m.end()
        return out

    def expr_bits(self, text):
        """LSB-first [(net, inverted, const)] for one port expression."""
        toks = self.tokens(text)
        bits, i = self._expr(toks, 0)
        if i != len(toks):
            db.die(f"trailing tokens in expression {text!r}")
        return bits

    def _expr(self, toks, i):
        t = toks[i]
        if t == "{":
            parts, i = [], i + 1
            while True:
                b, i = self._expr(toks, i)
                parts.append(b)
                if toks[i] == "}":
                    i += 1
                    break
                if toks[i] != ",":
                    db.die(f"bad concatenation near {toks[i]!r}")
                i += 1
            return [bit for p in reversed(parts) for bit in p], i
        if t == "!":
            b, i = self._expr(toks, i + 1)
            if len(b) != 1 or b[0][0] is None:
                db.die(f"inversion of a non-net {toks}")
            return [(b[0][0], not b[0][1], None)], i
        if "'" in t:
            return literal_bits(t), i + 1
        name = ident(t)
        if name in CONSTS:
            return [(None, False, CONSTS[name])], i + 1
        if i + 1 < len(toks) and toks[i + 1].startswith("["):
            return [(f"{name}{toks[i + 1]}", False, None)], i + 2
        if name in self.widths:
            msb, lsb = self.widths[name]
            rng = range(lsb, msb + 1) if msb >= lsb else range(lsb, msb - 1, -1)
            return [(f"{name}[{k}]", False, None) for k in rng], i + 1
        return [(name, False, None)], i + 1

    def canon(self, net):
        seen = set()
        while net in self.alias:
            if net in seen:
                db.die(f"assign loop at {net!r}")
            seen.add(net)
            net = self.alias[net]
        return net

    # ── file ────────────────────────────────────────────────────────────
    def parse(self, path):
        lines = Path(path).read_text().split("\n")
        loc = None
        i = 0
        while i < len(lines):
            ln = lines[i]
            i += 1
            s = ln.strip()
            if not s or s.startswith("`timescale") or s == "endmodule":
                continue
            if s.startswith("// Location: "):
                loc = s[len("// Location: "):]
                continue
            if "=>  Location:" in ln:
                m = _PIN_LINE.match(ln)
                if not m:
                    db.die(f"{path}:{i}: unrecognised pin line {ln!r}")
                self.pins.append(m.groups())
                continue
            if s.startswith("//"):
                continue
            if s.startswith("module "):
                self.module = s.split()[1]
                while not lines[i].strip().endswith(");"):
                    i += 1
                i += 1
                continue
            m = _DECL.match(s)
            if m:
                kind, msb, lsb, names = m.groups()
                for raw in self._decl_names(names):
                    name = ident(raw)
                    if msb is not None:
                        self.widths[name] = (int(msb), int(lsb))
                    if kind in ("input", "output", "inout"):
                        if msb is None:
                            self.port_dirs[name] = kind
                        else:
                            a, b = sorted((int(msb), int(lsb)))
                            for k in range(a, b + 1):
                                self.port_dirs[f"{name}[{k}]"] = kind
                continue
            m = _ASSIGN.match(s)
            if m:
                lhs_t, rhs = m.group(1).strip(), self.expr_bits(m.group(2))
                if lhs_t in CONSTS:   # assign gnd = 1'b0; etc.
                    if rhs != [(None, False, CONSTS[lhs_t])]:
                        db.die(f"{path}:{i}: unexpected constant assign {s!r}")
                    continue
                lhs = self.expr_bits(lhs_t)
                if (len(lhs) != 1 or len(rhs) != 1 or lhs[0][0] is None
                        or rhs[0][0] is None or lhs[0][1] or rhs[0][1]):
                    db.die(f"{path}:{i}: unsupported assign {s!r}")
                self.alias[lhs[0][0]] = rhs[0][0]
                continue
            m = _INST.match(ln)
            if m:
                atype, name = m.group(1), ident(m.group(2))
                if atype not in OUT_PORTS:
                    db.die(f"{path}:{i}: unknown atom type {atype!r} ({name})")
                if loc is None:
                    db.die(f"{path}:{i}: atom {name!r} has no // Location")
                if name in self.atoms:
                    db.die(f"{path}:{i}: duplicate atom {name!r}")
                atom = {"type": atype, "location": loc, "params": {}, "conns": []}
                self.atoms[name] = atom
                loc = None
                while True:
                    ln = lines[i]
                    i += 1
                    if not ln.strip() or ln.lstrip().startswith("//"):
                        continue
                    pm = _PORT.match(ln)
                    while not pm and ln.startswith("\t.") and ln.rstrip().endswith(",") \
                            and i < len(lines) and not lines[i].startswith("\t."):
                        ln += lines[i]          # a long concatenation wraps lines
                        i += 1
                        pm = _PORT.match(ln)
                    if not pm:
                        db.die(f"{path}:{i}: unrecognised port line {ln!r}")
                    port, expr, close = pm.groups()
                    if expr.strip():
                        d = "out" if port in OUT_PORTS[atype] else "in"
                        for b, (net, inv, const) in enumerate(self.expr_bits(expr)):
                            atom["conns"].append((port, b, d, net, inv, const))
                    if close == ");":
                        break
                continue
            m = _DEFPARAM.match(s)
            if m:
                name, p, v = ident(m.group(1)), m.group(2), m.group(3).strip()
                if name not in self.atoms:
                    db.die(f"{path}:{i}: defparam for unknown atom {name!r}")
                self.atoms[name]["params"][p] = v[1:-1] if v.startswith('"') else v
                continue
            db.die(f"{path}:{i}: unrecognised line {ln!r}")
        if self.module is None:
            db.die(f"{path}: no module")
        for port, _loc, _std, _cur in self.pins:
            if port not in self.port_dirs:
                db.die(f"{path}: pin table names unknown port {port!r}")
        return self

    @staticmethod
    def _decl_names(text):
        out = []
        for part in re.findall(r"\\\S+\s|[^,\s]+", text):
            if part.strip() != ",":
                out.append(part)
        return out


def load_vo(build_id, path):
    """Replace postfit_atoms/postfit_conns rows for build_id from a .vo file."""
    import schema
    from sqlalchemy import delete, insert, select
    vo = Vo().parse(path)
    ta, tc = schema.postfit_atoms, schema.postfit_conns
    rows = []
    for name, a in vo.atoms.items():
        kind, x, y, n = parse_loc(a["location"])
        rows.append(dict(build=build_id, name=name, type=a["type"], location=a["location"],
                         loc_kind=kind, x=x, y=y, n=n, params=a["params"]))
    for port, loc, std, cur in vo.pins:
        rows.append(dict(build=build_id, name=port, type="pin", location=loc, loc_kind="PIN",
                         x=None, y=None, n=None,
                         params={"direction": vo.port_dirs[port], "io_standard": std,
                                 "current_strength": cur}))
    with db.engine().begin() as conn:
        conn.execute(delete(tc).where(tc.c.build == build_id))
        conn.execute(delete(ta).where(ta.c.build == build_id))
        conn.execute(insert(ta), rows)
        ids = dict(conn.execute(select(ta.c.name, ta.c.id).where(ta.c.build == build_id)).all())
        crow = []
        for name, a in vo.atoms.items():
            for port, b, d, net, inv, const in a["conns"]:
                crow.append(dict(build=build_id, atom=ids[name], port=port, bit=b, direction=d,
                                 net=vo.canon(net) if net else None, inverted=inv, const=const))
        for port, _l, _s, _c in vo.pins:
            d = "out" if vo.port_dirs[port] == "input" else "in"
            crow.append(dict(build=build_id, atom=ids[port], port="pad", bit=0, direction=d,
                             net=vo.canon(port), inverted=False, const=None))
        conn.execute(insert(tc), crow)
    return vo


if __name__ == "__main__":
    for p in sys.argv[1:]:
        v = Vo().parse(p)
        print(f"module {v.module}: {len(v.atoms)} atoms, {len(v.pins)} pins, "
              f"{sum(len(a['conns']) for a in v.atoms.values())} conn bits, "
              f"{len(v.alias)} aliases")
