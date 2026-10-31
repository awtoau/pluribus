#!/usr/bin/env python3.15t
"""Image annotation table for the clean Cyclone IV pipeline (#165): named blocks over physical ids.

  cycloneiv_clean_annotate.py add --kind SCR --name N --claim C --tag V --evidence "log:...;ledger:M-019" --members ids.txt|a,b,c
  cycloneiv_clean_annotate.py list [--kind K] [--tag T]       check [--nl NL.pkl]      names [--out map.tsv]
  cycloneiv_clean_annotate.py coverage [--nl NL.pkl] [--no-record]       remove --block ID
  cycloneiv_clean_annotate.py seed-image [--nl NL.pkl] [--patterns P.json] [--clocks C.json]
DB: PLURIBUS_SQLITE_PATH (default databases/cycloneiv/gx150.db; schema.py owns the tables).  Table stays local; docs get counts only.
Block id = KIND + 3-digit counter; re-adding the same sorted member set (or the same kind+name) keeps the id.
Tags: V traced (a log/trace/ledger reference that exists), I inferred, H hypothesis, U unknown.  Physical ids are never renumbered.
Members file: one `physical_id[,alias]` per line.  Log: tmp/logs/cycloneiv_clean_annotate.log.
"""
import argparse
import collections
import datetime
import hashlib
import json
import logging
import os
import pickle
import re
import sys

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
os.environ.setdefault("PLURIBUS_SQLITE_PATH", os.path.join(REPO, "databases", "cycloneiv", "gx150.db"))

LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_annotate.log")
log = logging.getLogger("annotate")
KINDS = ("SCR", "CRC", "CNT", "FSM", "SPI", "MEM", "MAC", "PLL", "IO", "DAT", "CLK")   # CLK = clock domain (no logic members)
TAGS = ("V", "I", "H", "U")
EVIDENCE_KINDS = ("log", "trace", "ledger", "json", "script", "issue", "doc")
TRACE_KINDS = ("log", "trace", "ledger")        # a V claim needs one of these, existing
OBJ_KINDS = (("ff_", "ff"), ("lc_", "lut"), ("m9k_", "m9k"), ("mac_", "mac"), ("pll_", "pll"), ("pad_", "pad"), ("u_clkbuf", "clk"))
LEDGER = os.path.join(REPO, "reference", "rules.tsv")
DEFAULT_NL = os.path.join(REPO, "tmp", "dji_patterns", "image_nl.pkl")
ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def obj_kind(oid):
    for p, k in OBJ_KINDS:
        if oid.startswith(p):
            return k
    raise ValueError(f"unknown physical id form: {oid}")


def member_hash(ids):
    return hashlib.sha1("\n".join(sorted(ids)).encode()).hexdigest()


def read_members(spec):
    """'a,b,c' or a file of `id[,alias]` lines -> [(id, alias|None)]."""
    if os.path.isfile(spec):
        lines = [l.strip() for l in open(spec) if l.strip() and not l.startswith("#")]
        return [(l.split(",")[0].strip(), (l.split(",") + [""])[1].strip() or None) for l in lines]
    return [(x.strip(), None) for x in spec.split(",") if x.strip()]


# ---- evidence -------------------------------------------------------------------------------------------------------

def parse_evidence(ev):
    return [tuple(x.strip().split(":", 1)) if ":" in x else (x.strip(), "") for x in ev.split(";") if x.strip()]


def ledger_ids():
    if not os.path.exists(LEDGER):
        return set()
    return {l.split("\t", 1)[0] for l in open(LEDGER)}


def ref_problem(kind, ref, members):
    """None when the reference exists (and, for log / trace, mentions an FF member of the block), else the reason."""
    if kind not in EVIDENCE_KINDS:
        return f"unknown evidence kind '{kind}'"
    if not ref:
        return f"{kind}: empty reference"
    if kind == "ledger":
        return None if ref in ledger_ids() else f"ledger row {ref} not in reference/rules.tsv"
    if kind == "issue":
        return None if ref.isdigit() else f"issue ref '{ref}' is not a number"
    path = ref if os.path.isabs(ref) else os.path.join(REPO, ref)
    if not os.path.isfile(path):
        return f"{kind}: file {ref} does not exist"
    ffs = [m for m in members if m.startswith("ff_")]
    if kind in ("log", "trace") and ffs:
        text = open(path, errors="replace").read()
        if not any(re.search(r"(?<![A-Za-z0-9_])" + re.escape(f) + r"(?![A-Za-z0-9_])", text) for f in ffs):
            return f"{kind}: {ref} mentions none of the block's FFs"
    return None


