#!/usr/bin/env python3.15t
"""Cyclone IV GX M9K specimens, RAW cram-plane diff (issue #141). No Dec.active, no asm decode.

Pair = two designs identical except ONE thing (init bit, a parameter, a pin...). Answer = set bits
only in one plane (cycloneiv_corpus.cram_plane keys), as (frame, v).  Design prefix gxm9k_*.

  python3.15t scripts/cycloneiv_m9k.py gen   <set> [--jobs N]     # write src/ + design.toml for a set
  python3.15t scripts/cycloneiv_m9k.py build <set> [--jobs N]     # Quartus (trimmed after each build)
  python3.15t scripts/cycloneiv_m9k.py diff  <set>                # raw diffs -> tmp/cycloneiv_m9k_<set>.json
Sets: see SETS.  Log tmp/logs/cycloneiv_m9k.log.  Binding rules: docs/recovery-process.md.
"""
import argparse
import datetime
import json
import logging
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cycloneiv_corpus as cc  # noqa: E402
import cycloneiv_fuzz as fz  # noqa: E402
import toolchain  # noqa: E402

log = logging.getLogger("cycloneiv_m9k")
CORPUS = REPO / "corpus" / "cycloneiv"
DEVICE = "EP4CGX150DF31C7"
SITE = "M9K_X23_Y40_N0"
BITS = 2048          # bits per mem_init parameter; 5 per M9K (4096 data + parity 512 per 2 params, linear order)


def mem_init(ones, nparams=5):
    """ones: set of linear memory-bit indices (word*width + bit) -> mem_init0..4 parameter lines."""
    out = []
    for p in range(nparams):
        val = 0
        for i in ones:
            if p * BITS <= i < (p + 1) * BITS:
                val |= 1 << (i - p * BITS)
        out.append(f".mem_init{p}({BITS}'h{val:0{BITS // 4}x})")
    return out


def ram_design(width=1, depth=8192, mode="single_port", ones=(), site=SITE, extra=None, conns=None):
    """One cycloneiv_ram_block WYSIWYG at `site`.  extra = parameter overrides {name: verilog literal}."""
    aw = (depth - 1).bit_length()
    prm = {
        "operation_mode": f'"{mode}"', "ram_block_type": '"M9K"', "logical_ram_name": '"ram"',
        "port_a_logical_ram_depth": depth, "port_a_logical_ram_width": width,
        "port_a_first_address": 0, "port_a_last_address": depth - 1, "port_a_first_bit_number": 0,
        "port_a_data_width": width, "port_a_address_width": aw, "power_up_uninitialized": '"false"',
    }
    prm.update(extra or {})
    pl = ",\n    ".join(f".{k}({v})" for k, v in prm.items()) + ",\n    " + ",\n    ".join(mem_init(set(ones)))
    v = (f"module top(input clk, input we, input [{aw - 1}:0] addr, input [{width - 1}:0] d, "
         f"output [{width - 1}:0] q);\n"
         f"  cycloneiv_ram_block #(\n    {pl}\n  ) ram (\n"
         f"    .clk0(clk), .portawe(we), .portaaddr(addr), .portadatain(d), .portadataout(q));\n"
         "endmodule\n")
    qsf = [f"set_location_assignment {site} -to ram"]
    return v, qsf


def write_design(name, v, qsf, purpose):
    d = CORPUS / name
    if (d / "bitstream.rbf").exists():
        return
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "src" / "top.v").write_text(v)
    q = list(qsf) + ["set_global_assignment -name SEED 1", 'set_global_assignment -name FITTER_EFFORT "FAST FIT"']
    ver = re.search(r"quartus-([\d.]+)", toolchain.quartus_bin())
    (d / "design.toml").write_text(
        f'top = "top"\npurpose = "{purpose}"\nexercises = {fz.toml_list(["m9k"])}\n'
        f"qsf = {fz.toml_list(q)}\ndevice = \"{DEVICE}\"\ntool = \"quartus\"\n"
        f'tool_version = "{ver.group(1) if ver else "unknown"}"\nbuilt = "{datetime.date.today().isoformat()}"\n')


