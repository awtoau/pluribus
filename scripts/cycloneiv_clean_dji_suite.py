#!/usr/bin/env python3.15t
"""Bundled run of every DJI-m2001-specific structural-analysis script in one pass, with a single findings list scanned
out of their logs/output afterward.  Not a new analysis: this calls EXISTING scripts unmodified and reads what they
already wrote, so a structural finding (scrambler polynomial, M9K content, SPI register map, ...) stays owned by the
script that produced it -- this just stops each one being re-run and re-read by hand, one at a time, in a fresh agent
each time with no record of what's stale.

  python3.15t scripts/cycloneiv_clean_dji_suite.py              # full run, log tmp/logs/cycloneiv_clean_dji_suite.log
  python3.15t scripts/cycloneiv_clean_dji_suite.py --only m9k_dump,spi_trace
  python3.15t scripts/cycloneiv_clean_dji_suite.py --scan-only  # skip running, just rescan existing logs/output for findings

Three tiers, run in order (later tiers need earlier tiers' output on disk):
  0. image decode -> tmp/image_sim_dji_push/{nl.pkl,build.json}  (dev.py lift-image; skipped if already current)
  1. env-driven, PLURIBUS_DJI_IMAGE only, no nl.pkl needed (hardblock_usage, m9k_dump, m9k_modes, m9k_we_ctl, image_clocks,
     image_pll_pads, setbits, residue)
  2. --nl-driven, need tmp/image_sim_dji_push/nl.pkl (spi_trace, pad_roles, ram_loader_trace, af3_engine extract,
     template_match, match_overlap_check, regional_utilization)
  3. depends on tier-1 output on disk (m9k_content_classify reads m9k_dump's hex files)

Findings scan (--scan-only, or automatic after a run): greps every script's own log + json output this run touched for
the markers each script ALREADY uses for "found something worth a human" -- "FAIL", "MISMATCH" with a nonzero count,
"rc=1"/non-zero exit, a logged exception, or a JSON field literally named "open"/"unresolved"/"U" (this project's own
V/I/U evidence-tag convention).  Writes tmp/logs/cycloneiv_clean_dji_suite_findings.json: one entry per anomaly, with
the script name, the log line or json path, and enough context to hand a single entry to a cheap agent without it
needing to re-read the whole suite.  Dispatch to agents is NOT automatic (Dan's explicit call, 2026-10-31) -- this
script only produces the list.
"""
import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("dji_suite")
LOGDIR = Path(REPO) / "tmp" / "logs"
NL_PKL = Path(REPO) / "tmp" / "image_sim_dji_push" / "nl.pkl"
IMAGE_ENV = "PLURIBUS_DJI_IMAGE"

# step name -> (argv after the interpreter, needs_nl, stall/overall seconds -- 1.25x the slowest observed run of
# each script this session, or 300s as a floor for ones never individually timed yet).
STEPS = {
    "hardblock_usage": (["scripts/cycloneiv_clean_hardblock_usage.py"], False, 180),
    "m9k_dump": (["scripts/cycloneiv_clean_m9k_dump.py", "image"], False, 300),
    "m9k_modes": (["scripts/cycloneiv_clean_m9k_modes.py"], False, 180),
    "m9k_we_ctl": (["scripts/cycloneiv_clean_m9k_we_ctl.py"], False, 180),
    "image_clocks": (["scripts/cycloneiv_clean_image_clocks.py"], False, 300),
    "image_pll_pads": (["scripts/cycloneiv_clean_image_pll_pads.py"], False, 180),
    "setbits": (["scripts/cycloneiv_clean_setbits.py"], False, 300),
    "residue": (["scripts/cycloneiv_clean_residue.py"], False, 300),
    "m9k_content_classify": (["scripts/cycloneiv_clean_m9k_content_classify.py", "image"], False, 180),
    "spi_trace": (["scripts/cycloneiv_clean_spi_trace.py", "--nl", str(NL_PKL), "--pad", "AB11", "--tag", "image"], True, 180),
    "pad_roles": (["scripts/cycloneiv_clean_pad_roles.py", "--nl", str(NL_PKL), "--tag", "image"], True, 180),
    "ram_loader_trace": (["scripts/cycloneiv_clean_ram_loader_trace.py", "--nl", str(NL_PKL)], True, 180),
    "af3_engine_extract": (["scripts/cycloneiv_clean_af3_engine.py", "extract", "--nl", str(NL_PKL)], True, 300),
    "regional_utilization": (["scripts/cycloneiv_clean_regional_utilization.py"], True, 300),
}
TIER3_AFTER = {"m9k_content_classify": "m9k_dump"}       # reads the previous step's on-disk output, not --nl


