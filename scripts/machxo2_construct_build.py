#!/usr/bin/env python3.15t
"""Build MachXO2 construct / coverage designs with Diamond (LSE) and extract the oracle.

Per design dir D (default corpus/machxo2/constructs):
  D/<name>/src/*.v|*.sv  design.toml  [placement.lpf]      (tracked)
  D/<name>/run.tcl impl1/ ncdread.txt routing.nmc oracle.json postpar.vo
            bitstream.bit decoded.config compare.json build.json logs/   (untracked)

Steps per design, strictly sequential (single Diamond seat, ~0.4 GB each):
  diamondc (LSE, map, PAR, bitgen) -> ncdread + ncd2nmc -> oracle.json
  -> ldbanno postpar.vo -> bitstream.bit copy.
Resumable: a design with build.json status ok|failed and sources older than it is skipped.

Usage: python3.15t scripts/machxo2_construct_build.py [--dir D] [--match SUBSTR ...]
       [--force] [--limit N] [--no-oracle]
Log: tmp/logs/machxo2_construct_build.log
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)
import toolchain  # noqa: E402
import heavy_guard  # noqa: E402
import machxo2_diamond_oracle as OR  # noqa: E402
import diamond_oracle_parse as P  # noqa: E402

REPO = OR.REPO
DEFAULT_DIR = os.path.join(REPO, "corpus", "machxo2", "constructs")
LOG_PATH = os.path.join(REPO, "tmp", "logs", "machxo2_construct_build.log")
DEVICE = "LCMXO2-1200HC-5TG100C"
# diamondc whole flow (LSE+map+PAR+bitgen): 10-20 s measured (task brief, 2026-10-24);
# stall guard per awto-dan#53: no new output in the project log for 60 s = hung,
# backstop 3x the 20 s cold worst case = 60 s is below the stall guard, so use 180 s.
# Expiry: kill, record status "timeout" with elapsed.
FLOW_BACKSTOP_S = 180
# ldbanno: sub-second tool; 5 s = generous x10 on first-run cold start. Expiry: recorded.
ANNO_TIMEOUT_S = 5


def log(msg):
    line = f"{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}  {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as fh:
        fh.write(line + "\n")


class _Log:  # adapter for heavy_guard (expects .info)
    @staticmethod
    def info(fmt, *args):
        log(fmt % args if args else fmt)


def sources(d):
    sd = os.path.join(d, "src")
    return sorted(f for f in os.listdir(sd) if f.endswith((".v", ".sv")))


def tcl_text(d):
    srcs = " ".join(f'"src/{f}"' for f in sources(d))
    lines = [f'prj_project new -name "fuzz" -impl "impl1" -dev {DEVICE} -synthesis "lse"']
    for f in sources(d):
        lines.append(f'prj_src add "src/{f}"')
    if os.path.exists(os.path.join(d, "placement.lpf")):
        # project's own fuzz.lpf is rewritten in place (adding a second LPF collides)
        lpf = open(os.path.join(d, "placement.lpf")).read().strip()
        lines.append('set _fp [open "fuzz.lpf" w]')
        lines.append("puts $_fp {%s}" % lpf)
        lines.append("close $_fp")
    lines += ['prj_run PAR -impl impl1 -forceOne',
              'prj_run Export -impl impl1 -task Bitgen',
              'prj_project save', 'prj_project close']
    del srcs
    return "\n".join(lines) + "\n"


def first_errors(d, n=3):
    """First ERROR lines from the Diamond logs (exact text is a result)."""
    out = []
    for f in ("diamond.log", os.path.join("impl1", "synthesis.log")):
        p = os.path.join(d, f)
        if not os.path.exists(p):
            continue
        for line in open(p, errors="replace"):
            if re.search(r"\bERROR\b|^ERROR|@E:|Error:", line):
                s = line.strip()
                if s not in out:
                    out.append(s)
            if len(out) >= n:
                return out
    return out


def run_flow(d, env):
    """diamondc with a stall guard (no new log bytes for 60 s) and a backstop."""
    logp = os.path.join(d, "diamond.log")
    t0 = time.monotonic()
    with open(logp, "w") as fh:
        proc = subprocess.Popen([os.path.join(OR.toolchain.diamond_root(), "bin", "lin64", "diamondc"),
                                 "run.tcl"], cwd=d, env=env, stdout=fh, stderr=subprocess.STDOUT)
        last_size, last_change = 0, t0
        while True:
            try:
                proc.wait(timeout=2)  # poll period: log growth is checked every 2 s
                break
            except subprocess.TimeoutExpired:
                now = time.monotonic()
                size = os.path.getsize(logp)
                if size != last_size:
                    last_size, last_change = size, now
                stalled = now - last_change >= 60
                if stalled or now - t0 >= FLOW_BACKSTOP_S:
                    proc.kill()
                    proc.wait()
                    la = open(logp, errors="replace").read().strip().splitlines()[-1:]
                    return "timeout", time.monotonic() - t0, (
                        f"{'stall 60s' if stalled else 'backstop %ds' % FLOW_BACKSTOP_S}; "
                        f"elapsed {now - t0:.0f}s; last line {la}; loadavg {os.getloadavg()[0]:.1f}")
    return ("ok" if proc.returncode == 0 else "rc%d" % proc.returncode), time.monotonic() - t0, ""


def build_one(d, env, do_oracle):
    name = os.path.basename(d)
    for stale in ("impl1", "fuzz.ldf", "fuzz.lpf", "diamond.log", "ncdread.txt", "routing.nmc",
                  "oracle.json", "postpar.vo", "bitstream.bit", "decoded.config", "compare.json"):
        p = os.path.join(d, stale)
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.exists(p):
            os.remove(p)
    with open(os.path.join(d, "run.tcl"), "w") as fh:
        fh.write(tcl_text(d))
    heavy_guard.wait_available(_Log, name)
    st, secs, why = run_flow(d, env)
    res = {"name": name, "flow_status": st, "flow_seconds": round(secs, 1),
           "schema": 1, "built": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    ncd = os.path.join(d, "impl1", "fuzz_impl1.ncd")
    bit = os.path.join(d, "impl1", "fuzz_impl1.bit")
    if st == "timeout":
        res.update(status="failed", reason=why)
    elif not os.path.exists(ncd) or not os.path.exists(bit):
        errs = first_errors(d)
        res.update(status="failed", reason="; ".join(errs) or f"flow {st}, no ncd/bit")
    else:
        shutil.copy(bit, os.path.join(d, "bitstream.bit"))
        res["status"] = "ok"
        os.makedirs(os.path.join(d, "logs"), exist_ok=True)
        for f in ("diamond.log",):
            shutil.copy(os.path.join(d, f), os.path.join(d, "logs", f))
        for f in os.listdir(os.path.join(d, "impl1")):
            if f.endswith((".mrp", ".par", ".twr", ".log")) and "map" not in f[:0]:
                shutil.copy(os.path.join(d, "impl1", f), os.path.join(d, "logs", f))
        res["warnings"] = len([1 for line in open(os.path.join(d, "diamond.log"), errors="replace")
                               if line.startswith("WARNING")])
        if do_oracle:
            try:
                r = OR.process(name, os.path.dirname(d), os.path.dirname(d), env,
                               os.path.join(toolchain.diamond_root(), "ispfpga", "bin", "lin64"), True)
                res["oracle"] = r["status"]
            except (OR.ToolError, P.FormatError) as e:
                res["oracle"] = "failed: " + str(e)
            try:
                anno = os.path.join(toolchain.diamond_root(), "ispfpga", "bin", "lin64", "ldbanno")
                subprocess.run([anno, "-n", "Verilog", "-o", "postpar.vo", "impl1/fuzz_impl1.ncd"],
                               cwd=d, env=env, capture_output=True, text=True,
                               timeout=ANNO_TIMEOUT_S)
                res["postpar_vo"] = os.path.exists(os.path.join(d, "postpar.vo"))
            except subprocess.TimeoutExpired:
                res["postpar_vo"] = False
                log(f"[warn] {name}: ldbanno exceeded {ANNO_TIMEOUT_S}s")
    res["src_sha256"] = src_hash(d)
    with open(os.path.join(d, "build.json"), "w") as fh:
        json.dump(res, fh, indent=1, sort_keys=True)
    return res


def src_hash(d):
    import hashlib
    h = hashlib.sha256()
    names = [os.path.join("src", f) for f in sorted(os.listdir(os.path.join(d, "src")))]
    names += [f for f in ("placement.lpf", "design.toml") if os.path.exists(os.path.join(d, f))]
    for n in names:
        h.update(n.encode())
        h.update(open(os.path.join(d, n), "rb").read())
    return h.hexdigest()


def up_to_date(d):
    """Content hash, not mtime: a checkout or regenerate must not trigger rebuilds."""
    bj = os.path.join(d, "build.json")
    if not os.path.exists(bj):
        return False
    return json.load(open(bj)).get("src_sha256") == src_hash(d)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--match", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-oracle", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.dir)
    names = sorted(n for n in os.listdir(root)
                   if os.path.exists(os.path.join(root, n, "design.toml")))
    if a.match:
        names = [n for n in names if any(m in n for m in a.match)]
    if a.limit:
        names = names[:a.limit]
    _, env = OR.diamond_env()
    env["LM_LICENSE_FILE"] = os.path.join(toolchain.diamond_root(), "license", "license.dat")
    log(f"[build] {len(names)} designs in {root}")
    cnt = {}
    for i, n in enumerate(names, 1):
        d = os.path.join(root, n)
        if not a.force and up_to_date(d):
            cnt["skipped"] = cnt.get("skipped", 0) + 1
            continue
        r = build_one(d, env, not a.no_oracle)
        cnt[r["status"]] = cnt.get(r["status"], 0) + 1
        log(f"[build] {i}/{len(names)} {n}: {r['status']} {r['flow_seconds']}s "
            f"{r.get('reason', '')[:160]}")
    log(f"[build] done: {cnt}")


if __name__ == "__main__":
    main()
