#!/usr/bin/env python3.15t
"""Cyclone V round-trip re-encode check (#112): lifted data -> Quartus primitives -> fit + asm -> diff the .rbf.

Per design (corpus/cyclonev/<d>/bitstream.rbf, an original Quartus build):
  1. native-decode the original .rbf -> .bt, lift it (CycloneVLift): LUTs (mask, nets, ALM place), flip-flops, pads.
  2. emit a Verilog netlist of cyclonev_lcell_comb / dffeas atoms from the lifted rows only
     (mask rebuilt from the lifted init through the proven LAB-pin <-> lcell-port map).
  3. QSF: PIN_<pad> per port, LABCELL_X<x>_Y<y>_N<n> / FF_... per atom from the lifted ALM place.
  4. stage A: Quartus routes freely.  stage B (--rcf): the ORIGINAL build's RCF is imported (oracle routing,
     isolates the non-routing faults; instance/port names follow the original post-fit atoms).
  5. quartus_map/fit/asm/cpf, native-decode the regenerated .rbf, diff `.bt` against the original.
Scoring (per region): matched / (matched + missing + extra + wrong).  missing = original line absent, extra =
regenerated line with no original, wrong = same key (node / mux) with a different value.  Raw .rbf bit XOR
is reported beside it.  A pass is not expected; the output is the fault list.

  python3.15t scripts/cyclonev_reencode.py c_cmp_eq_v95_4 c_shiftreg_v95_4 c_adder_v95_4 [--rcf] [--skip-quartus]
Work dir: tmp/reencode/<design>[_rcf]/.  Log: tmp/logs/cyclonev_reencode.log.  Results: tmp/reencode/results.json.
"""
import argparse
import collections
import json
import logging
import os
import re
import shutil
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402

DEVICE = "5CEBA4U19C8"
CORPUS = os.path.join(REPO, "corpus", "cyclonev")
WORK = os.path.join(REPO, "tmp", "reencode")
LOG_PATH = os.path.join(REPO, "tmp", "logs", "cyclonev_reencode.log")
log = logging.getLogger("cyclonev_reencode")
HALF = ("T", "B")
PORTS = "abcdef"
# Backstops: heavy_guard.OVERALL_S (3x measured cold worst); stall limit 60 s of no CPU progress.
STEPS = (("quartus_map", "quartus"), ("quartus_fit", "quartus_fit"), ("quartus_asm", "quartus_asm"),
         ("quartus_cpf", "quartus_cpf"))


def setup_logging():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(LOG_PATH), logging.StreamHandler(sys.stdout)):
        h.setFormatter(fmt)
        log.addHandler(h)


# ---- lifted data -> Verilog ----------------------------------------------------------------------

def lab_pin(half, mode, port):
    """LAB pin feeding lcell port data<port> (same rule as cyclonev_postfit_compare.lab_pin)."""
    h = "0" if half == "T" else "1"
    if port in "ab":
        return port.upper()
    if port == "c":
        return "C" if half == "T" else "D"
    if port == "d":
        return {"D": "D", "C": "C", "E": "E" + h, "F": "FB"}[mode[0]]
    if port == "e":
        return {"E": "E" + h, "F": "FB"}.get(mode[2])
    return "F" + h


def is_const(net):
    return net is None or net.startswith("1'b")