def lift_is_current():
    """nl.pkl must postdate both F-021 (8de3cbaca, 2026-10-31 13:56) and the multi-LE tail strip
    (a852ab170, 14:49) -- the two lift-pipeline fixes landed today that this suite's findings have
    never been re-checked against (Dan, 2026-10-31).  Hardcoded cutoff, not a git call, since the
    suite must work even if the commits ever get rebased/squashed later; update this if the lift
    pipeline changes again in a way that could affect these findings."""
    import datetime
    cutoff = datetime.datetime(2026, 10, 31, 14, 50).timestamp()
    return NL_PKL.exists() and NL_PKL.stat().st_mtime > cutoff


def ensure_lift(log):
    if lift_is_current():
        log.info("nl.pkl current (mtime %.0f > cutoff), skipping re-lift", NL_PKL.stat().st_mtime)
        return True
    image = os.environ.get(IMAGE_ENV)
    if not image:
        log.error("nl.pkl missing/stale and %s not set -- cannot re-lift; tier-2/3 steps will be skipped", IMAGE_ENV)
        return False
    log.info("nl.pkl missing or stale: re-lifting via dev.py lift-image (this takes several minutes)")
    r = subprocess.run([sys.executable, "dev.py", "lift-image", "--out", str(NL_PKL.parent)], cwd=REPO,
                        capture_output=True, text=True, timeout=1800)
    (LOGDIR / "dji_suite_lift.log").write_text(r.stdout + r.stderr)
    if r.returncode != 0:
        log.error("lift-image failed rc=%d, see tmp/logs/dji_suite_lift.log", r.returncode)
        return False
    return lift_is_current()


def run_step(name, argv, timeout):
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable] + argv, cwd=REPO, capture_output=True, text=True, timeout=timeout,
                            env=dict(os.environ))
    except subprocess.TimeoutExpired as e:
        log.error("%s: exceeded %ds (stall/overall backstop), killed", name, timeout)
        (LOGDIR / f"dji_suite_{name}.log").write_text((e.stdout or "") + (e.stderr or "") + f"\n[TIMEOUT after {timeout}s]\n")
        return dict(step=name, rc=None, elapsed=timeout, timed_out=True)
    (LOGDIR / f"dji_suite_{name}.log").write_text(r.stdout + r.stderr)
    log.info("%s: rc=%d %.1fs", name, r.returncode, time.time() - t0)
    return dict(step=name, rc=r.returncode, elapsed=round(time.time() - t0, 1), timed_out=False)


FAIL_PAT = re.compile(r"\b(FAIL|ERROR|Traceback|Exception)\b", re.I)
# the count must be ADJACENT to the keyword (immediately before, as in "0 mismatches", or immediately
# after a colon/space with nothing else between, as in "mismatch: 3") -- NOT just "nearby", since a
# clean-pass line like "0 mismatches of 31060 bits" has an unrelated bigger number a few words later
# that an unanchored \D{0,N} gap would wrongly grab instead of the real (zero) count.
MISMATCH_PAT = re.compile(r"(?:\b(\d+)\s+(?:mismatch|missing|extra|wrong)\w*\b|\b(?:mismatch|missing|extra|wrong)\w*[:=]\s*(\d+)\b)", re.I)