def evidence_problems(tag, ev, members):
    refs = parse_evidence(ev)
    if not refs:
        return ["missing evidence"]
    out, good = [], []
    for k, r in refs:
        p = ref_problem(k, r, members)
        (out if p else good).append(p or k)
    if tag == "V" and not [k for k in good if k in TRACE_KINDS]:
        out.append("tag V without an existing log / trace / ledger reference")
    return out


# ---- DB -------------------------------------------------------------------------------------------------------------

def get_engine():
    import db
    import schema
    eng = db.engine()
    schema.init(eng)
    return eng


def block_rows(conn, image):
    import schema as S
    from sqlalchemy import select
    return list(conn.execute(select(S.annotations).where(S.annotations.c.image == image).order_by(S.annotations.c.block_id)).mappings())


def next_block_id(conn, image, kind):
    n = 0
    for r in block_rows(conn, image):
        if r["kind"] == kind:
            n = max(n, int(r["block_id"][len(kind):]))
    return f"{kind}{n + 1:03d}"


def add_block(eng, image, kind, name, claim, tag, evidence, members, date=None, block=None):
    """Upsert. members = [(id, alias|None)]. Same member hash, else same kind+name, else --block keeps the id. -> (block_id, 'new'|'same'|'updated')."""
    import schema as S
    from sqlalchemy import delete, insert, select, update
    if kind not in KINDS:
        raise ValueError(f"kind {kind} not in {KINDS}")
    if tag not in TAGS:
        raise ValueError(f"tag {tag} not in {TAGS}")
    if not evidence.strip():
        raise ValueError("evidence is required")
    if not members:
        raise ValueError("a block needs members")
    ids = [m for m, _ in members]
    h = member_hash(ids)
    a = S.annotations
    with eng.begin() as conn:
        rows = [r for r in block_rows(conn, image) if r["kind"] == kind]
        hit = next((r for r in rows if r["member_hash"] == h), None) or next((r for r in rows if r["name"] == name), None) \
            or next((r for r in rows if block and r["block_id"] == block), None)
        vals = dict(image=image, kind=kind, name=name, claim=claim, tag=tag, evidence=evidence,
                    date=date or datetime.date.today().isoformat(), member_hash=h, n_members=len(ids))
        if hit is None:
            bid = block or next_block_id(conn, image, kind)
            aid = conn.execute(insert(a).values(block_id=bid, **vals)).inserted_primary_key[0]
            action = "new"
        else:
            bid, aid = hit["block_id"], hit["id"]
            same = hit["member_hash"] == h and all(hit[k] == vals[k] for k in ("name", "claim", "tag", "evidence"))
            conn.execute(update(a).where(a.c.id == aid).values(**vals))
            conn.execute(delete(S.annotation_members).where(S.annotation_members.c.annotation_id == aid))
            action = "same" if same else "updated"
        conn.execute(insert(S.annotation_members), [dict(annotation_id=aid, image=image, obj_kind=obj_kind(i), obj_id=i, alias=al)
                                                    for i, al in members])
    log.info("%s %s %s %s tag=%s members=%d", action, bid, kind, name, tag, len(ids))
    return bid, action


def remove_block(eng, image, block_id):
    import schema as S
    from sqlalchemy import delete
    with eng.begin() as conn:
        aid = [r["id"] for r in block_rows(conn, image) if r["block_id"] == block_id]
        for i in aid:
            conn.execute(delete(S.annotation_members).where(S.annotation_members.c.annotation_id == i))
            conn.execute(delete(S.annotations).where(S.annotations.c.id == i))
    return len(aid)


