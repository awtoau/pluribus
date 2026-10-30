#!/usr/bin/env python3.15t
"""Package experiment (#172): the same RTL and the same pin LOCATIONs built for several EP4CGX150 packages / speed grades; builds land in tmp/pkgtest/ (not the corpus).

  python3.15t scripts/cycloneiv_pkgtest.py --build [--jobs 2]
Sets: `minpu` (min with the default weak pull-up unused option), `loc` (adder with PIN_ locations bonded in all three packages, from the official pin file), `free` (same RTL, fitter-placed), `min` (1 in / 1 out, fitter-placed).
Log: tmp/logs/cycloneiv_pkgtest.log
"""
import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))
import cycloneiv_fuzz as FZ  # noqa: E402
import heavy_guard  # noqa: E402
from lifters.cycloneiv_clean import pinfile as PF  # noqa: E402

ROOT = REPO / "tmp" / "pkgtest"
# source: part names of the experiment: the three requested parts + the other speed grades of each package (isolates package from speed / temperature)
DEVICES = ["EP4CGX150CF23C8", "EP4CGX150DF27I7", "EP4CGX150DF31C7", "EP4CGX150CF23C7", "EP4CGX150CF23I7", "EP4CGX150DF27C7", "EP4CGX150DF31I7"]
WIDTH = 16
STRIDE = 4          # spread the pins over the banks: every 4th common plain-I/O row of the pin file
log = logging.getLogger("pkgtest")


# source: part-name package codes of the Quartus device names (CF23 = F484, DF27 = F672, DF31 = F896); ball counts from the pin file columns
PKG_OF = {"CF23": "F484", "DF27": "F672", "DF31": "F896"}


def common_pins(n, pkg):
    """Same pad in every package = one pin-file row; the ball is that row's ball in `pkg`."""
    rows = [r for r in PF.rows() if PF.plain_io(r) and len(r["balls"]) == 3]
    return [r["balls"][pkg] for r in rows[::STRIDE][:n]]


def adder_rtl():
    return (f"module top(input [{WIDTH-1}:0] a, input [{WIDTH-1}:0] b, output [{WIDTH}:0] s);\n  assign s = a + b;\nendmodule\n")


# source: Quartus RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP option value "AS INPUT TRI-STATED WITH WEAK PULL-UP" (docs/cycloneiv-clean-io.md, unused-pin states)
PULLUP = 'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED WITH WEAK PULL-UP"'
MIN_RTL = "module top(input a, output y);\n  assign y = a;\nendmodule\n"


def specs():
    names = [f"a[{i}]" for i in range(WIDTH)] + [f"b[{i}]" for i in range(WIDTH)] + [f"s[{i}]" for i in range(WIDTH + 1)]
    out = {}
    for dev in DEVICES:
        pins = common_pins(3 * WIDTH + 1, PKG_OF[dev[9:13]])
        loc = [f"set_location_assignment PIN_{p} -to {n}" for p, n in zip(pins, names)]
        out[f"loc_{dev}"] = (adder_rtl(), loc, dev)
        out[f"free_{dev}"] = (adder_rtl(), [], dev)
    for dev in DEVICES[:3]:
        out[f"min_{dev}"] = (MIN_RTL, [], dev)
        out[f"minpu_{dev}"] = (MIN_RTL, [PULLUP], dev)       # the Quartus default unused-pin option (the image's bonded unused pads)
    return out


def generate():
    for name, (rtl, qsf, dev) in specs().items():
        d = ROOT / name
        (d / "src").mkdir(parents=True, exist_ok=True)
        (d / "src" / "top.v").write_text(rtl)
        q = FZ.toml_list(qsf)
        (d / "design.toml").write_text(f'top = "top"\npurpose = "package experiment"\nexercises = []\nqsf = {q}\ndevice = "{dev}"\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--jobs", type=int, default=2)
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    for h in (logging.FileHandler(REPO / "tmp" / "logs" / "cycloneiv_pkgtest.log"), logging.StreamHandler()):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    FZ.log.addHandler(log.handlers[0])
    FZ._tl.corpus = ROOT
    generate()
    if not a.build:
        return 0
    names = sorted(n for n in specs() if not (ROOT / n / "bitstream.rbf").exists())
    bad = {}

    def one(n):
        FZ._tl.corpus = ROOT
        FZ._tl.qtmp = REPO / "tmp" / "pkgtest_qtmp"
        heavy_guard.wait_available(log, n, FZ.JOB_MIN_GB)
        f = FZ.build_one(n)
        log.info("%s: %s", n, "ok" if f is None else f"FAIL at {f}")
        if f:
            bad[n] = f
    with heavy_guard.heavy_lock("cycloneiv_pkgtest", log):
        with ThreadPoolExecutor(max(1, min(a.jobs, FZ.MAX_JOBS))) as ex:
            list(ex.map(one, names))
    log.info("done %d, failed %d %s", len(names) - len(bad), len(bad), bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
