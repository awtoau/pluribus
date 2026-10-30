#!/usr/bin/env python3
"""Coverage table: libcomp_asm* ASM_* classes -> asmdb arch groups -> block type -> bits, with decoded status (#169).

  python3.15t scripts/cycloneiv_clean_asm_classes.py     # log tmp/logs/cycloneiv_clean_asm_classes.log, json tmp/cycloneiv_clean/asm_classes.json

- Classes = nm symbols `ASM_X::process_atom | process_end_of_phase | process_beginning_of_phase` in libcomp_asm / asm2 / asmgx / asmcc dumps
  (vendor-analysis/altera/analysis/nm_*.txt).  Class ASM_X is bound to the arch group type named X (class name == libdb_asmdb group name;
  source: docs/cycloneiv-clean-io.md, ASM_IO_USE_BUS_HOLD <-> IO_USE_BUS_HOLD enum 165; the match rate is the first output line).
- Bits per group name over every walk group of that type: calc = distinct offsets x instances (BLOCK_INFO list length),
  std / dumb / stlmap = distinct stored addresses by tag (CRAM 0, CFF 0xA, option 0x88, DPRIO 0x84, markers 0xC/0xF dropped).
- Status: pair (a pair build confirmed the field: options_table.json, io_decode FIELD_GROUPS, fields doc), placed (addresses known, no value
  map), none (class has no group of that name in the asmdb).
"""
import collections
import json
import logging
import os
import re
import sys

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import asmdb_walk as W, io_decode as ID, options as O  # noqa: E402
import cycloneiv_clean_dirt as D  # noqa: E402

AN = os.path.join(REPO, "vendor-analysis", "altera", "analysis")
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_asm_classes.log")
OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "asm_classes.json")
NMS = {"libcomp_asm": "nm_full_comp_asm.txt", "libcomp_asm2": "nm_full_comp_asm2.txt", "libcomp_asmgx": "nm_comp_asmgx.txt",
       "libcomp_asmcc": "nm_comp_asmcc.txt"}
HOOKS = ("process_atom", "process_end_of_phase", "process_beginning_of_phase")
# source: docs/cycloneiv-clean-fields.md "Field labels confirmed by pair diff" (LAB / M9K groups a pair build isolated)
FIELD_PAIR = {"LE_CLEAR_SELECT", "LAB_CLEAR_FAST_MUX", "LAB_CLR_INVERT_PAIR", "LE_REG_OUT_YGR", "LE_USE_SYNC_CLEAR", "LE_USE_SYNC_LOAD",
              "LAB_ENABLE_SYNC_SIGNALS", "LAB_CE_FAST_MUX", "LAB_ENABLE_CE", "LAB_INVERT", "LE_CLOCK_SELECT", "LAB_CLOCK_FAST_MUX",
              "LAB_SYNC_LOAD_FAST_MUX_MAG", "LE_LUT_FUNCTION", "RAM_REG_DATA_OUT", "RAM_REG_DATA_OUT_B", "RAM_SELECT_CLK_DATA_OUT",
              "RAM_SELECT_CLK_DATA_OUT_B", "RAM_CE_SELECT_OUTPUT", "RAM_NEW_DATA_MODE", "RAM_CONTENT"}
SPACE = {0x0: "cram", 0xA: "cff", 0x8: "opt_dprio", 0xC: "marker", 0xF: "marker"}


def classes():
    out = collections.OrderedDict()
    pat = re.compile(r"^[0-9a-f]+ [Tt] (ASM_\w+)::(%s)\(" % "|".join(HOOKS))
    for lib, f in NMS.items():
        for line in open(os.path.join(AN, f), errors="replace"):
            m = pat.match(line)
            if m:
                out.setdefault(m.group(1), {"libs": set(), "hooks": set()})
                out[m.group(1)]["libs"].add(lib)
                out[m.group(1)]["hooks"].add(m.group(2))
    return out


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    log = logging.getLogger("cls")
    log.setLevel(logging.INFO)
    log.addHandler(logging.FileHandler(LOG, "w"))
    log.addHandler(logging.StreamHandler(sys.stdout))
    w = W.Walk()
    nm = D.enum_tables()
    gname, bname = nm["arch_group_type"], nm["block_type"]
    inst = {b["btype"]: len(b["lists"].get(1, [])) for b in w.block_infos()}
    byname = collections.defaultdict(list)
    for g in w.groups():
        byname[gname.get(g["type"], str(g["type"]))].append(g)

    def gbits(g):
        if g["cls"] == 7:
            return list(g["bits"])
        return [b for p in g["paths"] for r in p if r for b in w.mux(r)["bits"]]

    decoded_opts = {e["name"] for e in O.entries() if e["klass"] == "group"}
    decoded_io = {g for v in ID.FIELD_GROUPS.values() for g in v}
    cl = classes()
    bind = collections.defaultdict(set)                # class -> group names, from the factory switches (cycloneiv_clean_class_bind.py)
    for r in json.load(open(os.path.join(REPO, "lifters", "cycloneiv_clean", "class_groups_table.json"))):
        if r["group"]:
            bind[r["cls"]].add(r["group"])
    log.info("classes with a hook: %d", len(cl))
    rows, matched = [], 0
    for c in sorted(cl):
        base = c[4:]
        names_ = sorted(set(bind.get(c, ())) | ({base} if base in byname else set()))
        gs = [g for n_ in names_ for g in byname.get(n_, [])]
        if gs:
            matched += 1
        sp = collections.Counter()
        blocks = set()
        for name, glist in ((base, gs),):
            seen = set()
            for g in glist:
                blocks.add(bname.get(g["btype"], str(g["btype"])))
                offs = {b for b in gbits(g) if b < 0xC0000000}
                if g["cls"] == 5:
                    n = inst.get(g["btype"], 1)
                    for b in offs:
                        seen.add(("cram_rel", b))
                    sp["cram"] += len(offs) * n if g["btype"] in (18, 39, 41) else 0
                else:
                    for b in offs:
                        seen.add((SPACE.get(b >> 28, "other"), b))
            for k, _ in seen:
                if k != "cram_rel":
                    sp[k] += 1
        pair = any(n_ in FIELD_PAIR or n_ in decoded_opts or n_ in decoded_io for n_ in names_)
        status = "pair" if (gs and pair) else ("placed" if gs and sum(sp.values()) else ("grouped" if gs else "none"))
        rows.append(dict(cls=c, libs=sorted(cl[c]["libs"]), hooks=sorted(cl[c]["hooks"]), group=names_ if gs else None, bound=sorted(bind.get(c, ())),
                         blocks=sorted(blocks), bits=dict(sp), total_bits=sum(sp.values()), status=status))
    log.info("classes bound to an asmdb group (factory switch or name): %d of %d", matched, len(cl))
    st = collections.Counter(r["status"] for r in rows)
    log.info("status %s", dict(st))
    agg = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        for b in r["blocks"] or ["-"]:
            agg[b]["classes"] += 1
            agg[b]["bits"] += r["total_bits"]
            agg[b]["pair"] += r["status"] == "pair"
    for b, c in sorted(agg.items(), key=lambda kv: -kv[1]["bits"]):
        log.info("block %-26s classes %4d pair-confirmed %3d bits %d", b, c["classes"], c["pair"], c["bits"])
    for r in sorted(rows, key=lambda r: -r["total_bits"])[:60]:
        log.info("top %-48s %-8s %-22s %s", r["cls"], r["status"], ",".join(r["blocks"]), r["bits"])
    json.dump(rows, open(OUT, "w"), indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