def port_nets(lt, init_key, pins_key):
    """{lcell port: net or literal} and the 64-bit Quartus mask for one lifted LUT row.

    Quartus mask bit v = lifted init at the index built from the LAB-pin values; constant / unconnected
    ports are tied to their literal and replicated (the don't-care bits Quartus also replicates)."""
    half, mode = lt["half"], lt["mode"]
    pins, init = lt[pins_key], lt[init_key]
    letter_of = {p: l for l, p in pins.items()}
    nets, constv = {}, {}
    for port in PORTS:
        lp = lab_pin(half, mode, port)
        if lp is None:
            nets[port], constv[port] = f"1'b{mode[2]}", int(mode[2])
            continue
        letter = letter_of.get(lp)
        net = lt[letter] if letter else None
        if is_const(net):
            val = 1 if (net or "").endswith("1") else 0
            nets[port], constv[port] = f"1'b{val}", val
        else:
            nets[port] = net
    mask = 0
    for v in range(64):
        idx = 0
        for k, port in enumerate(PORTS):
            lp = lab_pin(half, mode, port)
            bit = constv[port] if port in constv else (v >> k) & 1
            if lp is None or not bit:
                continue
            letter = letter_of.get(lp)
            if letter:
                idx |= 1 << "abcdef".index(letter)
        mask |= int(init[63 - idx]) << v
    return nets, mask



def arith_mask(g):
    """Quartus lut_mask of an adder half from the lifted sum / cout rows.

    cyclonev_lcell_comb (shared_arith off): f0 = mask[15:0](a,b,c,d), in2 = ~mask[47:32](a,b,c,f),
    sum = cin ^ f0 ^ in2, cout = maj(cin, f0, in2).  Per (a,b,c): the f0[d] / in2[f] bits are solved by
    brute force against the lifted sum(cin=0), cout(cin=0), cout(cin=1) tables.  With no cout row only
    f0 ^ in2 is known: in2 = 0 (as Quartus does for the last bit).  Returns (mask, nets, notes)."""
    sm = g.get("sum") or next(iter(g.values()))
    co = g.get("cout")
    half, mode = sm["half"], sm["mode"]
    nets, constv = {}, {}
    for port in "abcdf":
        lp = lab_pin(half, mode, port)
        net = sm[next((l for l, q in sm["pins"].items() if q == lp), "")] if lp else None
        if lp is None or is_const(net):
            nets[port], constv[port] = "1'b0", (1 if (net or "").endswith("1") else 0)
            nets[port] = f"1'b{constv[port]}"
        else:
            nets[port] = net

    def row_val(row, vals, cin):
        idx = 0
        for l, q in row["pins"].items():
            bit = cin if q == "CIN" else next((vals[p] for p in "abcdf" if lab_pin(half, mode, p) == q), 0)
            if bit:
                idx |= 1 << "abcdef".index(l)
        return int(row["init"][63 - idx])

    def point(a, b, c, d, f):
        v = {"a": a, "b": b, "c": c, "d": d, "f": f}
        for p, cv in constv.items():
            v[p] = cv
        return v
    f0 = [0] * 16
    f2 = [0] * 16
    amb = 0
    for abc in range(8):
        a, b, c = abc & 1, abc >> 1 & 1, abc >> 2 & 1
        if any(p in constv and constv[p] != x for p, x in (("a", a), ("b", b), ("c", c))):
            continue
        pts = {}
        for d in (0, 1):
            for f in (0, 1):
                v = point(a, b, c, d, f)
                s0 = row_val(sm, v, 0)
                c0, c1 = (row_val(co, v, 0), row_val(co, v, 1)) if co else (None, None)
                pts[(d, f)] = (s0, c0, c1)
        sols = []
        for f0d in range(4):
            for i2 in range(4):
                ok = True
                for (d, f), (s0, c0, c1) in pts.items():
                    if ("d" in constv and d != constv["d"]) or ("f" in constv and f != constv["f"]):
                        continue
                    x, y = f0d >> d & 1, i2 >> f & 1
                    ok &= (x ^ y) == s0
                    if co:
                        ok &= (x & y) == c0 and (x | y) == c1
                if ok:
                    sols.append((f0d, i2))
        if not sols:
            amb += 1
            continue
        if len(sols) > 1:
            amb += 1
            if not co:
                sols = [s for s in sols if s[1] == 0] or sols
        f0d, i2 = sols[0]
        for d in (0, 1):
            f0[a | b << 1 | c << 2 | d << 3] = f0d >> (constv.get("d", d)) & 1
            f2[a | b << 1 | c << 2 | d << 3] = 1 - (i2 >> (constv.get("f", d)) & 1)   # slot 3 of the index = f
    mask = sum(b << i for i, b in enumerate(f0)) | sum(b << (32 + i) for i, b in enumerate(f2))
    return mask, nets, amb


