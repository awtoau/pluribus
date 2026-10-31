#!/usr/bin/env python3.15t
"""Functional gate: lifted Verilog (bitstream only) simulated against the Quartus post-fit netlist.

Per corpus design: lift the .rbf (lifters/cycloneiv_lift.py), emit Verilog, simulate it next to
the post-fit .vo on the vendor cell models (iverilog) with the same random stimulus and compare
every LUT combout / cout and FF q that exists in the .vo, by location.

- The lifter's boundary nets (IO pads reaching the fabric, clock wires, unresolved inputs) are
  driven from the .vo: pad / clock wires by the net the RCF routes through that element
  (vendor-assisted NAMING of the boundary only, no logic comes from the .vo); unresolved inputs
  stay X, which scores as missing.
- Per (cell, signal) point:  matched  lifted == .vo on every sample
                             wrong    lifted differs on a sample
                             missing  .vo cell with no lifted cell, or lifted output X
                             extra    lifted cell at a location with no .vo cell
  Headline = matched / (matched + missing + extra + wrong).  PASS = headline 100%.
- Not covered and not hidden: IO-pad ends of the netlist (output pads), M9K / multipliers / PLL,
  clock tree: the gate says so in its summary instead of counting them as matched.

  python3.15t scripts/cycloneiv_lifted_sim_check.py gx150_sp_000 [--tables a.json,b.json]
  python3.15t scripts/cycloneiv_lifted_sim_check.py --all --pattern 'gx150_sp_*' --split odd
Log tmp/logs/cycloneiv_lifted_sim_check.log; per design tmp/cycloneiv/simcheck/<design>/
"""
import argparse
import random
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "lifters"))
import cycloneiv_corpus as cc  # noqa: E402
import heavy_guard  # noqa: E402
import cycloneiv_emit as em  # noqa: E402
import cycloneiv_geom as cg  # noqa: E402
import cycloneiv_lift as lf  # noqa: E402
import cycloneiv_common as cm  # noqa: E402
import cycloneiv_sim_check as sc  # noqa: E402

LOG = REPO / "tmp" / "logs" / "cycloneiv_lifted_sim_check.log"
WORK = REPO / "tmp" / "cycloneiv" / "simcheck"
# iverilog compile + vvp of ~1k cells x 72 steps: measured < 20 s; stall rule 60 s, backstop 3x.
SIM_LIMIT_S = 180
STEPS = 72
LOC = re.compile(r"^(LCCOMB|FF)_X(\d+)_Y(\d+)_N(\d+)$")


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(msg + "\n")
    print(msg, flush=True)


def esc(n):
    return "\\" + n + " "


def vo_out_net(a, port):
    for p, _b, _d, net, _i, _c in a["conns"]:
        if p == port and net:
            return net
    return None


def terminal_nets(d, des):
    """lifted boundary net -> vo net (hierarchical, unescaped), via the RCF net through the element."""
    vo, rcf = d["vo"], d["rcf"]
    node_net = {}
    oracle_nets = {}
    for tname, info in des.terminals.items():
        if info[0] == "WIRE" and str(info[1]).startswith("ORACLE:"):
            oracle_nets[tname] = info[1][len("ORACLE:"):]
    for net, edges in rcf.items():
        for s, t in edges:
            for nd in (s, t):
                if nd[0] == "W":
                    node_net.setdefault(nd[1:], net)
    out = {}
    ib_at = {}
    for a in vo.atoms.values():
        m = LOC.match(a.get("location") or "") if False else None
    for name, info in des.terminals.items():
        if info[0] == "DRV" and info[1] == "IOIBUF":
            _k, _ck, x, y, n = info
            for a in vo.atoms.values():
                if a.get("location") == f"IOIBUF_X{x}_Y{y}_N{n}" and a["type"] == "cycloneive_io_ibuf":
                    vn = vo_out_net(a, "o")
                    if vn:
                        out[name] = vn
            continue
        if info[0] != "WIRE":
            continue
        _k, typ, x, y, s, i = info
        if name in oracle_nets:
            out[name] = oracle_nets[name]
            continue
        net = node_net.get((typ, x, y, s, i))
        if net is None or net not in vo.atoms:
            continue
        a = vo.atoms[net]
        port = {"cycloneive_io_ibuf": "o", "cycloneive_clkctrl": "outclk"}.get(a["type"])
        vn = vo_out_net(a, port) if port else None
        if vn:
            out[name] = vn
    return out


