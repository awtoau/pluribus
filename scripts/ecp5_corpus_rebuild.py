#!/usr/bin/env python3
#
# One entry point that rebuilds the ECP5 corpus from nothing.
# SPDX-License-Identifier: BSD-3-Clause

"""
Fetches, carves, tests and reports the ECP5 bitstream corpus in one command.

The corpus is 220-plus third-party bitstreams used to test the ECP5 lifter
against designs nobody here built. **The binaries are not in this repository**
-- most are unlicensed build artefacts published by hobby projects, so they are
gitignored and only `corpus/manifest.json` is committed. That makes the corpus
reproducible without redistributing anyone's firmware, but it also means a fresh
checkout has a manifest and no data.

This script closes that gap. It drives the existing tools in order rather than
reimplementing them:

    ecp5_corpus_fetch.py    download every manifest entry, verify by SHA-256
    ecp5_carve.py           extract bitstreams embedded in firmware packages
    ecp5_corpus_test.py     decode, compare against ecpunpack, lift
    ecp5_corpus_report.py   the results table

Each stage is skippable, so a partial rebuild does not start over.

    ./scripts/ecp5_corpus_rebuild.py                 # everything
    ./scripts/ecp5_corpus_rebuild.py --verify-only   # check what is on disk
    ./scripts/ecp5_corpus_rebuild.py --skip-fetch    # test what is already here
    ./scripts/ecp5_corpus_rebuild.py --workers 8

## What a rebuild cannot guarantee

Sources go away. Repositories are deleted, release assets are replaced, and
vendors withdraw firmware downloads. A rebuild reports how many entries it could
not retrieve rather than failing, because a corpus that is 90% present is still
useful and a hard failure would make it unusable.

SHA-256 mismatches are a different matter and are reported separately: a file
that downloaded but does not match the manifest means the upstream artefact
*changed*, which is worth knowing rather than silently accepting.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
MANIFEST = ROOT / "corpus" / "manifest.json"
LOG = ROOT / "tmp" / "logs" / "ecp5_corpus_rebuild.log"

# The stages, in order. Each is (name, script, args-builder).
STAGES = ("fetch", "carve", "test", "report")

_handle = None


def emit(text=""):
    """Print, and record with it."""
    global _handle
    if _handle is None:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        _handle = LOG.open("w")
    print(text, flush=True)
    _handle.write(str(text) + "\n")
    _handle.flush()


def run_stage(name, script, args):
    """Run one stage, reporting rather than raising.

    A stage that fails does not abort the rebuild: fetch commonly fails
    partially because upstream sources disappear, and the later stages are
    still worth running on what did arrive.
    """
    path = SCRIPTS / script
    if not path.exists():
        emit(f"  {name}: {script} not found -- skipped")
        return False

    emit(f"  {name}: {script} {' '.join(args)}")
    started = time.perf_counter()
    result = subprocess.run([sys.executable, str(path), *args],
                            cwd=ROOT, capture_output=True, text=True)
    elapsed = time.perf_counter() - started

    # Keep the stage's own output in the log; it is the detail a reader wants
    # when a rebuild comes up short.
    for line in (result.stdout or "").splitlines():
        _handle.write(f"      {line}\n")

    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()
        emit(f"      failed after {elapsed:.1f}s: "
             f"{tail[-1][:80] if tail else 'no output'}")
        return False

    emit(f"      done in {elapsed:.1f}s")
    return True


def corpus_state():
    """What is on disk against what the manifest expects."""
    if not MANIFEST.exists():
        return None

    payload = json.loads(MANIFEST.read_text())
    entries = payload if isinstance(payload, list) else payload.get("entries", [])

    present = missing = 0
    for entry in entries:
        local = entry.get("local")
        if local and (ROOT / local).exists():
            present += 1
        else:
            missing += 1

    return {"total": len(entries), "present": present, "missing": missing}


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=4,
                        help="parallelism for fetch and test")
    parser.add_argument("--verify-only", action="store_true",
                        help="report what is on disk and stop")
    for stage in STAGES:
        parser.add_argument(f"--skip-{stage}", action="store_true",
                            help=f"do not run the {stage} stage")
    args = parser.parse_args()

    LOG.parent.mkdir(parents=True, exist_ok=True)
    emit("ECP5 corpus rebuild")
    emit()

    state = corpus_state()
    if state is None:
        emit(f"no manifest at {MANIFEST.relative_to(ROOT)}")
        emit("Nothing to rebuild from -- the manifest is what makes the corpus")
        emit("reproducible, and it is committed, so this should not happen in a")
        emit("clean checkout.")
        return 1

    emit(f"manifest: {state['total']} entries, "
         f"{state['present']} on disk, {state['missing']} missing")
    emit()

    if args.verify_only:
        emit("verifying checksums of what is present")
        run_stage("verify", "ecp5_corpus_fetch.py", ["--verify"])
        return 0

    ok = True

    if not args.skip_fetch:
        # --verify after fetching, so a changed upstream artefact is reported
        # rather than quietly entering the corpus.
        ok &= run_stage("fetch", "ecp5_corpus_fetch.py",
                        ["--workers", str(args.workers)])
        run_stage("verify", "ecp5_corpus_fetch.py", ["--verify"])

    if not args.skip_carve:
        # Firmware packages contain bitstreams rather than being them; carving
        # finds a bitstream preamble inside a larger file.
        #
        # Worth widening: pluribus has lifters for ECP5, MachXO2, Gowin and
        # Anlogic, but the carver only recognises the ECP5 preamble
        # (ff ff bd b3). Any Gowin or Anlogic bitstream inside a firmware blob
        # is currently walked straight past. Since the harness can already
        # decode them, every FPGA bitstream found anywhere is a candidate --
        # not just the ECP5 ones.
        ok &= run_stage("carve", "ecp5_carve.py",
                        ["--out", "corpus/carved"])

    if not args.skip_test:
        ok &= run_stage("test", "ecp5_corpus_test.py",
                        ["--manifest", "corpus/manifest.json",
                         "--workers", str(args.workers),
                         "--resume",
                         "--out", "tmp/corpus_results.json"])

    if not args.skip_report:
        ok &= run_stage("report", "ecp5_corpus_report.py",
                        ["--results", "tmp/corpus_results.json",
                         "--out", "docs/ecp5/corpus-results.md"])

    final = corpus_state()
    emit()
    emit(f"corpus: {final['present']} of {final['total']} present")
    if final["missing"]:
        emit(f"{final['missing']} entries could not be retrieved. Sources do go")
        emit("away -- repositories are deleted, release assets replaced. A")
        emit("partial corpus is still useful; the report says which are absent.")
    emit(f"log: {LOG}")

    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