def lcell_n(alm, half):
    return alm * 6 + 3 * HALF.index(half)


def ff_n(alm, half, slot):
    return alm * 6 + 3 * HALF.index(half) + (1 if slot == "0" else 2)


def emit(d, names=None):
    """Design -> (verilog text, qsf lines, notes).  names: {pad label: port name}, {lifted ff/lut name: atom name}."""
    notes = collections.Counter()
    ports, body, qsf = [], [], []
    pname = {}
    for p in sorted(d.pads, key=lambda p: p["label"]):
        nm = (names or {}).get(("pad", p["label"])) or f"p_{p['label']}"
        pname[p["label"]] = nm
        ports.append(f"{'input' if p['direction'] == 'in' else 'output'} wire {esc(nm)}")
        qsf.append(f"set_location_assignment PIN_{p['label']} -to {tcl(nm)}")
        if p["direction"] == "in" and p["net_in"]:
            body.append(f"assign {p['net_in']} = {esc(nm)};")
        elif p["direction"] == "out" and p["net_out"]:
            body.append(f"assign {esc(nm)} = {p['net_out']};")
            if p.get("out_inverted"):
                notes["out_inverted pad (not emitted)"] += 1
        else:
            notes["pad without net"] += 1
    nets = set()
    groups = collections.defaultdict(dict)
    for lt in d.luts:
        if lt.get("io_inverter"):
            notes["io_inverter row (skipped)"] += 1
            continue
        if lt.get("block") != "LAB":
            notes[f"unsupported block {lt.get('block')}"] += 1
            continue
        groups[(lt["x"], lt["y"], lt["alm"], lt["half"])][lt.get("role", "sum")] = lt
    cout_net = {k: g["cout"]["z"] for k, g in groups.items() if "cout" in g}
    for key, g in sorted(groups.items()):
        x, y, alm, half = key
        base = g.get("sum") or next(iter(g.values()))
        arith = bool(base.get("arith"))
        if arith:
            mask, pn, amb = arith_mask(g)
            pn["e"] = "1'b0"
            if amb:
                notes["adder bits with ambiguous / unsolved f0,f2"] += amb
        else:
            pn, mask = port_nets(base, "init", "pins")
        inst = (names or {}).get(("lut", base["name"])) or f"lc_{x}_{y}_{alm}{half}"
        conn = {f"data{p}": v for p, v in pn.items()}
        outs = {}
        if arith:
            src = base.get("cin_src")
            conn["cin"] = cout_net.get(tuple(src)) if src else "1'b0"
            if conn["cin"] is None:
                notes["cin_src without cout row"] += 1
                conn["cin"] = "1'b0"
            if "sum" in g and g["sum"]["z_used"]:
                outs["sumout"] = g["sum"]["z"]
            if "cout" in g and g["cout"]["z_used"]:
                outs["cout"] = g["cout"]["z"]
            if "shareout" in g:
                notes["shareout row (not emitted)"] += 1
            params = f'.lut_mask(64\'h{mask:016x}), .shared_arith("off"), .extended_lut("off")'
        else:
            outs["combout"] = base["z"]
            params = f'.lut_mask(64\'h{mask:016x}), .shared_arith("off"), .extended_lut("off")'
        for o in outs.values():
            nets.add(o)
        for v in conn.values():
            if not v.startswith("1'b"):
                nets.add(v)
        pl = ", ".join(f".{k}({v})" for k, v in sorted(conn.items()))
        po = ", ".join(f".{k}({v})" for k, v in outs.items())
        body.append(f"cyclonev_lcell_comb #({params}) {esc(inst)} ({pl}{', ' if po else ''}{po});")
        qsf.append(f"set_location_assignment LABCELL_X{x}_Y{y}_N{lcell_n(alm, half)} -to {tcl(inst)}")
    for ff in d.ffs:
        if ff.get("block") != "LAB":
            notes["unsupported ff block"] += 1
            continue
        ctl = ff["ctl"]
        extra = [k for k in ("clrn", "sclr", "sload") if ctl.get(k) not in (("const", 1), ("const", 0))]
        if extra or "clr=" in (ff.get("dtype") or "") or ff.get("lsr"):
            notes["ff control not emitted (clr/sclr/sload)"] += 1
        inst = (names or {}).get(("ff", ff["name"])) or f"ff_{ff['x']}_{ff['y']}_{ff['alm']}{ff['half']}{ff['slot']}"
        nets.update(n for n in (ff["q"], ff["d"], ff["clk"]) if n and not n.startswith("1'b"))
        ena = ff["ce"] or "1'b1"
        body.append(f"dffeas #(.power_up(\"low\"), .is_wysiwyg(\"true\")) {esc(inst)} (.clk({ff['clk']}), .d({ff['d']}), .ena({ena}), "
                    f".clrn(1'b1), .sclr(1'b0), .sload(1'b0), .asdata(1'b0), .aload(1'b0), .q({ff['q']}));")
        qsf.append(f"set_location_assignment FF_X{ff['x']}_Y{ff['y']}_N{ff_n(ff['alm'], ff['half'], ff['slot'])} "
                   f"-to {tcl(inst)}")
    for p in d.pads:
        nets.update(n for n in (p["net_in"], p["net_out"]) if n)
    wires = "\n".join(f"wire {n};" for n in sorted(nets, key=lambda s: int(s[1:])))
    top = "reenc_top"
    text = (f"// generated by scripts/cyclonev_reencode.py from lifted data only\n"
            f"module {top} (\n  " + ",\n  ".join(ports) + "\n);\n" + wires + "\n" + "\n".join(body) + "\nendmodule\n")
    return top, text, qsf, notes


