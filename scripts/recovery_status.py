"""Is the Cyclone IV specimen pipeline alive and still correct?  (docs/recovery-process.md)

  python3.15t scripts/recovery_status.py status    # read-only: processes, log freshness, builds, disk
  python3.15t scripts/recovery_status.py canary    # known-answer test: rebuild the Tier-0 pair, diff must match

status: stall = newest tmp/logs file untouched for STALL_S while a build process runs (hang).
canary: fixed one-LUT pair built end-to-end; any change in the raw diff means the toolchain,
the bitstream reader or the diff code changed under us.  Run before/after every sweep.
Log: tmp/logs/recovery_status.log
"""
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
CORPUS = REPO / "corpus" / "cycloneiv"
LOGS = REPO / "tmp" / "logs"
STALL_S = 60            # same stall limit as cycloneiv_fuzz.run: a build step prints or burns CPU within this
MIN_FREE_GB = 10        # sweeps stop below this (ENOSPC hit twice on 2026-10-28)
# Known answer: Tier-0 self-loop, LCCOMB_X10_Y10_N0, mask FFFF; recorded 2026-10-28 (#141).
CANARY_BITS = [4146287, 4184495, 4254543]

log = logging.getLogger("recovery_status")


def status():
    ps = subprocess.run(["ps", "-eo", "pid,etime,args"], capture_output=True, text=True).stdout.splitlines()
    runs = [p for p in ps if ("cycloneiv_forced" in p or "cycloneiv_specimens" in p) and "recovery_status" not in p]
    quartus = [p for p in ps if "quartus_" in p and "grep" not in p]
    log.info("sweep processes: %d; quartus steps running: %d", len(runs), len(quartus))
    for r in runs:
        log.info("  %s", r.strip()[:140])
    newest = max(LOGS.glob("*.out"), key=lambda p: p.stat().st_mtime, default=None)
    if newest:
        age = time.time() - newest.stat().st_mtime
        log.info("newest log %s, %.0fs old", newest.name, age)
        if runs and age > STALL_S:
            log.error("STALL: sweep running but newest log idle %.0fs > %ds", age, STALL_S)
    ok = bad = 0
    for d in CORPUS.iterdir():
        if d.is_dir() and (d / "routing.rcf").exists():
            if (d / "bitstream.rbf").exists():
                ok += 1
            else:
                bad += 1
    log.info("corpus dirs: %d with rbf+rcf, %d rcf-only (trimmed)", ok, bad)
    free = shutil.disk_usage(REPO).free / 2**30
    (log.error if free < MIN_FREE_GB else log.info)("disk free %.1f GB (floor %d)", free, MIN_FREE_GB)


def canary():
    import cycloneiv_forced as f
    ds = {k: v for k, v in f.tier_designs().items() if k.startswith("gxt0_")}
    names = {}
    for n, (v, q, p) in ds.items():
        cn = n.replace("gxt0_", "gxcanary_")
        f.write_design(cn, v, q, "canary: tier0 self-loop")
        names[n] = cn
    t0 = time.monotonic()
    res = f.build_all(list(names.values()), 2)
    if any(res.values()):
        log.error("CANARY FAIL: build error %s", res)
        return 1
    only_spec, only_base = f.diff(names["gxt0_s"], names["gxt0_b"])
    log.info("canary diff: only-spec %s only-base %s (%.0fs)", only_spec, only_base, time.monotonic() - t0)
    if only_spec != CANARY_BITS or only_base:
        log.error("CANARY FAIL: expected only-spec %s, none only-base", CANARY_BITS)
        return 1
    log.info("CANARY OK: toolchain + bitstream reader + diff reproduce the recorded answer")
    return 0


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(LOGS / "recovery_status.log")])
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status()
    elif cmd == "canary":
        sys.exit(canary())
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
