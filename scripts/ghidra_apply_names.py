#!/usr/bin/env python3
"""Ghidra workflow for the Quartus libs (#165, #168).  Docs: docs/ghidra-workflow.md.

  python3 scripts/ghidra_apply_names.py import [lib ...]        # create/extend the project (slow, once)
  python3 scripts/ghidra_apply_names.py apply                   # apply reference/ghidra/*.tsv (idempotent)
  python3 scripts/ghidra_apply_names.py decomp <lib> <pat|0xVADDR> ...   # -> vendor-analysis/altera/analysis/ghidra_out/
  python3 scripts/ghidra_apply_names.py strings <lib> <regex>   # string -> referencing functions
  python3 scripts/ghidra_apply_names.py batch <lib> <re:regex|0xVADDR|substr> ...   # one .c per function -> ghidra_out/cache/<lib>/ (skips existing)
  python3 scripts/ghidra_apply_names.py xrefs <lib> 0xVADDR ...  # references to an address (and +0x10) -> ghidra_out/<lib>_xrefs.tsv
  python3 scripts/ghidra_apply_names.py export                  # user-defined names -> tmp/ghidra/export.tsv
  python3 scripts/ghidra_apply_names.py check                   # validate TSV shape (no Ghidra needed)
  -- readability layer (docs/ghidra-workflow.md "Readable code") --
  python3 scripts/ghidra_apply_names.py gen-enums | gen-vtables  # regenerate enums.tsv / vtables.tsv from the vendor libs
  python3 scripts/ghidra_apply_names.py classes [lib ...]        # Ghidra RTTI class recovery (once per lib; marker in tmp/ghidra/)
  python3 scripts/ghidra_apply_names.py types                    # names + enums + structs + vtable structs + signatures.tsv
  python3 scripts/ghidra_apply_names.py rename-locals <lib> <selector> [limit]   # name locals/params from types and field accesses
  python3 scripts/ghidra_apply_names.py export-readable <lib> [selector] [limit] # rename + annotated pseudo-code per class
  python3 scripts/ghidra_apply_names.py emulate <lib> <0xVADDR> <maxSteps> <arg|A..B> ...   # P-code sweep of a pure table function
  python3 scripts/ghidra_apply_names.py snapshot <name>          # read-only copy; decomp/strings/find-xrefs/emulate use the newest one
  python3 scripts/ghidra_apply_names.py find-xrefs <lib> <target> ...            # references to symbol regex / vaddr
  python3 scripts/ghidra_apply_names.py class-tree <lib> ...     # RTTI class hierarchy -> analysis/readable/class_tree.tsv
  python3 scripts/ghidra_apply_names.py readable [lib ...]       # classes + types + export-readable for the key functions
Project override: $PLURIBUS_GHIDRA_PROJ (a copy lets two agents work without the project lock).

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
PROJ = os.environ.get("PLURIBUS_GHIDRA_PROJ") or os.path.join(REPO, "vendor-analysis", "altera", "ghidra-project")
PNAME = "quartus"
TSV = os.path.join(REPO, "reference", "ghidra")
SCRIPTS = os.path.join(REPO, "scripts", "ghidra")
OUT = os.path.join(REPO, "vendor-analysis", "altera", "analysis", "ghidra_out")
LOG = os.path.join(REPO, "tmp", "logs", "ghidra_apply_names.log")
LIBS = ["libcomp_asm", "libcomp_asm2", "libcomp_asmcc", "libcomp_asmgx", "libdb_asmdb", "libddb_dev",
        "libddb_dygr", "libddb_dstr", "libpgm_pgmio", "libpgm_npcf",
        "libcomp_asmio", "libcomp_asmram", "libcomp_asmmac", "libcomp_asmpll", "libdb_cdb_atom_stingray", "libddb_bcm2bits",
        "libdb_u2b_bcm", "libddb_dbcm", "libpgm_fbgen", "libpgm_pof", "libdb_cut", "libdb_cdb_atom_ygr"]
COLS = {"functions.tsv": 6, "globals.tsv": 7, "structs.tsv": 8, "notes.tsv": 5, "enums.tsv": 5, "vtables.tsv": 6,
        "signatures.tsv": 6}
SRC_COL = {"enums.tsv": 4, "vtables.tsv": 5, "signatures.tsv": 4}   # new files: source column index
READ_OUT = os.path.join(REPO, "vendor-analysis", "altera", "analysis", "readable")
ALL_LIBS = LIBS + ["libdb_pdb"]
KEY_SELECTOR = ("re:::(process_(atom|end_of_phase|begin_of_phase|beginning_of_phase)|operator<<|xfr_\\w+|set_bits|silent_set_bits|"
                "mux_select|resolve_io_index\\w*|write_block\\w*)$;re:^asm_convert_")


SNAPS = os.path.join(REPO, "vendor-analysis", "altera", "ghidra-project-copies")


def ro_proj():
    """Read-only commands (decomp/strings/find-xrefs/emulate) use $PLURIBUS_GHIDRA_RO_PROJ, else the newest snapshot, else PROJ."""
    env = os.environ.get("PLURIBUS_GHIDRA_RO_PROJ")
    if env:
        return env
    if os.path.isdir(SNAPS):
        d = sorted((os.path.getmtime(os.path.join(SNAPS, x)), os.path.join(SNAPS, x)) for x in os.listdir(SNAPS)
                   if os.path.exists(os.path.join(SNAPS, x, PNAME + ".gpr")))
        if d:
            return d[-1][1]
    return PROJ


def snapshot(name):
    import shutil
    dst = os.path.join(SNAPS, name)
    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(SNAPS, exist_ok=True)
    shutil.copytree(PROJ, dst, ignore=shutil.ignore_patterns("*.lock*", "*.lock"))
    print(dst)
    return 0


def run(args, label, stall_s=120, overall_s=1800, proj=None):
    """Ghidra headless under the stall guard: kill when tree CPU does not advance for stall_s (JVM idle = hung);
    overall_s = backstop (import of 10 libs measured ~25 min cold; per-lib import / process runs are minutes)."""
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log = logging.getLogger("ghidra_apply_names")
    if not log.handlers:
        log.addHandler(logging.FileHandler(LOG))
        log.addHandler(logging.StreamHandler(sys.stdout))
        log.setLevel(logging.INFO)
    env = dict(os.environ, GHIDRA_MAXMEM=os.environ.get("GHIDRA_MAXMEM", "12G"))
    cmd = ["analyzeHeadless", proj or PROJ, PNAME] + args
    r = heavy_guard.run_stall_guarded(cmd, label, log, stall_s=stall_s, overall_s=overall_s, env=env)
    with open(LOG, "a") as lg:
        lg.write(f"== {label}: {' '.join(cmd)}\n{r.stdout}{r.stderr}")
    return r.returncode


def check():
    bad = 0
    for f, n in COLS.items():
        p = os.path.join(TSV, f)
        if not os.path.exists(p):
            continue
        for i, line in enumerate(open(p), 1):
            if not line.strip() or line.startswith("#"):
                continue
            c = line.rstrip("\n").split("\t")
            if len(c) < n:
                print(f"{f}:{i}: {len(c)} cols < {n}")
                bad += 1
            elif f in SRC_COL and not c[SRC_COL[f]].strip():
                print(f"{f}:{i}: empty source column")
                bad += 1
            elif f != "notes.tsv" and f not in SRC_COL and not c[-1 if f != "structs.tsv" else 7].strip():
                print(f"{f}:{i}: empty source column")
                bad += 1
            for bannedtxt in ("/mnt/", "/home/"):
                if bannedtxt in line:
                    print(f"{f}:{i}: private path")
                    bad += 1
    print("TSV ok" if not bad else f"{bad} problems")
    return bad


def main_with(argv):
    old = sys.argv
    sys.argv = [old[0]] + argv
    try:
        return main()
    finally:
        sys.argv = old


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
    if cmd in ("apply", "types"):
        if check():
            return 1
        rep = os.path.join(REPO, "tmp", "ghidra", "apply_report.tsv")
        os.makedirs(os.path.dirname(rep), exist_ok=True)
        open(rep, "w").close()
        scr = ["-postScript", "ApplyNames.java", TSV, rep]
        if cmd == "types":
            scr += ["-postScript", "TypesPass.java", TSV, rep]
        rc = run(["-process", "-noanalysis", "-scriptPath", SCRIPTS] + scr, cmd)
        print(open(rep).read())
        return rc
    if cmd in ("gen-enums", "gen-vtables"):
        import subprocess
        return subprocess.run([sys.executable, os.path.join(HERE, "ghidra_" + cmd.replace("-", "_") + ".py")]).returncode
    if cmd == "snapshot":   # snapshot <name>: cp of the project (no lock files) -> ghidra-project-copies/<name>; read-only commands use the newest
        return snapshot(rest[0] if rest else "latest")
    if cmd == "class-tree":
        import subprocess
        return subprocess.run([sys.executable, os.path.join(HERE, "ghidra_class_tree.py")] + rest).returncode
    if cmd == "classes":
        rc = 0
        mark = os.path.join(REPO, "tmp", "ghidra")
        os.makedirs(mark, exist_ok=True)
        for l in rest or ALL_LIBS:
            m = os.path.join(mark, "classes_done_" + l)
            if os.path.exists(m):
                print(l, "classes already recovered (delete", m, "to redo)")
                continue
            r = run(["-process", l + ".so", "-noanalysis", "-postScript", "RecoverClassesFromRTTIScript.java"], "classes-" + l, 120, 3600)
            if r == 0:
                open(m, "w").close()
            rc = rc or r
        return rc
    if cmd in ("rename-locals", "export-readable"):
        lib = rest[0]
        sel = rest[1] if len(rest) > 1 else KEY_SELECTOR
        lim = rest[2] if len(rest) > 2 else "1000000"
        os.makedirs(READ_OUT, exist_ok=True)
        return run(["-process", lib + ".so", "-noanalysis", "-scriptPath", SCRIPTS, "-postScript", "ReadablePass.java", READ_OUT,
                    "rename" if cmd == "rename-locals" else "both", sel, lim], cmd + "-" + lib, 120, 3600)
    if cmd == "emulate":   # emulate <lib> <vaddr> <maxSteps> <argSpec> ...   (spec N | A..B) -> readable/emulate_<lib>_<vaddr>.tsv
        os.makedirs(READ_OUT, exist_ok=True)
        out = os.path.join(READ_OUT, f"emulate_{rest[0]}_{rest[1]}.tsv")
        open(out, "w").close()
        rc = run(["-process", rest[0] + ".so", "-noanalysis", "-readOnly", "-scriptPath", SCRIPTS, "-postScript", "Emulate.java", out]
                 + rest[1:], "emulate", 120, 1800, proj=ro_proj())
        print(out)
        return rc
    if cmd == "export-gdt":   # export-gdt <lib> -> readable/pluribus_<lib>.gdt (GUI Data Type Archive of /pluribus types)
        os.makedirs(READ_OUT, exist_ok=True)
        out = os.path.join(READ_OUT, f"pluribus_{rest[0]}.gdt")
        return run(["-process", rest[0] + ".so", "-noanalysis", "-readOnly", "-scriptPath", SCRIPTS, "-postScript", "ExportGdt.java", out],
                   "export-gdt")
    if cmd == "find-xrefs":
        os.makedirs(READ_OUT, exist_ok=True)
        out = os.path.join(READ_OUT, "xrefs_" + rest[0] + ".tsv")
        open(out, "w").close()
        rc = run(["-process", rest[0] + ".so", "-noanalysis", "-readOnly", "-scriptPath", SCRIPTS, "-postScript", "FindXrefs.java", out]
                 + rest[1:], "find-xrefs", proj=ro_proj())
        print(out)
        return rc
    if cmd == "readable":
        for step in (["classes"] + rest, ["types"]):
            if main_with(step):
                return 1
        for l in rest or ALL_LIBS:
            if main_with(["export-readable", l]):
                return 1
        return 0
    if cmd == "decomp":
        os.makedirs(OUT, exist_ok=True)
        out = os.path.join(OUT, rest[0] + "_" + "_".join(x.replace(":", "") for x in rest[1:])[:60] + ".c")
        open(out, "w").close()
        rc = run(["-process", rest[0] + ".so", "-noanalysis", "-readOnly", "-scriptPath", SCRIPTS,
                  "-postScript", "DecompNames.java", out] + rest[1:], "decomp", proj=ro_proj())
        print(out)
        return rc
    if cmd == "strings":
        os.makedirs(OUT, exist_ok=True)
        out = os.path.join(OUT, rest[0] + "_strings.tsv")
        open(out, "w").close()
        rc = run(["-process", rest[0] + ".so", "-noanalysis", "-readOnly", "-scriptPath", SCRIPTS,
                  "-postScript", "StringXrefs.java", out, rest[1]], "strings", proj=ro_proj())
        print(out)
        return rc
    if cmd == "batch":
        out = os.path.join(OUT, "cache", rest[0])
        os.makedirs(out, exist_ok=True)
        rc = run(["-process", rest[0] + ".so", "-noanalysis", "-readOnly", "-scriptPath", SCRIPTS,
                  "-postScript", "DecompBatch.java", out] + rest[1:], "batch", 120, 3600)
        print(out)
        return rc
    if cmd == "xrefs":
        os.makedirs(OUT, exist_ok=True)
        out = os.path.join(OUT, rest[0] + "_xrefs.tsv")
        open(out, "w").close()
        rc = run(["-process", rest[0] + ".so", "-noanalysis", "-readOnly", "-scriptPath", SCRIPTS,
                  "-postScript", "AddrXrefs.java", out] + rest[1:], "xrefs")
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
