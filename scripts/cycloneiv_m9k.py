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


def bits(name):
    return set(cc.load_plane_only(name).keys.tolist())


def fv(k):
    return divmod(k, 6368)


def trim(n):
    for sub in ("quartus/db", "quartus/incremental_db"):
        shutil.rmtree(CORPUS / n / sub, ignore_errors=True)
    (CORPUS / n / "quartus" / "build.rbf").unlink(missing_ok=True)


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
    ap.add_argument("set")
    ap.add_argument("--jobs", type=int, default=2)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_m9k.log"),
                                  logging.StreamHandler()])
    pairs = sets()[a.set]
    names = [n for p in pairs for n in p[:2]]
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
        for b, sp, *_ in pairs:
            A, B = bits(b), bits(sp)
            rep[sp] = {"base": b, "only_base": [fv(k) for k in sorted(A - B)],
                       "only_spec": [fv(k) for k in sorted(B - A)]}
            log.info("%s vs %s: only-base %s only-spec %s", b, sp, rep[sp]["only_base"][:8], rep[sp]["only_spec"][:8])
        (REPO / "tmp" / f"cycloneiv_m9k_{a.set}.json").write_text(json.dumps(rep))


if __name__ == "__main__":
    main()
