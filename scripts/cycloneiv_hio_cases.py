#!/usr/bin/env python3.15t
"""Minimal HIO-output cases (#168): one output on a bank-5 DIFFIO pad of EP4CGX150DF27I7 with different drivers; builds in tmp/hiocases/, then the clean emit reports the HIO data-mux status.

  python3.15t scripts/cycloneiv_hio_cases.py [--build]          Log: tmp/logs/cycloneiv_hio_cases.log
"""
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))
import cycloneiv_fuzz as FZ  # noqa: E402
import heavy_guard  # noqa: E402
from lifters.cycloneiv_clean import pinfile as PF  # noqa: E402

ROOT = REPO / "tmp" / "hiocases"
DEV = "EP4CGX150DF27I7"
OUT_PINS = ["AA24", "AA23", "AB24", "AC23", "U23"]       # the image's five HIO outputs without a LOCAL_INTERCONNECT source (F672 balls)
log = logging.getLogger("hio_cases")
# driver expressions of the output (a, b = inputs, c = clock input)
DRV = {"reg": "r", "comb": "a & b", "const1": "1'b1", "const0": "1'b0", "feed": "a", "regq": "r2"}


def specs():
    ins = [r["balls"]["F672"] for r in PF.rows() if PF.plain_io(r) and "F672" in r["balls"] and r["bank"] == "B5" and r["balls"]["F672"] not in OUT_PINS][:3]
    out = {}
    for k, e in DRV.items():
        for op in OUT_PINS[:2]:
            rtl = ("module top(input a, input b, input c, output o);\n  reg r, r2;\n  always @(posedge c) begin r <= a ^ b; r2 <= r; end\n"
                   f"  assign o = {e};\nendmodule\n")
            loc = [f"set_location_assignment PIN_{p} -to {n}" for p, n in zip(ins + [op], ("a", "b", "c", "o"))]
            out[f"{k}_{op}"] = (rtl, loc)
    vio = [r["balls"]["F672"] for r in PF.rows() if PF.plain_io(r) and "F672" in r["balls"] and r["bank"] == "B4"][:3]
    for k in ("reg", "const1", "const0"):                      # VIO output (the image's sixth output, bank 3 column I/O)
        rtl = ("module top(input a, input b, input c, output o);\n  reg r, r2;\n  always @(posedge c) begin r <= a ^ b; r2 <= r; end\n"
               f"  assign o = {DRV[k]};\nendmodule\n")
        out[f"vio_{k}_AB8"] = (rtl, [f"set_location_assignment PIN_{p} -to {n}" for p, n in zip(vio + ["AB8"], ("a", "b", "c", "o"))])
    return out


def main():
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    h = logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_hio_cases.log")
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(h)
    log.addHandler(logging.StreamHandler())
    FZ.log.addHandler(h)
    for n, (rtl, loc) in specs().items():
        d = ROOT / n
        (d / "src").mkdir(parents=True, exist_ok=True)
        (d / "src" / "top.v").write_text(rtl)
        (d / "design.toml").write_text(f'top = "top"\npurpose = "HIO output case"\nexercises = []\nqsf = {FZ.toml_list(loc)}\ndevice = "{DEV}"\n')
    if "--build" not in sys.argv:
        return
    FZ._tl.corpus = ROOT
    FZ._tl.qtmp = REPO / "tmp" / "hiocases_qtmp"
    with heavy_guard.heavy_lock("cycloneiv_hio_cases", log):
        for n in specs():
            if not (ROOT / n / "bitstream.rbf").exists():
                f = FZ.build_one(n)
                log.info("%s: %s", n, "ok" if f is None else f"FAIL at {f}")


if __name__ == "__main__":
    main()
