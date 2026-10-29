#!/usr/bin/env python3
"""Ghidra workflow for the Quartus libs (#165, #168).  Docs: docs/ghidra-workflow.md.

  python3 scripts/ghidra_apply_names.py import [lib ...]        # create/extend the project (slow, once)
  python3 scripts/ghidra_apply_names.py apply                   # apply reference/ghidra/*.tsv (idempotent)
  python3 scripts/ghidra_apply_names.py decomp <lib> <pat|0xVADDR> ...   # -> vendor-analysis/altera/analysis/ghidra_out/
  python3 scripts/ghidra_apply_names.py strings <lib> <regex>   # string -> referencing functions
  python3 scripts/ghidra_apply_names.py export                  # user-defined names -> tmp/ghidra/export.tsv
  python3 scripts/ghidra_apply_names.py check                   # validate TSV shape (no Ghidra needed)

Project: vendor-analysis/altera/ghidra-project/quartus (gitignored).  Log: tmp/logs/ghidra_apply_names.log.
Quartus root: $PLURIBUS_QUARTUS_DIR or the default below.  One analyzeHeadless at a time (project lock).
"""
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import heavy_guard  # noqa: E402

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(HERE)
import toolchain  # noqa: E402
QROOT = os.environ.get("PLURIBUS_QUARTUS_DIR") or os.path.dirname(toolchain.quartus_bin())
PROJ = os.path.join(REPO, "vendor-analysis", "altera", "ghidra-project")
PNAME = "quartus"
TSV = os.path.join(REPO, "reference", "ghidra")
SCRIPTS = os.path.join(REPO, "scripts", "ghidra")
OUT = os.path.join(REPO, "vendor-analysis", "altera", "analysis", "ghidra_out")
LOG = os.path.join(REPO, "tmp", "logs", "ghidra_apply_names.log")
LIBS = ["libcomp_asm", "libcomp_asm2", "libcomp_asmcc", "libcomp_asmgx", "libdb_asmdb", "libddb_dev",
        "libddb_dygr", "libddb_dstr", "libpgm_pgmio", "libpgm_npcf"]
COLS = {"functions.tsv": 6, "globals.tsv": 7, "structs.tsv": 8, "notes.tsv": 5}


def run(args, label, stall_s=120, overall_s=1800):
    """Ghidra headless under the stall guard: kill when tree CPU does not advance for stall_s (JVM idle = hung);
    overall_s = backstop (import of 10 libs measured ~25 min cold; per-lib import / process runs are minutes)."""
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log = logging.getLogger("ghidra_apply_names")
    if not log.handlers:
        log.addHandler(logging.FileHandler(LOG))
        log.addHandler(logging.StreamHandler(sys.stdout))
        log.setLevel(logging.INFO)
    env = dict(os.environ, GHIDRA_MAXMEM=os.environ.get("GHIDRA_MAXMEM", "12G"))
    cmd = ["analyzeHeadless", PROJ, PNAME] + args
    r = heavy_guard.run_stall_guarded(cmd, label, log, stall_s=stall_s, overall_s=overall_s, env=env)
    with open(LOG, "a") as lg:
        lg.write(f"== {label}: {' '.join(cmd)}\n{r.stdout}{r.stderr}")
    return r.returncode


def check():
    bad = 0
    for f, n in COLS.items():
        p = os.path.join(TSV, f)
        for i, line in enumerate(open(p), 1):
            if not line.strip() or line.startswith("#"):
                continue
            c = line.rstrip("\n").split("\t")
            if len(c) < n:
                print(f"{f}:{i}: {len(c)} cols < {n}")
                bad += 1
            elif f != "notes.tsv" and not c[-1 if f != "structs.tsv" else 7].strip():
                print(f"{f}:{i}: empty source column")
                bad += 1
            for bannedtxt in ("/mnt/", "/home/"):
                if bannedtxt in line:
                    print(f"{f}:{i}: private path")
                    bad += 1
    print("TSV ok" if not bad else f"{bad} problems")
    return bad


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 2
    cmd, rest = a[0], a[1:]
    if cmd == "check":
        return 1 if check() else 0
    if cmd == "import":
        libs = rest or LIBS
        os.makedirs(PROJ, exist_ok=True)
        files = [os.path.join(QROOT, "linux64", l + ".so") for l in libs]
        return run(["-import"] + files + ["-analysisTimeoutPerFile", "1200"], "import", 300, 5400)
    if cmd == "apply":
        if check():
            return 1
        rep = os.path.join(REPO, "tmp", "ghidra", "apply_report.tsv")
        os.makedirs(os.path.dirname(rep), exist_ok=True)
        open(rep, "w").close()
        rc = run(["-process", "-noanalysis", "-scriptPath", SCRIPTS, "-postScript", "ApplyNames.java", TSV, rep], "apply")
        print(open(rep).read())
        return rc
    if cmd == "decomp":
        os.makedirs(OUT, exist_ok=True)
        out = os.path.join(OUT, rest[0] + "_" + "_".join(x.replace(":", "") for x in rest[1:])[:60] + ".c")
        open(out, "w").close()
        rc = run(["-process", rest[0] + ".so", "-noanalysis", "-readOnly", "-scriptPath", SCRIPTS,
                  "-postScript", "DecompNames.java", out] + rest[1:], "decomp")
        print(out)
        return rc
    if cmd == "strings":
        os.makedirs(OUT, exist_ok=True)
        out = os.path.join(OUT, rest[0] + "_strings.tsv")
        open(out, "w").close()
        rc = run(["-process", rest[0] + ".so", "-noanalysis", "-readOnly", "-scriptPath", SCRIPTS,
                  "-postScript", "StringXrefs.java", out, rest[1]], "strings")
        print(out)
        return rc
    if cmd == "export":
        out = os.path.join(REPO, "tmp", "ghidra", "export.tsv")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "w").close()
        rc = run(["-process", "-noanalysis", "-readOnly", "-scriptPath", SCRIPTS, "-postScript", "ExportNames.java", out], "export")
        print(out)
        return rc
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