def sets():
    """{set: [(base, specimen, design-kwargs-base, design-kwargs-specimen, purpose)]}"""
    s = {}
    p0 = []
    for r in range(4):                      # r0 = first build, r1..r3 = rebuilds of the same pair
        p0.append((f"gxm9k_p0_base_r{r}", f"gxm9k_p0_w0b0_r{r}", {}, {"ones": {0}}, "word0 bit0 init 1"))
    s["p0"] = p0
    return s


DEPTH = {1: 8192, 2: 4096, 4: 2048, 8: 1024, 9: 1024, 16: 512, 18: 512, 32: 256, 36: 256}


def data_pairs(width, items, site=SITE, tag="d"):
    """Shared all-zero base + one specimen per (word, bit); init bit at linear index word*width+bit."""
    depth = DEPTH[width]
    base = f"gxm9k_{tag}{width}_base"
    out = [(base, f"gxm9k_{tag}{width}_w{w}b{b}", {"width": width, "depth": depth, "site": site},
            {"width": width, "depth": depth, "site": site, "ones": {w * width + b}}, f"init word {w} bit {b}")
           for w, b in items]
    return out


def bin_pairs(width, site=SITE):
    """Binary-coded init: specimen k sets cell c iff bit k of (c+1) is set; shared all-zero base."""
    n = DEPTH[width] * width
    nb = n.bit_length()          # codes 1..n
    base = f"gxm9k_b{width}_base"
    kw = {"width": width, "depth": DEPTH[width], "site": site}
    return [(base, f"gxm9k_b{width}_k{k}", dict(kw),
             dict(kw, ones={c for c in range(n) if ((c + 1) >> k) & 1}), f"bincode bit {k}") for k in range(nb)]