def load_all(eng, image):
    """-> (blocks, members_by_block_id): rows as dicts."""
    import schema as S
    from sqlalchemy import select
    with eng.connect() as conn:
        blocks = [dict(r) for r in block_rows(conn, image)]
        by_id = {b["id"]: b["block_id"] for b in blocks}
        mem = collections.defaultdict(list)
        for r in conn.execute(select(S.annotation_members).where(S.annotation_members.c.image == image).order_by(S.annotation_members.c.id)).mappings():
            mem[by_id[r["annotation_id"]]].append(dict(r))
    return blocks, mem


# ---- check ----------------------------------------------------------------------------------------------------------

def check(eng, image, totals=None):
    """-> list of problem strings."""
    blocks, mem = load_all(eng, image)
    bad = []
    owner = {}
    alias_of = collections.defaultdict(set)
    for b in blocks:
        bid, ms = b["block_id"], mem[b["block_id"]]
        ids = [m["obj_id"] for m in ms]
        if b["kind"] not in KINDS or not re.fullmatch(re.escape(b["kind"]) + r"\d{3,}", bid):
            bad.append(f"{bid}: block id does not match kind {b['kind']}")
        if b["tag"] not in TAGS:
            bad.append(f"{bid}: tag {b['tag']} not in {TAGS}")
        if not ms:
            bad.append(f"{bid}: no members")
        if b["member_hash"] != member_hash(ids) or b["n_members"] != len(ids):
            bad.append(f"{bid}: member hash / count does not match its members")
        for p in evidence_problems(b["tag"], b["evidence"] or "", ids):
            bad.append(f"{bid}: {p}")
        if not (b["claim"] or "").strip() or not (b["name"] or "").strip():
            bad.append(f"{bid}: empty name or claim")
        for m in ms:
            o = m["obj_id"]
            if o in owner:
                bad.append(f"duplicate physical id {o}: {owner[o]} and {bid}")
            owner.setdefault(o, bid)
            if totals is not None and o not in totals["all"]:
                bad.append(f"{bid}: {o} is not in the netlist")
            if m["alias"]:
                if not ALIAS_RE.match(m["alias"]):
                    bad.append(f"{bid}: alias '{m['alias']}' is not an identifier")
                alias_of[m["alias"]].add(o)
    physical = set(owner)
    for al, objs in alias_of.items():
        if len(objs) > 1:
            bad.append(f"alias collision '{al}': {sorted(objs)}")
        if al in physical and al not in objs:
            bad.append(f"alias '{al}' equals the physical id of another object")
        if totals is not None and al in totals["all"] and al not in objs:
            bad.append(f"alias '{al}' equals a netlist signal name")
    return bad


# ---- coverage -------------------------------------------------------------------------------------------------------

def m9k_id(m):
    return f"m9k_{m['x']}_{m['y']}"


def mac_id(m):
    return f"mac_{m['x']}_{m['y']}"


def netlist_totals(nl):
    t = dict(ff={f["name"] for f in nl.ffs}, lut={l["name"] for l in nl.luts}, m9k={m9k_id(m) for m in nl.m9k},
             mac={mac_id(m) for m in nl.mac}, pll={f"pll_{p['k']}" for p in nl.pll}, pad={f"pad_{i['ball']}" for i in nl.ios},
             clk={f["clk"] for f in nl.ffs if f.get("clk")})
    t["all"] = set().union(*t.values())
    return t


def coverage(eng, image, totals, record=True):
    import schema as S
    from sqlalchemy import insert, select
    blocks, mem = load_all(eng, image)
    kinds = ("ff", "lut", "m9k", "mac")
    named = {k: set() for k in kinds}
    by_tag = {t: dict(blocks=0, **{k: 0 for k in kinds}) for t in TAGS}
    for b in blocks:
        by_tag[b["tag"]]["blocks"] += 1
        for m in mem[b["block_id"]]:
            if m["obj_kind"] in kinds and m["obj_id"] in totals[m["obj_kind"]]:
                by_tag[b["tag"]][m["obj_kind"]] += 1
                if b["tag"] != "U":
                    named[m["obj_kind"]].add(m["obj_id"])
    res = {k: dict(total=len(totals[k]), named=len(named[k])) for k in kinds}
    for k in kinds:
        res[k]["pct"] = round(100.0 * res[k]["named"] / res[k]["total"], 2) if res[k]["total"] else 0.0
    res["by_tag"] = by_tag
    if record:
        with eng.begin() as conn:
            run = conn.execute(select(S.gate_runs.c.id).where(S.gate_runs.c.family == "cycloneiv").order_by(S.gate_runs.c.id.desc()).limit(1)).scalar()
            conn.execute(insert(S.annotation_coverage).values(
                image=image, ts=datetime.datetime.now(datetime.timezone.utc), gate_run_id=run, by_tag=by_tag,
                **{f"{k}_{x}": res[k][x] for k in kinds for x in ("total", "named")}))
        res["gate_run_id"] = run
    return res