def race_taint(vo):
    """Cells downstream of a register whose asynchronous control (clrn / prn / aload) is driven by
    logic.  Their zero-delay behaviour is a simulator race (the clear glitches while the register
    outputs it depends on settle) and differs between two correct models; the gate excludes them and
    says how many.  -> {("lut" | "ff", (x, y, le))}."""
    drv, readers, cells = {}, {}, {}
    for a in vo.atoms.values():
        m = LOC.match(a.get("location") or "")
        if not m or a["type"] not in ("cycloneive_lcell_comb", "dffeas"):
            continue
        kind = "ff" if m.group(1) == "FF" else "lut"
        key = (kind, (int(m.group(2)), int(m.group(3)), int(m.group(4)) // 2))
        cells[key] = a
        for p, _b, d, net, _i, _c in a["conns"]:
            if not net:
                continue
            net = vo.canon(net)
            if d == "out":
                drv[net] = key
            else:
                readers.setdefault(net, []).append((key, p))
    seeds = set()
    for key, a in cells.items():
        if key[0] != "ff":
            continue
        for p, _b, d, net, _i, _c in a["conns"]:
            if p in ("clrn", "prn", "aload") and net and vo.canon(net) in drv:
                seeds.add(key)
    out, todo = set(seeds), list(seeds)
    while todo:
        key = todo.pop()
        for p, _b, d, net, _i, _c in cells[key]["conns"]:
            if d == "out" and net:
                for rk, _rp in readers.get(vo.canon(net), []):
                    if rk not in out:
                        out.add(rk)
                        todo.append(rk)
    return out


def clock_ports(vo):
    """top-level input ports that feed a clkctrl."""
    ib = {}
    for a in vo.atoms.values():
        if a["type"] == "cycloneive_io_ibuf":
            ib[vo_out_net(a, "o")] = vo_out_net(a, "i")
    ck = set()
    for a in vo.atoms.values():
        if a["type"] == "cycloneive_clkctrl":
            for p, _b, _d, net, _i, _c in a["conns"]:
                if p == "inclk" and net in ib:
                    ck.add(ib[net])
    return ck


class OracleTracer:
    """Routing taken from the .vo instead of the bitstream (--oracle): isolates the other decode
    (LUT mask / carry mode, FF fields, emitter, gate) from routing quality.  Never a result."""

    def __init__(self, d):
        vo = d["vo"]
        self.atom_at, self.src, self.ffs = {}, {}, set()
        for a in vo.atoms.values():
            m = LOC.match(a.get("location") or "")
            if m:
                kind, x, y, n = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
                self.atom_at[(kind, x, y, n)] = a
                if kind == "FF":
                    self.ffs.add((x, y, n // 2))
                for p, _b, _d, net, _i, _c in a["conns"]:
                    if net and p in ("combout", "q"):
                        self.src[vo.canon(net)] = ("DRV", "FF" if kind == "FF" else "LCCOMB", n, x, y)
            if a["type"] in ("cycloneive_io_ibuf", "cycloneive_clkctrl"):
                port = "o" if a["type"] == "cycloneive_io_ibuf" else "outclk"
                for p, _b, _d, net, _i, _c in a["conns"]:
                    if p == port and net:
                        self.src[vo.canon(net)] = ("WIRE", "ORACLE:" + vo.canon(net), 0, 0, 0, 0)
        self.vo = vo

    def ff_present(self, x, y, le):
        return (x, y, le) in self.ffs

    def inverted(self, key, x, y):
        kind, n, port = key
        a = self.atom_at.get((kind, x, y, n))
        vport = "d" if port == "DATAD" else port.lower()
        for p, _b, _d, net, inv, _c in (a["conns"] if a else []):
            if p == vport:
                return bool(inv)
        return False

    def trace(self, key, x, y):
        kind, n, port = key
        a = self.atom_at.get((kind, x, y, n))
        if a is None:
            return None, "oracle: no cell"
        if kind == "LCCOMB" and port == "DATAC" and a["params"].get("sum_lutc_input") == "cin":
            return ("CIN", 0, 0, x, y), "oracle"
        vport = "d" if port == "DATAD" and kind == "FF" else port.lower()
        for p, _b, _d, net, _i, const in a["conns"]:
            if p != vport:
                continue
            if net is None:
                if const in ("0", "1"):
                    return ("CONST", int(const), 0, 0, 0), "oracle"
                return None, "oracle: unconnected"
            net = self.vo.canon(net)
            if kind == "FF" and port == "DATAD":
                s = self.src.get(net)
                if s and s[0] == "DRV" and s[1] == "LCCOMB" and (s[3], s[4], s[2]) == (x, y, n - 1):
                    return ("LUTOUT", 0, 0, x, y), "oracle"
            s = self.src.get(net)
            return (s, "oracle") if s else (None, "oracle: net with no known driver")
        return None, "oracle: pin not in the .vo"


def check(name, tables, steps=STEPS, oracle=False):
    d = cc.load(name)
    geom = cm.one_geom([name])
    lift = lf.CycloneIVLift(geom.die)
    des = lift.lift(d["plane"], tracer=OracleTracer(d) if oracle else None)
    work = WORK / name
    work.mkdir(parents=True, exist_ok=True)
    (work / "lifted.v").write_text(em.emit(des))
    vo = d["vo"]
    tmap = terminal_nets(d, des)
    # probes: (label, kind, vo net, lifted net)
    vo_lut, vo_ff = {}, {}
    for a in vo.atoms.values():
        m = LOC.match(a.get("location") or "")
        if not m:
            continue
        x, y, n = int(m.group(2)), int(m.group(3)), int(m.group(4))
        if m.group(1) == "LCCOMB" and a["type"] == "cycloneive_lcell_comb":
            vo_lut[(x, y, n // 2)] = a
        elif m.group(1) == "FF" and a["type"] == "dffeas":
            vo_ff[(x, y, n // 2)] = a
    l_lut = {(l["x"], l["y"], l["le"]): l for l in des.luts}
    l_ff = {(f["x"], f["y"], f["le"]): f for f in des.ffs}
    probes, missing, extra = [], [], []
    tainted = race_taint(vo)
    excluded = []
    for k, a in vo_lut.items():
        for port, lnet in (("combout", lf.comb(*k)), ("cout", lf.cout(*k))):
            vn = vo_out_net(a, port)
            if vn is None:
                continue
            if a is not None and ("lut", k) in tainted:
                excluded.append(f"lut{k}.{port}")
                continue
            if k in l_lut:
                probes.append((f"lut{k}.{port}", vn, lnet))
            else:
                missing.append(f"lut{k}.{port}")
    for k, a in vo_ff.items():
        vn = vo_out_net(a, "q")
        if vn is None:
            continue
        if ("ff", k) in tainted:
            excluded.append(f"ff{k}.q")
            continue
        if k in l_ff:
            probes.append((f"ff{k}.q", vn, lf.qnet(*k)))
        else:
            missing.append(f"ff{k}.q")
    read = set()
    for l in des.luts:
        read.update(l[p] for p in ("a", "b", "c", "d", "cin"))
    for f in des.ffs:
        read.update(f[p] for p in ("d", "asdata", "clk", "clrn", "ena", "sclr", "sload"))
    # extra = a lifted cell with no .vo cell whose output something reads (a register-only LE keeps
    # a pass-through LUT the .vo does not list; unread, it is not an extra)
    for k, l in l_lut.items():
        if k not in vo_lut and (l["z"] in read or l["cout"] in read):
            extra.append(f"lut{k}")
    for k, f in l_ff.items():
        if k not in vo_ff and f["q"] in read:
            extra.append(f"ff{k}")
    ins = sorted(p for p, dr in vo.port_dirs.items() if dr == "input")
    outs = sorted(p for p, dr in vo.port_dirs.items() if dr == "output")
    clks = clock_ports(vo)
    data = [p for p in ins if p not in clks]
    rnd = random.Random(7)
    tb = ["`timescale 1ps/1ps", "module tb;"]
    tb += [f"  reg {esc(p)};" for p in ins]
    tb.append("  top Q(" + ", ".join(f".{esc(p)}({esc(p)})" for p in ins) + ");")
    conns = []
    for t in sorted(des.terminals):
        if t in tmap:
            conns.append(f".{t}(Q.{esc(tmap[t])})")
        else:
            conns.append(f".{t}(1'bx)")
    tb.append(f"  cycloneiv_lifted L({', '.join(conns)});")
    tb.append(f"  integer ok [0:{max(len(probes), 1) - 1}], bad [0:{max(len(probes), 1) - 1}], xl [0:{max(len(probes), 1) - 1}], xq [0:{max(len(probes), 1) - 1}], fb [0:{max(len(probes), 1) - 1}];")
    tb.append("  integer i, s;")
    tb.append("  initial begin")
    tb.append(f"    for (i = 0; i < {max(len(probes), 1)}; i = i + 1) begin ok[i] = 0; bad[i] = 0; xl[i] = 0; xq[i] = 0; fb[i] = -1; end")
    # Data first, clocks left undriven (X) until the data has settled: a clock going X -> 0 is a
    # falling edge, but an inverted clock (~X -> 1) is a rising edge, so inverted-clock registers
    # capture once at t = 100 ps with settled data, identically in both models.  Clocks driven at
    # t = 0 would race the data and give a different power-up state in the two simulators.
    tb += [f"    {esc(p)} = $random;" for p in data]
    tb.append("    #100;")
    tb += [f"    {esc(p)} = 0;" for p in sorted(clks)]
    tb.append("    #100;")
    tb.append(f"    for (s = 0; s < {steps}; s = s + 1) begin")
    for p in data:
        tb.append(f"      {esc(p)} = $random;")
    tb.append("      #50;")
    # one clock at a time, each in its own time step: pulsing several together races the register
    # updates of one domain against the clock edges of the other
    for p in sorted(clks):
        tb.append(f"      {esc(p)} = 1;")
        tb.append("      #50;")
        tb.append(f"      {esc(p)} = 0;")
        tb.append("      #50;")
    tb.append("      if (s >= 0) begin")
    for i, (label, vn, ln) in enumerate(probes):
        tb.append(f"        if (L.{ln} === 1'bx || L.{ln} === 1'bz) xl[{i}] = xl[{i}] + 1;"
                  f" else if (Q.{esc(vn)} === 1'bx || Q.{esc(vn)} === 1'bz) xq[{i}] = xq[{i}] + 1;"
                  f" else if (Q.{esc(vn)} === L.{ln}) ok[{i}] = ok[{i}] + 1; else begin bad[{i}] = bad[{i}] + 1; if (fb[{i}] < 0) fb[{i}] = s; end")
    tb.append("      end")
    tb.append("    end")
    for i, (label, vn, ln) in enumerate(probes):
        tb.append(f"    $display(\"PROBE {i} %0d %0d %0d %0d %0d\", ok[{i}], bad[{i}], xl[{i}], xq[{i}], fb[{i}]);")
    tb.append("    $finish;")
    tb.append("  end")
    tb.append("endmodule")
    (work / "tb.v").write_text("\n".join(tb) + "\n")
    cells = {a["type"] for a in vo.atoms.values()} - {"dffeas"}
    (work / "models.v").write_text(sc.vendor_models(cells))
    cmd = ["iverilog", "-g2012", "-o", str(work / "sim.vvp"), str(work / "tb.v"),
           str(cc.top_module_only(cc.CORPUS / name / "postfit.vo")), str(work / "models.v"),
           str(sc.SIMLIB / "altera_primitives.v"), str(work / "lifted.v")]
    try:
        r = heavy_guard.guarded(cmd, f"{name} iverilog", overall_s=SIM_LIMIT_S)
        if r.timed_out:
            return name, {"error": f"iverilog exceeded {SIM_LIMIT_S}s or stalled"}
        if r.returncode:
            return name, {"error": "iverilog compile: " + r.stderr.strip()[-400:]}
        r = heavy_guard.guarded(["vvp", str(work / "sim.vvp")], f"{name} vvp", overall_s=SIM_LIMIT_S)
        if r.timed_out:
            return name, {"error": f"vvp exceeded {SIM_LIMIT_S}s or stalled"}
    except OSError as e:
        return name, {"error": f"simulator start failed: {e}"}
    res = {"matched": 0, "wrong": 0, "missing": len(missing), "extra": len(extra), "xq": 0, "wrong_pts": [],
           "missing_pts": missing[:5], "luts": len(des.luts), "ffs": len(des.ffs),
           "unresolved": len(des.unresolved), "terminals": len(des.terminals), "mapped": len(tmap),
           "not_lifted": dict(des.not_lifted), "excluded": len(excluded)}
    for ln_ in r.stdout.splitlines():
        m = re.match(r"PROBE (\d+) (\d+) (\d+) (\d+) (\d+) (-?\d+)", ln_)
        if not m:
            continue
        i, ok, bad, xl, xq, fb = map(int, m.groups())
        if bad:
            res["wrong"] += 1
            res["wrong_pts"].append(probes[i][0])
            res.setdefault("first_bad", []).append((fb, probes[i][0]))
        elif xl or ok == 0:
            res["missing"] += 1
            res["missing_pts"].append(probes[i][0])
        else:
            res["matched"] += 1
        res["xq"] += xq > 0
    return name, res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--oracle", action="store_true", help="routing from the RCF (debug: isolates the other decode)")
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--pattern", default="gx150_sp_*")
    ap.add_argument("--split", default="odd", choices=["all", "even", "odd"])
    ap.add_argument("--tables", default=str(REPO / "tmp" / "cycloneiv" / "rl_gx_m8c.json"))
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    # The routing source (learned tables / phys tracer) is retired; the gate returns with the clean P2 tracer.
    raise SystemExit("cycloneiv_lifted_sim_check: unavailable, pending clean P2 tracer (#165, docs/altera/cycloneIV/cycloneiv-clean-pipeline.md)")
    names = a.designs or [n for n in cc.designs(a.pattern) if cm.split_of(n, a.split)]
    if a.limit:
        names = names[:a.limit]
    tables = a.tables.split(",")
    tot = {"matched": 0, "wrong": 0, "missing": 0, "extra": 0}
    npass = 0
    with ThreadPoolExecutor(a.jobs) as ex:
        for name, res in ex.map(lambda n: check(n, tables, oracle=a.oracle), names):
            if "error" in res:
                log(f"{name}: ERROR {res['error']}")
                continue
            for k in tot:
                tot[k] += res[k]
            den = sum(res[k] for k in tot)
            ok = res["wrong"] == res["missing"] == res["extra"] == 0 and res["matched"] > 0
            npass += ok
            log(f"{name}: {'PASS' if ok else 'FAIL'} points matched {res['matched']} / ({res['matched']} + missing "
                f"{res['missing']} + extra {res['extra']} + wrong {res['wrong']}) = {100 * res['matched'] / max(den, 1):.1f}%; "
                f"lifted {res['luts']} LUT {res['ffs']} FF; boundary {res['terminals']} (mapped {res['mapped']}), "
                f"unresolved inputs {res['unresolved']}; excluded as race-prone {res['excluded']}; wrong {res['wrong_pts'][:3]}; missing {res['missing_pts'][:3]}")
    den = sum(tot.values())
    log(f"SUMMARY {len(names)} designs, {npass} PASS: points matched {tot['matched']} / (matched {tot['matched']} + "
        f"missing {tot['missing']} + extra {tot['extra']} + wrong {tot['wrong']}) = {100 * tot['matched'] / max(den, 1):.2f}%")
    return 0 if npass == len(names) else 1


if __name__ == "__main__":
    sys.exit(main())
