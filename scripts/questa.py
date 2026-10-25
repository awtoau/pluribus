#!/usr/bin/env python3.15t
"""Thin Questa-Altera (Starter) runner: vlib + vlog + vsim -c, against the precompiled Altera libraries.

- Install: QUESTA_HOME (default /mnt/2tb/opt/altera/quartus-25.1/questa_fse); libraries from its
  modelsim.ini (`cyclonev_ver`, `altera_ver`, `altera_lnsim_ver`, ...): vendor atoms incl. encrypted ones.
- Licence: QUESTA_LICENSE (default the Starter licence file) -> LM_LICENSE_FILE / SALT_LICENSE_SERVER.
  Used as issued; nothing here touches licence checks.
- Guard per tool call: STALL_S with no output = hung (killed, logged); LIMIT_S overall backstop.
Usage: python3.15t scripts/questa.py --work DIR --top tb [--lib cyclonev_ver ...] FILE...
Log: tmp/logs/questa.log
"""
import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "tmp" / "logs" / "questa.log"
HOME = Path(os.environ.get("QUESTA_HOME", "/mnt/2tb/opt/altera/quartus-25.1/questa_fse"))
BIN = HOME / "linux_x86_64"
LICENSE = os.environ.get("QUESTA_LICENSE", "/mnt/2tb/opt/altera/licenses/questa-starter-LR-204266.dat")
CV_LIBS = ("cyclonev_ver", "altera_ver", "altera_lnsim_ver", "altera_mf_ver", "lpm_ver")
STALL_S = 60     # shared-box rule: no output line for 60 s = hung
LIMIT_S = 600    # backstop for one vlog / vsim call


def available():
    return (BIN / "vsim").is_file() and Path(LICENSE).is_file()


def env():
    return dict(os.environ, LM_LICENSE_FILE=LICENSE, SALT_LICENSE_SERVER=LICENSE)


def _run(cmd, cwd):
    """One tool call with a stall guard -> (returncode, output); returncode None = killed."""
    p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env(), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)
    out, last = [], [time.monotonic()]

    def reader():
        for line in p.stdout:
            out.append(line)
            last[0] = time.monotonic()
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t0 = time.monotonic()
    while p.poll() is None:
        t.join(1.0)
        now = time.monotonic()
        why = (f"stalled {now - last[0]:.0f}s (limit {STALL_S}s)" if now - last[0] > STALL_S else
               f"ran {now - t0:.0f}s (limit {LIMIT_S}s)" if now - t0 > LIMIT_S else None)
        if why:
            p.kill()
            p.wait()
            tail = out[-1].strip() if out else "<no output>"
            return None, "".join(out) + (f"\nKILLED {Path(str(cmd[0])).name}: {why}; last line: {tail}; "
                                         f"loadavg {os.getloadavg()}\n")
    t.join()
    return p.returncode, "".join(out)


def compile_and_run(work, files, top, libs=CV_LIBS, vlog_args=(), vsim_args=()):
    """vlib work; vlog files; vsim -c top -> (ok, transcript). ok False on any tool error / kill."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    text = []
    if not (work / "work").is_dir():
        rc, o = _run([BIN / "vlib", "work"], work)
        text.append(o)
        if rc:
            return False, "".join(text)
    rc, o = _run([BIN / "vlog", "-quiet", *vlog_args, *[Path(f).resolve() for f in files]], work)
    text.append(o)
    if rc != 0:
        return False, "".join(text)
    lib_args = [a for lb in libs for a in ("-L", lb)]
    rc, o = _run([BIN / "vsim", "-c", "-quiet", *lib_args, *vsim_args, "-do", "run -all; quit -f", top], work)
    text.append(o)
    return rc == 0 and "** Fatal" not in o and "** Error" not in o, "".join(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--top", required=True)
    ap.add_argument("--lib", action="append", help="-L library (default: Cyclone V set)")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    ok, text = compile_and_run(a.work, a.files, a.top, tuple(a.lib) if a.lib else CV_LIBS)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(f"== {time.strftime('%Y-%m-%dT%H:%M:%S%z')} {a.top} {a.files}\n{text}\nok={ok}\n")
    print("\n".join(ln for ln in text.splitlines() if not ln.startswith("# //")))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