# ---- seeding from existing evidence ---------------------------------------------------------------------------------

def readers(nl):
    """signal -> set of consumer ids (LUT pins, FF control fields, M9K / MAC / pad signal strings)."""
    rd = collections.defaultdict(set)
    for l in nl.luts:
        for p in l["pins"]:
            rd[p].add(l["name"])
    for f in nl.ffs:
        for k in ("d", "ena", "aclr", "sclr", "sload", "asdata", "clk"):
            if isinstance(f.get(k), str):
                rd[f[k]].add(f["name"])

    def walk(v, who):
        if isinstance(v, str):
            rd[v].add(who)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x, who)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x, who)
    for m in nl.m9k:
        for k in ("data", "addr", "we", "be", "clk"):
            walk(m.get(k), m9k_id(m))
    for m in nl.mac:
        for k in ("a", "b", "clk", "ena", "aclr", "sign"):
            walk(m.get(k), mac_id(m))
    for i in nl.ios:
        walk(i.get("drv"), f"pad_{i['ball']}")
    return rd


def absorb_cone(ffs, lut_by, rd, claimed):
    """Members = the FFs plus every LUT whose consumers all lie inside the set (private D / control cone), unclaimed."""
    cone = set(ffs)
    cand = set()
    while True:
        for n in list(cone):
            if n.startswith("ff_") and n in lut_by.get("ff", {}):
                f = lut_by["ff"][n]
                cand.update(f[k] for k in ("d", "ena", "aclr", "sclr", "sload", "asdata") if isinstance(f.get(k), str))
            elif n.startswith("lc_"):
                cand.update(lut_by["lut"][n]["pins"])
        grow = {c for c in cand if c.startswith("lc_") and c in lut_by["lut"] and c not in cone and c not in claimed
                and rd[c] and rd[c] <= cone}
        if not grow:
            return cone
        cone |= grow


def find_trace(members, trace_dir):
    """Existing trace file for a group: a json whose `ffs` list equals the members, else the seed-trace log if it names one."""
    ms = set(members)
    if os.path.isdir(trace_dir):
        for fn in sorted(os.listdir(trace_dir)):
            if fn.endswith(".json"):
                try:
                    d = json.load(open(os.path.join(trace_dir, fn)))
                except ValueError:
                    continue
                if isinstance(d, dict) and set(d.get("ffs") or []) == ms:
                    return "trace:" + os.path.relpath(os.path.join(trace_dir, fn), REPO)
    lg = "tmp/logs/cycloneiv_clean_seed_trace.log"
    return f"log:{lg}" if ref_problem("log", lg, list(ms)) is None else None


