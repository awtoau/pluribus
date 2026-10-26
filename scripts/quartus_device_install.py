#!/usr/bin/env python3.15t
"""Add a device-support .qdz to the existing Quartus install with the install's own device
installer (quartus/common/devinfo/dev_install/dev_install.run, unattended), then verify.

  python3.15t scripts/quartus_device_install.py --qdz-dir DIR --component cyclone [--family "Cyclone IV E"]
DIR must hold only the .qdz to add (dev_install installs what it finds there).
Log: tmp/logs/quartus_device_install.log
"""
import argparse
import logging
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402

ALL = ("quartus quartus_help devinfo arria_lite cyclone cyclone10lp cyclonev max max10 "
       "quartus_update riscfree questa_fse questa_fe").split()
# Cyclone V qdz install took 37 s for 1.4 GB (install log 2026-10-23); 3x a cold worst case of
# ~5 min = 15 min backstop; expiry kills the installer and fails.
LIMIT_S = 900


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qdz-dir", required=True)
    ap.add_argument("--component", required=True, choices=ALL)
    ap.add_argument("--family", action="append", default=[])
    a = ap.parse_args()
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(REPO / "tmp" / "logs" / "quartus_device_install.log")])
    log = logging.getLogger()
    qb = pathlib.Path(str(toolchain.quartus_bin()))
    root = qb.parent.parent
    inst = qb.parent / "common" / "devinfo" / "dev_install" / "dev_install.run"
    cmd = [str(inst), "--mode", "unattended", "--unattendedmodeui", "none", "--accept_eula", "1",
           "--downloaddir", str(pathlib.Path(a.qdz_dir).resolve()), "--installdir", str(root),
           "--enable-components", a.component,
           "--disable-components", ",".join(c for c in ALL if c not in (a.component, "devinfo"))]
    with heavy_guard.heavy_lock("quartus_device_install", log):
        heavy_guard.wait_available(log, "dev_install", 4)
        log.info("+ %s", " ".join(cmd))
        r = heavy_guard.guarded(cmd, "quartus device install", log, overall_s=LIMIT_S)  # #122
        log.info("rc=%d\n%s", r.returncode, (r.stdout + r.stderr)[-3000:])
        if r.returncode:
            return 1
        v = heavy_guard.guarded([str(qb / "quartus_sh"), "--tcl_eval", "get_family_list"], "quartus_sh", log,
                                overall_s=120)  # #122
        log.info("get_family_list: %s", v.stdout.strip())
        missing = [f for f in a.family if f not in v.stdout]
        if missing:
            log.error("families still missing: %s", missing)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