def rand_ones(width, seed):
    import random
    n = DEPTH[width] * width
    return set(random.Random(seed).sample(range(n), n // 2))


def rand_pairs(width, seed, site=SITE):
    kw = {"width": width, "depth": DEPTH[width], "site": site}
    return [(f"gxm9k_b{width}_base", f"gxm9k_r{width}_s{seed}", dict(kw), dict(kw, ones=rand_ones(width, seed)),
             f"random half-filled init seed {seed}")]


def predict(width, sp):
    """Predicted only_spec set from the located-cell map; None if the pair is not predictable."""
    mp = REPO / "tmp" / f"cycloneiv_m9k_map{width}.json"
    if not mp.exists():
        return None
    cells = {int(k): tuple(v) for k, v in json.loads(mp.read_text())["cells"].items()}
    m = re.match(rf"gxm9k_d{width}_w(\d+)b(\d+)$", sp)
    if m:
        return {cells[int(m[1]) * width + int(m[2])]}
    m = re.match(rf"gxm9k_r{width}_s(\d+)$", sp)
    if m:
        return {cells[c] for c in rand_ones(width, int(m[1]))}
    return None


def bin_decode(width, rep):
    """rep: {spec: {only_spec: [(f, v)]}} -> {code: (f, v)} + leftovers.  v >= 6344: lane tail / CRC bytes, masked."""
    n = DEPTH[width] * width
    code = {}
    for sp, r in rep.items():
        k = int(sp.rsplit("_k", 1)[1])
        for f, v in r["only_spec"]:
            code[(f, v)] = code.get((f, v), 0) | (1 << k)
        assert not r["only_base"], f"{sp}: bits only in base {r['only_base'][:4]}"
    cells, masked, bad = {}, [], []
    for (f, v), c in code.items():
        if v >= 6344:
            masked.append((f, v, c))
        elif 1 <= c <= n and c - 1 not in cells:
            cells[c - 1] = (f, v)
        else:
            bad.append((f, v, c))
    return cells, masked, bad


def bits(name):
    return set(cc.load_plane_only(name).keys.tolist())


def fv(k):
    return divmod(k, 6368)


def trim(n):
    for sub in ("quartus/db", "quartus/incremental_db"):
        shutil.rmtree(CORPUS / n / sub, ignore_errors=True)
    (CORPUS / n / "quartus" / "build.rbf").unlink(missing_ok=True)


def prune(n):
    """Diff recorded: drop bitstream + postfit + logs, keep rcf/toml/src."""
    d = CORPUS / n
    for f in ("bitstream.rbf", "postfit.vo", "fit.rpt", "build.pin"):
        (d / f).unlink(missing_ok=True)
    shutil.rmtree(d / "quartus", ignore_errors=True)
    shutil.rmtree(d / "logs", ignore_errors=True)


def build(names, jobs):
    def one(n):
        f = fz.build_one(n)
        trim(n)
        log.info("%s: %s", n, "ok" if f is None else f"FAIL at {f}")
        return n, f
    with ThreadPoolExecutor(jobs) as ex:
        return dict(ex.map(one, names))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["gen", "build", "diff"])
    ap.add_argument("set", help="named set, or 'data'")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--width", type=int, default=1)
    ap.add_argument("--items", default="", help="data set: word:bit,word:bit,...")
    ap.add_argument("--site", default=SITE)
    ap.add_argument("--tag", default="d")
    ap.add_argument("--keep", type=int, default=0, help="diff: keep bitstreams of the first N specimens")
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_m9k.log"),
                                  logging.StreamHandler()])
    if a.set == "rand":
        pairs = rand_pairs(a.width, int(a.items), a.site)
    elif a.set == "bincode":
        pairs = bin_pairs(a.width, a.site)
    elif a.set == "data":
        pairs = data_pairs(a.width, [tuple(map(int, i.split(":"))) for i in a.items.split(",")], a.site, a.tag)
    else:
        pairs = sets()[a.set]
    names = list(dict.fromkeys(n for p in pairs for n in p[:2]))
    if a.cmd in ("gen", "build"):
        for b, sp, kb, ks, purpose in pairs:
            write_design(b, *ram_design(**kb), purpose + " (base)")
            write_design(sp, *ram_design(**ks), purpose)
    if a.cmd == "build":
        todo = [n for n in names if not (CORPUS / n / "bitstream.rbf").exists()]
        res = build(todo, a.jobs)
        log.info("built %d, failed %s", len(todo), [n for n, f in res.items() if f])
    if a.cmd == "diff":
        rep = {}
        out = REPO / "tmp" / f"cycloneiv_m9k_{a.set}{a.width}{a.tag}.json"
        if out.exists():
            rep = json.loads(out.read_text())
        cache = {}
        for i, (b, sp, *_) in enumerate(pairs):
            if sp in rep:
                continue
            if b not in cache:
                cache[b] = bits(b)
            A, B = cache[b], bits(sp)
            rep[sp] = {"base": b, "only_base": [fv(k) for k in sorted(A - B)],
                       "only_spec": [fv(k) for k in sorted(B - A)]}
            pr = predict(a.width, sp)
            if pr is not None:
                got = {tuple(x) for x in rep[sp]["only_spec"]}
                rep[sp]["predicted_hit"] = bool(got == pr and not rep[sp]["only_base"])
                rep[sp]["pred_missing"], rep[sp]["pred_extra"] = len(pr - got), len(got - pr)
                log.info("PREDICT %s: hit=%s missing %d extra %d (of %d)", sp, rep[sp]["predicted_hit"],
                         len(pr - got), len(got - pr), len(pr))
            log.info("%s vs %s: only-base %s only-spec %s", b, sp, rep[sp]["only_base"][:8], rep[sp]["only_spec"][:8])
            if i >= a.keep:
                prune(sp)
        out.write_text(json.dumps(rep))
        if a.set == "bincode":
            cells, masked, bad = bin_decode(a.width, rep)
            n = DEPTH[a.width] * a.width
            log.info("bincode x%d: %d / %d cells located, masked CRC/tail %d, unattributed %d %s", a.width,
                     len(cells), n, len(masked), len(bad), bad[:6])
            (REPO / "tmp" / f"cycloneiv_m9k_map{a.width}.json").write_text(json.dumps(
                {"width": a.width, "cells": {str(c): fvv for c, fvv in sorted(cells.items())},
                 "masked": masked, "unattributed": bad}))


if __name__ == "__main__":
    main()