def seed_image(eng, image, nl, patterns, clocks, trace_dir):
    rd = readers(nl)
    lut_by = dict(ff={f["name"]: f for f in nl.ffs}, lut={l["name"]: l for l in nl.luts})
    claimed, stats = set(), collections.Counter()
    pjson = os.path.relpath(patterns, REPO) if patterns.startswith(REPO) else patterns
    det = json.load(open(patterns))

    def put(kind, name, claim, tag, ev, ffs, extra=()):
        cone = absorb_cone(ffs, lut_by, rd, claimed)
        ms = [(i, None) for i in sorted(cone | set(extra))]
        bid, act = add_block(eng, image, kind, name, claim, tag, ev, ms)
        claimed.update(cone)
        stats[act] += 1
        return bid

    # 1. LFSR / PRBS groups (autonomous, polynomial matched) and CRC-class parallel groups; V only with a trace file naming the group
    for i, g in enumerate(det["lfsr"]):
        tr = find_trace(g["members"], trace_dir)
        match = g["match"][0][0] if g["match"] else "no table match"
        ev = ";".join(x for x in (tr, f"json:{pjson}", "doc:docs/altera/cycloneIV/cycloneiv-clean-patterns.md") if x)
        put("SCR", f"PRBS{g['n']}-{i}", f"autonomous {g['form']} LFSR n={g['n']} {g['poly']} ({match}); seed traced; H: on-chip test-pattern / timer source (no pad downstream), whitening use not excluded",
            "V" if tr else "I", ev, g["members"])
    for i, g in enumerate(det["parallel"]):
        if g["match"]:
            tr = find_trace(g["members"], trace_dir)
            ev = ";".join(x for x in (tr, f"json:{pjson}", "doc:docs/altera/cycloneIV/cycloneiv-clean-patterns.md") if x)
            put("CRC", f"CRC{g['n']}-{i}", f"serial {g['n']}-stage group matching {g['match'][0][0]}; H: checks a byte stream from an M9K",
                "V" if tr else "I", ev, g["members"])
        else:
            put("DAT", f"LIN{g['n']}-{i}", f"linear {g['n']}-stage GF(2) group, no table polynomial match; function unknown", "U",
                f"json:{pjson}", g["members"])
    # 2. counters / accumulators (structural detector, no trace)
    for i, c in enumerate(det["counters"]):
        if claimed & set(c["ffs"]):
            stats["counter_overlap_skipped"] += 1
            continue
        put("CNT", f"{c['kind']}{c['width']}-{i}", f"{c['kind']} {c['width']} bits (structural detector)", "I",
            f"json:{pjson};doc:docs/altera/cycloneIV/cycloneiv-clean-patterns.md", c["ffs"])
    # 3. PLLs and clock domains
    clk = json.load(open(clocks))
    clog = "log:tmp/logs/cycloneiv_clean_image_clocks.log"
    cjson = "json:" + (os.path.relpath(clocks, REPO) if clocks.startswith(REPO) else clocks)
    for k, p in sorted(clk["pll"].items(), key=lambda kv: int(kv[0])):
        add_block(eng, image, "PLL", f"PLL{k}", f"PLL {k} enabled, M={p['params']['m']} N={p['params']['n']}; input frequency unknown (interval only)",
                  "V", f"{clog};{cjson}", [(f"pll_{k}", None)])
        stats["new_or_same"] += 1
    ffs_by_clk = collections.Counter(f["clk"] for f in nl.ffs if f.get("clk"))
    for d in clk["domains"]:
        root = f"u_clkbuf_out_{d['x']}_{d['y']}_{d['z']}_{d['index']}"
        add_block(eng, image, "CLK", f"domain-{d['x']}-{d['y']}-{d['z']}", f"clock domain, {d['ffs']} FFs by clock-line decode ({ffs_by_clk.get(root, 0)} by netlist clock)",
                  "V", f"{clog};{cjson}", [(root, None)])
        stats["domains"] += 1
    # 4. MAC (decoded config) and M9K (modelled: decoded; unmodelled: unknown)
    rom = {tuple(r["xy"]): r for r in det["mac_rom"]}
    for m in nl.mac:
        r = rom.get((m["x"], m["y"]))
        add_block(eng, image, "MAC", f"MAC-{m['x']}-{m['y']}",
                  f"hard multiplier, {'9x9' if m['nine'] else '18x18'}, output reg {m['oreg']}, M9K operands A/B {r['m9k_a']}/{r['m9k_b']}" if r else
                  f"hard multiplier, {'9x9' if m['nine'] else '18x18'}, output reg {m['oreg']}",
                  "I", f"ledger:MA-004;doc:docs/altera/cycloneIV/cycloneiv-clean-mac.md", [(mac_id(m), None)])
        stats["mac"] += 1
    unmod = []
    for m in nl.m9k:
        if m["modelled"]:
            add_block(eng, image, "MEM", f"M9K-{m['x']}-{m['y']}", f"M9K, {m['W']}-bit words x 2^{m['A']}, address class {m['cls']}; content decoded",
                      "I", "ledger:M-019;doc:docs/altera/cycloneIV/cycloneiv-clean-m9k.md", [(m9k_id(m), None)])
            stats["m9k_modelled"] += 1
        else:
            unmod.append((m9k_id(m), None))
    if unmod:
        add_block(eng, image, "MEM", "M9K-unmodelled", "M9Ks whose mode / width / content the emit does not model; role unknown", "U",
                  f"json:{pjson}", unmod)
        stats["m9k_unmodelled"] = len(unmod)
    log.info("seed-image: %s", dict(stats))
    return stats


