#!/usr/bin/env python3
"""Inventory of Quartus linux64 libs/binaries; classify relevance to Cyclone IV GX (#169).

  python3 scripts/ghidra_inventory.py            # -> reference/ghidra/libs.tsv, log tmp/logs/ghidra_inventory.log
Relevance = name pattern OR symbol hits (dynsym defined+undefined) on stingray/cycloneiv/ygr/dygr/asmdb/cut/atm/pgm/pdb/dstr/dev.
"""
import concurrent.futures as cf
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import toolchain  # noqa: E402

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(HERE)
QROOT = os.environ.get("PLURIBUS_QUARTUS_DIR") or os.path.dirname(toolchain.quartus_bin())
OUT = os.path.join(REPO, "reference", "ghidra", "libs.tsv")
BINS = ["quartus_asm", "quartus_cpf", "quartus_fit", "quartus_cdb", "quartus_map", "quartus_pow", "quartus_sta", "quartus_pgm", "quartus_sh"]
NAME_RE = re.compile(r"(asm|cdb_atom|ddb|db_|dstr|dygr|ygr|stingray|cycloneiv|pgm_|pdb|cut|_cv|cyclone|u2b|rcf|fbgen|pof|npcf|dev)", re.I)
SYM_RE = re.compile(r"(stingray|cycloneiv|CYCLONEIV|ygr|YGR|dygr|asmdb|ASMDB|\bcut_|CUT_|ATM_|_atm|PGM_|pdb|PDB_|dstr|DSTR|DEV_)")
STRICT = re.compile(r"(stingray|cycloneiv|ygr|dygr|asmdb|ASM_|CUT_|cut_)")
SKIP_NAME = re.compile(r"(^libQt|^libicu|^libstdc|^libgcc|^libc\.|^libm\.|^libz|^libssl|^libcrypto|^libX|^libxcb|^libgtk|^libglib|^libpng|^libfreetype|^libqt|^libcurl|^libxml|^libsys_)")


CORE = re.compile(r"^(libcomp_asm|libdb_asmdb|libdb_cdb_atom(_ygr|_stingray|_generic|_cuda|_dynamic|_syn)?\.so|libdb_cut|libddb_|libdb_u2b|libdb_rcf|"
                  r"libpgm_|libdb_pdb|libatm_(astr|aygr|autil)|libcbx_stingray|libperiph_hssi|libfitter_fhssi|libfitter_fygr|libperiph_c(io|clk|pll)|libpower_patfam_ygr|libdb_cdb\.so|libdb_rbc\.so|quartus_(asm|cpf|fit|cdb|map|pow)$)")
NOT_CORE = re.compile(r"aes")   # key/decrypt libs: out of scope (#165)


def tier(name, hits, rel):
    if CORE.match(name) and not NOT_CORE.search(name) and (rel or hits > 0 or name.startswith("quartus_")):
        return "core"
    return "adjacent" if rel else "no"


def symbols(path):
    r = subprocess.run(["nm", "-D", "-C", path], capture_output=True, text=True)
    return r.stdout.splitlines() if r.returncode == 0 else []


def classify(path):
    name = os.path.basename(path)
    syms = symbols(path)
    total = len(syms)
    hits = sum(1 for s in syms if SYM_RE.search(s))
    strict = sum(1 for s in syms if STRICT.search(s))
    name_hit = bool(NAME_RE.search(name)) and not SKIP_NAME.search(name)
    # relevant: strict symbol hits, or name hit with some symbol hits
    rel = strict >= 3 or (name_hit and hits >= 3)
    return name, total, hits, strict, name_hit, rel, os.path.getsize(path)


def main():
    d = os.path.join(QROOT, "linux64")
    files = [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".so") and os.path.isfile(os.path.join(d, f))]
    files += [os.path.join(d, b) for b in BINS if os.path.isfile(os.path.join(d, b))]
    with cf.ThreadPoolExecutor(8) as ex:
        rows = list(ex.map(classify, files))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write("# lib\tdynsyms\tsym_hits\tstrict_hits\tname_hit\trelevant\tsize\ttier\tsource\n")
        for r in rows:
            f.write("\t".join(str(x) for x in (r[0], r[1], r[2], r[3], int(r[4]), int(r[5]), r[6], tier(r[0], r[2], r[5]), "scripts/ghidra_inventory.py")) + "\n")
    rel = [r for r in rows if r[5]]
    print(f"{len(rows)} files, {len(rel)} relevant, {sum(1 for r in rows if tier(r[0], r[2], r[5]) == 'core')} core -> {OUT}")
    for r in rel:
        print(f"  {r[0]:45s} syms={r[1]:6d} hits={r[2]:5d} strict={r[3]:5d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