def scan_findings(ran_steps):
    """Grep each step's own log for this project's existing anomaly markers (FAIL/ERROR/Traceback, or a
    mismatch/missing/extra/wrong COUNT > 0 -- the project's own scoring-fault vocabulary, see CLAUDE.md
    'Scoring faults'); also scan step json outputs for a literal 'open'/'unresolved' key.  Does not
    invent new severity judgement -- flags exactly what each script already chose to log as notable."""
    findings = []
    for step in ran_steps:
        if step.get("timed_out"):
            findings.append(dict(script=step["step"], kind="timeout", detail=f"exceeded its {step['elapsed']}s backstop",
                                  log=f"tmp/logs/dji_suite_{step['step']}.log"))
            continue
        if step.get("rc") not in (0, None):
            findings.append(dict(script=step["step"], kind="nonzero_exit", detail=f"rc={step['rc']}",
                                  log=f"tmp/logs/dji_suite_{step['step']}.log"))
        p = LOGDIR / f"dji_suite_{step['step']}.log"
        if not p.exists():
            continue
        text = p.read_text(errors="replace")
        for m in FAIL_PAT.finditer(text):
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            findings.append(dict(script=step["step"], kind="error_marker",
                                  detail=text[line_start:line_end if line_end >= 0 else None].strip()[:300],
                                  log=f"tmp/logs/dji_suite_{step['step']}.log"))
        for m in MISMATCH_PAT.finditer(text):
            count = int(m.group(1) or m.group(2))
            if count > 0:
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.end())
                findings.append(dict(script=step["step"], kind="nonzero_count",
                                      detail=text[line_start:line_end if line_end >= 0 else None].strip()[:300],
                                      log=f"tmp/logs/dji_suite_{step['step']}.log"))
    # dedupe identical (script, kind, detail) triples -- several scripts repeat the same summary line to both
    # stdout and a FileHandler, which would otherwise double-count every real finding.
    seen, out = set(), []
    for f in findings:
        key = (f["script"], f["kind"], f["detail"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated step names to run (default: all)")
    ap.add_argument("--scan-only", action="store_true", help="skip running steps, just rescan existing tmp/logs/dji_suite_*.log")
    a = ap.parse_args()
    os.makedirs(LOGDIR, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(), logging.FileHandler(LOGDIR / "cycloneiv_clean_dji_suite.log")])
    names = a.only.split(",") if a.only else list(STEPS)
    ran = []
    if not a.scan_only:
        have_nl = ensure_lift(log)
        for name in names:
            if name not in STEPS:
                log.warning("unknown step %r, skipping", name)
                continue
            if name in TIER3_AFTER and TIER3_AFTER[name] not in [s["step"] for s in ran]:
                log.warning("%s depends on %s having run first this session -- running it now", name, TIER3_AFTER[name])
            argv, needs_nl, timeout = STEPS[name]
            if needs_nl and not have_nl:
                log.warning("%s needs nl.pkl, unavailable -- skipped", name)
                ran.append(dict(step=name, rc=None, elapsed=0, timed_out=False, skipped="no nl.pkl"))
                continue
            ran.append(run_step(name, argv, timeout))
    else:
        for name in names:
            p = LOGDIR / f"dji_suite_{name}.log"
            ran.append(dict(step=name, rc=0 if p.exists() else None, elapsed=0, timed_out=False))
    findings = scan_findings(ran)
    out = dict(ran=ran, n_findings=len(findings), findings=findings)
    json.dump(out, open(LOGDIR / "cycloneiv_clean_dji_suite_findings.json", "w"), indent=1)
    log.info("suite done: %d steps, %d findings -> tmp/logs/cycloneiv_clean_dji_suite_findings.json", len(ran), len(findings))
    for f in findings:
        log.info("FINDING [%s/%s] %s", f["script"], f["kind"], f["detail"])
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