# ---- CLI ------------------------------------------------------------------------------------------------------------

def load_nl(path):
    return pickle.load(open(path, "rb"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", default="image", help="netlist label the ids belong to (emit label of the image)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add")
    s.add_argument("--kind", required=True, choices=KINDS)
    s.add_argument("--name", required=True)
    s.add_argument("--claim", required=True)
    s.add_argument("--tag", required=True, choices=TAGS)
    s.add_argument("--evidence", required=True)
    s.add_argument("--members", required=True)
    s.add_argument("--block")
    s = sub.add_parser("list")
    s.add_argument("--kind")
    s.add_argument("--tag")
    s = sub.add_parser("check")
    s.add_argument("--nl", help="also require every member to exist in this netlist pickle")
    s = sub.add_parser("coverage")
    s.add_argument("--nl", default=DEFAULT_NL)
    s.add_argument("--no-record", action="store_true")
    s = sub.add_parser("names")
    s.add_argument("--out")
    s = sub.add_parser("remove")
    s.add_argument("--block", required=True)
    s = sub.add_parser("seed-image")
    s.add_argument("--nl", default=DEFAULT_NL)
    s.add_argument("--patterns", default=os.path.join(REPO, "tmp", "dji_patterns", "patterns.json"))
    s.add_argument("--clocks", default=os.path.join(REPO, "tmp", "cycloneiv_clean", "image_clocks.json"))
    s.add_argument("--trace-dir", default=os.path.join(REPO, "tmp", "dji_seed"))
    a = ap.parse_args(argv)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[logging.StreamHandler(), logging.FileHandler(LOG)])
    eng = get_engine()
    if a.cmd == "add":
        bad = evidence_problems(a.tag, a.evidence, [m for m, _ in read_members(a.members)])
        if bad:
            sys.exit("rejected: " + "; ".join(bad))
        print(*add_block(eng, a.image, a.kind, a.name, a.claim, a.tag, a.evidence, read_members(a.members), block=a.block))
    elif a.cmd == "list":
        blocks, _ = load_all(eng, a.image)
        for b in blocks:
            if (a.kind and b["kind"] != a.kind) or (a.tag and b["tag"] != a.tag):
                continue
            print(f"{b['block_id']}\t{b['tag']}\t{b['n_members']}\t{b['name']}\t{b['claim']}\t{b['evidence']}\t{b['date']}")
    elif a.cmd == "check":
        bad = check(eng, a.image, netlist_totals(load_nl(a.nl)) if a.nl else None)
        for p in bad:
            log.error("CHECK FAIL %s", p)
        log.info("check: %d problems", len(bad))
        sys.exit(1 if bad else 0)
    elif a.cmd == "coverage":
        res = coverage(eng, a.image, netlist_totals(load_nl(a.nl)), record=not a.no_record)
        log.info("coverage %s", json.dumps(res))
        print(json.dumps(res, indent=1))
    elif a.cmd == "names":
        _, mem = load_all(eng, a.image)
        rows = [(m["alias"], m["obj_id"]) for ms in mem.values() for m in ms if m["alias"]]
        text = "".join(f"{al}\t{o}\n" for al, o in sorted(rows))
        if a.out:
            open(a.out, "w").write(text)
        print(text, end="")
        log.info("names: %d aliases", len(rows))
    elif a.cmd == "remove":
        print(remove_block(eng, a.image, a.block))
    elif a.cmd == "seed-image":
        nl = load_nl(a.nl)
        print(dict(seed_image(eng, a.image, nl, a.patterns, a.clocks, a.trace_dir)))


if __name__ == "__main__":
    main()