def esc(name):
    return name if re.fullmatch(r"[A-Za-z_]\w*", name) else "\\" + name + " "


def tcl(name):
    return "\"" + name + "\""


# ---- quartus -------------------------------------------------------------------------------------

def quartus(work, rcf_file, top):
    qb = toolchain.quartus_bin()
    qsf = ['set_global_assignment -name FAMILY "Cyclone V"', f"set_global_assignment -name DEVICE {DEVICE}",
           f"set_global_assignment -name TOP_LEVEL_ENTITY {top}",
           "set_global_assignment -name VERILOG_FILE reenc.v"]
    qsf += open(os.path.join(work, "assign.qsf")).read().splitlines()
    if rcf_file:
        qsf.append(f"set_global_assignment -name ROUTING_BACK_ANNOTATION_FILE {rcf_file}")
    open(os.path.join(work, "build.qsf"), "w").write("\n".join(qsf) + "\n")
    open(os.path.join(work, "build.qpf"), "w").write('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    for step, key in STEPS:
        if step == "quartus_cpf":
            cmd = [os.path.join(qb, step), "-c", "build.sof", "build.rbf"]
        else:
            cmd = [os.path.join(qb, step), "build"]
        t0 = time.monotonic()
        r = heavy_guard.run_stall_guarded(cmd, step, log, stall_s=60, overall_s=heavy_guard.OVERALL_S[key], cwd=work)
        open(os.path.join(work, f"{step}.log"), "w").write(r.stdout + r.stderr)
        log.info("[%s] rc=%s %.1fs", step, r.returncode, time.monotonic() - t0)
        if r.returncode:
            return step
    return None


# ---- diff ----------------------------------------------------------------------------------------

def bt_of(rbf, compat=False):
    """Native decode -> .bt lines.  compat=True for the lifter input: the default mode also emits the SCLK/DCMUX
    links libmistral skips, and the lifter's clock-tree resolution then loses the clock pad net."""
    import cyclonev_decode as nd
    m = nd.decode(open(rbf, "rb").read(), DEVICE, compat=compat)
    return m.bt_lines()


def region(line):
    """Fault category of a .bt line."""
    k, rest = line[0], line[2:].split()
    if k == "o":
        return "option"
    if k == "r":
        dst = rest[1] if len(rest) > 1 else rest[0]
        return "route:" + dst.split(".")[0].split(":")[0]
    if k == "i":
        return "inverter"
    node = rest[0]
    blk = node.split(".")[0]
    port = node.split(":")[-1].split(".")[0] if ":" in node else ""
    if blk in ("LAB", "MLAB") and port == "LUT_MASK":
        return "setting:LUT_MASK"
    return f"setting:{blk}"


def key_of(line):
    k, rest = line[0], line[2:].split(" ; ")[0].split()
    if k == "r":
        return ("r", rest[1])          # routing: keyed by sink; value = source
    if k == "o":
        return ("o", rest[0])
    return (k, rest[0])


def val_of(line):
    k, rest = line[0], line[2:].split(" ; ")[0].split()
    return rest[0] if k == "r" else " ".join(rest[1:])


def diff_bt(orig, new):
    """Per region counters {matched, missing, extra, wrong} and sample lines."""
    o = {key_of(ln): ln for ln in orig if ln and ln[0] in "rsio"}
    n = {key_of(ln): ln for ln in new if ln and ln[0] in "rsio"}
    c = collections.defaultdict(collections.Counter)
    samples = collections.defaultdict(list)
    for k, ln in o.items():
        reg = region(ln)
        if k not in n:
            c[reg]["missing"] += 1
            samples[reg].append(("missing", ln))
        elif val_of(n[k]) == val_of(ln):
            c[reg]["matched"] += 1
        else:
            c[reg]["wrong"] += 1
            samples[reg].append(("wrong", ln + "  =>  " + n[k]))
    for k, ln in n.items():
        if k not in o:
            reg = region(ln)
            c[reg]["extra"] += 1
            samples[reg].append(("extra", ln))
    return c, samples


def bit_xor(a, b):
    n = min(len(a), len(b))
    x = int.from_bytes(a[:n], "big") ^ int.from_bytes(b[:n], "big")
    return x.bit_count(), len(a), len(b)


def headline(c):
    m, tot = c["matched"], sum(c[k] for k in ("matched", "missing", "extra", "wrong"))
    return m, tot, (m / tot if tot else float("nan"))


# ---- driver --------------------------------------------------------------------------------------

def original_names(design):
    """Stage B: original post-fit atom / port names by physical place (names the RCF refers to)."""
    import sqlite3
    db = os.path.join(CORPUS, "corpus.db")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute("select a.name, a.type, a.location, a.loc_kind, a.x, a.y, a.n from postfit_atoms a "
                     "join corpus_builds b on a.build=b.id where b.design=?", (design,)).fetchall()
    return rows


def run_design(design, rcf, skip_quartus):
    from lifters.cyclonev_lift import CycloneVLift
    src = os.path.join(CORPUS, design)
    work = os.path.join(WORK, design + ("_rcf" if rcf else ""))
    os.makedirs(work, exist_ok=True)
    orig_rbf = os.path.join(src, "bitstream.rbf")
    orig_bt = bt_of(orig_rbf)
    open(os.path.join(work, "orig.bt"), "w").write("\n".join(bt_of(orig_rbf, compat=True)) + "\n")
    lift = CycloneVLift(DEVICE)
    pc = lift.parse_config(os.path.join(work, "orig.bt"))
    d = lift.recover_netlist(pc)
    names = None
    if rcf:
        names = rcf_names(design, d)
    top, text, qsf, notes = emit(d, names)
    open(os.path.join(work, "reenc.v"), "w").write(text)
    open(os.path.join(work, "assign.qsf"), "w").write("\n".join(qsf) + "\n")
    log.info("%s: emitted %d lines, notes %s", design, text.count("\n"), dict(notes))
    res = {"design": design, "stage": "B(rcf)" if rcf else "A", "notes": dict(notes)}
    rcf_file = None
    if rcf:
        rcf_file = "orig.rcf"
        shutil.copyfile(os.path.join(src, "build.rcf"), os.path.join(work, rcf_file))
    new_rbf = os.path.join(work, "build.rbf")
    if not skip_quartus:
        for f in os.listdir(work):
            if f.endswith((".rbf", ".sof")) or f in ("db", "incremental_db", "qdb"):
                p = os.path.join(work, f)
                shutil.rmtree(p) if os.path.isdir(p) else os.unlink(p)
        failed = quartus(work, rcf_file, top)
        if failed:
            res["failed"] = failed
            return res
    new_bt = bt_of(new_rbf)
    open(os.path.join(work, "new.bt"), "w").write("\n".join(new_bt) + "\n")
    c, samples = diff_bt(orig_bt, new_bt)
    total = collections.Counter()
    for reg in c:
        total.update(c[reg])
    xor, la, lb = bit_xor(open(orig_rbf, "rb").read(), open(new_rbf, "rb").read())
    res.update(regions={r: dict(v) for r, v in sorted(c.items())}, total=dict(total), rbf_xor_bits=xor,
               rbf_len=[la, lb], headline=headline(total))
    with open(os.path.join(work, "faults.txt"), "w") as fh:
        for reg, ss in sorted(samples.items()):
            for kind, ln in ss:
                fh.write(f"{reg}\t{kind}\t{ln}\n")
    m, tot, h = res["headline"]
    log.info("%s %s: matched %d / %d = %.2f%%  rbf xor bits %d", design, res["stage"], m, tot, 100 * h, xor)
    for reg, v in sorted(c.items()):
        log.info("   %-22s matched %-5d missing %-5d extra %-5d wrong %-5d", reg, v["matched"], v["missing"],
                 v["extra"], v["wrong"])
    return res


def rcf_names(design, d):
    """{("pad", label) | ("lut", lifted name) | ("ff", lifted name): original post-fit atom name} by place."""
    by_pin, by_place = {}, {}
    for name, typ, loc, kind, x, y, n in original_names(design):
        if kind == "PIN":
            by_pin[loc[len("PIN_"):]] = name
        elif kind in ("LABCELL", "MLABCELL"):
            by_place[("lut", x, y, n)] = name
        elif kind == "FF":
            by_place[("ff", x, y, n)] = name
    names = {("pad", lab): nm for lab, nm in by_pin.items()}
    for lt in d.luts:
        if lt.get("block") == "LAB" and lt.get("role", "sum") == "sum":
            nm = by_place.get(("lut", lt["x"], lt["y"], lcell_n(lt["alm"], lt["half"])))
            if nm:
                names[("lut", lt["name"])] = nm
    for ff in d.ffs:
        nm = by_place.get(("ff", ff["x"], ff["y"], ff_n(ff["alm"], ff["half"], ff["slot"])))
        if nm:
            names[("ff", ff["name"])] = nm
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("designs", nargs="+")
    ap.add_argument("--rcf", action="store_true", help="stage B: import the original build's RCF (oracle routing)")
    ap.add_argument("--skip-quartus", action="store_true", help="reuse the regenerated .rbf in the work dir")
    a = ap.parse_args()
    setup_logging()
    results = []
    with heavy_guard.heavy_lock("cyclonev_reencode", log):
        for dsg in a.designs:
            if not a.skip_quartus:
                heavy_guard.wait_available(log, dsg)
            results.append(run_design(dsg, a.rcf, a.skip_quartus))
    out = os.path.join(WORK, "results.json")
    old = json.load(open(out)) if os.path.exists(out) else {}
    for r in results:
        old[r["design"] + ("_rcf" if a.rcf else "")] = r
    json.dump(old, open(out, "w"), indent=1)


if __name__ == "__main__":
    main()
