#!/usr/bin/env python3
"""Directed routing fuzz via RCF import: steer ONE net's route, refit, diff bits.

Modes:
  edit     replace one element idx in the net's RCF text.  The fitter accepts it only if the new
           route is a legal path; otherwise it drops that fan-out's constraint and reroutes.
  exclude  append `section exclusion_list { TYPE:XxYyS0Ik; ... }` (resources the router must not
           use); the fan-out reroutes around them, every other net keeps its imported route.
           Depth k = k-th alternative at that hop (each step also excludes the previous detour).
  After each exclude variant the exported RCF is re-imported alone (REPLAY): accepted if the
  re-export is identical and the bitstream equals the variant's.

Mechanism (docs/cyclonev-rcf-oracle.md): the .qsf carries ROUTING_BACK_ANNOTATION_FILE build.rcf
(written by quartus_cdb --write_settings_files=on, with every LOCATION), so quartus_fit imports
the RCF as soft routing constraints.  A variant is ACCEPTED when the re-exported RCF of the edited
net equals the edited text; otherwise the fitter dropped the constraint and rerouted (REROUTED).

Per variant (own scratch dir under tmp/rcf_fuzz/<design>/): fit -> asm -> cpf -> cdb --back_annotate.
Bits = rbf bytes XOR the CONTROL build (unedited RCF through the same flow).

Usage:
  python3.15t scripts/cyclonev_rcf_fuzz.py --design adder12 --mode exclude --depth 3 \\
      --target 's[0]~reg0|s[0]~output|LOCAL_INTERCONNECT|0' [--target ...] [--workers 3]
  python3.15t scripts/cyclonev_rcf_fuzz.py --design shiftreg16 --mode edit \\
      --target 'sr[3]|q[3]~output|C2|0' [--alts auto|0-19]
  target = net|dest atom|element TYPE|nth occurrence on that branch
  --alts auto: candidates mined from the corpus edge graph (rcf_routes, all builds): m is an
  alternative to the element if pred->m and m->succ edges (same type/idx/relative x,y) were seen.
Log: tmp/logs/cyclonev_rcf_fuzz.log ; rows -> table rcf_fuzz_bits (corpus.db).
"""
import argparse
import logging
import os
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ.setdefault("PLURIBUS_SQLITE_PATH", str(REPO / "corpus" / "cyclonev" / "corpus.db"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import cyclonev_corpus_build as cb  # noqa: E402
import cyclonev_rcf_parse as rp  # noqa: E402
import heavy_guard  # noqa: E402
import toolchain  # noqa: E402

LOG = REPO / "tmp" / "logs" / "cyclonev_rcf_fuzz.log"
WORK = REPO / "tmp" / "rcf_fuzz"
log = logging.getLogger("rcf_fuzz")
RCF_MSG = re.compile(r"(RCF|Routing Constraints|routing constraint|constrained routing)", re.I)


def setup_logging():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    h1 = logging.FileHandler(LOG)
    h2 = logging.StreamHandler(sys.stdout)
    for h in (h1, h2):
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
        cb.log.addHandler(h)
    cb.log.setLevel(logging.INFO)


def flow(qb, vdir, logs, with_cdb=True):
    """fit -> asm -> cpf (-> cdb back-annotate).  Returns failing step or None."""
    heavy_guard.wait_available(log, "rcf_fuzz flow")
    steps = [("quartus_fit", [qb / "quartus_fit", "build", "-c", "build"]),
             ("quartus_asm", [qb / "quartus_asm", "build"]),
             ("quartus_cpf", [qb / "quartus_cpf", "-c", "build.sof", "build.rbf"])]
    for step, cmd in steps:
        if not cb.run(step, cmd, vdir, logs):
            return step
    if with_cdb:
        shutil.copyfile(vdir / "build.rcf", vdir / "edited.rcf")
        if not cb.run("quartus_cdb", [qb / "quartus_cdb", "build", "-c", "build",
                                      "--back_annotate=routing", "--write_settings_files=on"],
                      vdir, logs):
            return "quartus_cdb"
    return None


def fresh_copy(src, dst):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.rbf", "*.sof", "simulation"))


def edit_rcf(text, net, element, x, y, n, old_idx, new_idx, dest=None):
    """Replace one element line inside the net's block (the one on dest's branch if given)."""
    lines = text.split("\n")
    out, in_net, done, pending = [], False, False, []
    pat = re.compile(rf"^(\t{re.escape(element)}:X{x}Y{y}S{n}I){old_idx};$")
    # collect the net block, edit the line sitting in the branch that ends at `dest`
    start = next(i for i, l in enumerate(lines) if l == f"signal_name = {net} {{")
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    branch_start = start + 1
    for i in range(start + 1, end):
        if lines[i].lstrip().startswith("dest = "):
            if dest is None or f"( {dest}, " in lines[i]:
                for j in range(branch_start, i):
                    m = pat.match(lines[j])
                    if m:
                        lines[j] = f"{m.group(1)}{new_idx};"
                        return "\n".join(lines)
            branch_start = i + 1
    raise SystemExit(f"element {element}:X{x}Y{y}S{n}I{old_idx} not found in net {net!r} (dest {dest!r})")


def rbf_bits(a, b):
    da, db_ = a.read_bytes(), b.read_bytes()
    if len(da) != len(db_):
        return None
    return [[i, k] for i, (p, q) in enumerate(zip(da, db_)) if p != q
            for k in range(8) if (p ^ q) >> k & 1]


def bt_diff(qb_cv, rbf_a, rbf_b, wd):
    """Decompile both with mistral-cv; return {only_control: [...], only_variant: [...]}."""
    outs = []
    for k, r in enumerate((rbf_a, rbf_b)):
        o = wd / f"d{k}.bt"
        if not cb.run("decomp", [qb_cv, "decomp", cb.DEVICE, r, o], wd, wd / "logs"):
            return None
        outs.append(set(o.read_text().split("\n")))
    return {"control_only": sorted(outs[0] - outs[1]), "variant_only": sorted(outs[1] - outs[0])}


def net_routes(rcf_path, net):
    """{dest: tuple of hop tuples} for one net, branch-order independent."""
    rows = [r for r in rp.parse(rcf_path) if r["net"] == net]
    by = {}
    for r in rows:
        by.setdefault(r["branch"], []).append(r)
    res = {}
    for b, rs in by.items():
        rs.sort(key=lambda r: r["hop"])
        res[(rs[0]["dest_atom"], rs[0]["dest_port"])] = (
            rs[0]["parent_label"],
            tuple((r["kind"], r["element"], r["x"], r["y"], r["n"], r["idx"], r["port_path"])
                  for r in rs))
    return res


def elem_str(h):
    return f"{h[1]}:X{h[2]}Y{h[3]}S{h[4]}I{h[5]}"


def full_routes(rcf_path):
    """{(net, dest atom, dest port): (parent_label, hop tuples)} for every branch of the file."""
    br = {}
    for r in rp.parse(rcf_path):
        br.setdefault((r["net"], r["dest_atom"], r["dest_port"]), []).append(r)
    return {k: (v[0]["parent_label"], tuple((r["kind"], r["element"], r["x"], r["y"], r["n"], r["idx"],
                                             r["port_path"]) for r in sorted(v, key=lambda r: r["hop"])))
            for k, v in br.items()}


def exclude_chain(a, qb, base, ctl_rbf, spec, depth):
    """Iteratively exclude the target element (+ earlier detours); one row per depth."""
    net, dest, el, _ = spec.split("|")
    t = pick_target(base / "build.rcf", spec)
    key = (net, dest, t["dest_port"])
    old = full_routes(base / "build.rcf")[key][1]
    old_i = {h for h in old if h[5] is not None}
    excluded = [elem_str(("", t["element"], t["x"], t["y"], t["n"], t["idx"]))]
    rows = []
    tag = re.sub(r"[^A-Za-z0-9]+", "_", spec)
    for d in range(1, depth + 1):
        vdir = WORK / a.design / f"x_{tag}_{d}"
        fresh_copy(base, vdir)
        text = (base / "build.rcf").read_text()
        (vdir / "build.rcf").write_text(text + "\nsection exclusion_list {\n"
                                        + "".join(f"\t{e};\n" for e in excluded) + "}\n")
        row = dict(alt_idx=d, mode="exclude", excluded=list(excluded), new_route=None, replay=None,
                   n_changed=None, changed_bits=None, bt_diff=None, note=None)
        fail = flow(qb, vdir, vdir / "logs")
        if fail:
            row["status"] = f"fail:{fail}"
            rows.append(row)
            break
        # the exclusion section is not echoed by cdb: the exported file is the plain imported routing
        new = full_routes(vdir / "build.rcf").get(key)
        row["new_route"] = [elem_str(h) for h in new[1] if h[5] is not None] if new else None
        bits = rbf_bits(ctl_rbf, vdir / "build.rbf")
        row["n_changed"] = None if bits is None else len(bits)
        row["changed_bits"] = bits
        if bits:
            row["bt_diff"] = bt_diff(toolchain.mistral_cv(), ctl_rbf, vdir / "build.rbf", vdir)
        new_i = {h for h in new[1] if h[5] is not None} if new else set()
        used = any(elem_str(h) in excluded for h in new_i)
        row["status"] = "no_alternative" if (new is None or new[1] == old or used) else "rerouted"
        if row["status"] == "rerouted":
            row["replay"] = replay(a, qb, base, vdir, key, new)
        rows.append(row)
        if row["status"] != "rerouted":
            break
        # next depth: also exclude the detour's same-type elements that the old route did not use
        for h in new_i - old_i:
            if h[1] == el and elem_str(h) not in excluded:
                excluded.append(elem_str(h))
    return t, rows


def replay(a, qb, base, vdir, key, new):
    """Import the variant's exported RCF alone into a fresh copy of base; compare re-export + rbf."""
    rdir = Path(str(vdir) + "_replay")
    fresh_copy(base, rdir)
    shutil.copyfile(vdir / "build.rcf", rdir / "build.rcf")
    fail = flow(qb, rdir, rdir / "logs")
    if fail:
        return f"fail:{fail}"
    same_rcf = full_routes(rdir / "edited.rcf") == full_routes(rdir / "build.rcf")
    same_rbf = (rdir / "build.rbf").read_bytes() == (vdir / "build.rbf").read_bytes()
    return "accepted" if same_rcf and same_rbf else f"rejected(rcf_same={same_rcf},rbf_same={same_rbf})"


def mine_edges():
    """Observed edges over every build: (type, idx, dx, dy) -> {(type, idx)} (I-form elements)."""
    import db
    from collections import defaultdict
    rows = db.connect_threadsafe().execute(
        "select build,net,branch,hop,element,x,y,idx from rcf_routes "
        "where kind='elem' and port_path is null order by build,net,branch,hop").fetchall()
    br = defaultdict(list)
    for r in rows:
        br[(r[0], r[1], r[2])].append(r)
    fwd = defaultdict(set)
    for rs in br.values():
        for a, b in zip(rs, rs[1:]):
            fwd[(a[4], a[7], b[5] - a[5], b[6] - a[6])].add((b[4], b[7]))
    return fwd


def mined_alts(fwd, pred, mid, succ):
    """Same-type idx values m with pred->m and m->succ observed elsewhere in the corpus."""
    out = []
    for t, i in fwd[(pred["element"], pred["idx"], mid["x"] - pred["x"], mid["y"] - pred["y"])]:
        if t != mid["element"] or i == mid["idx"]:
            continue
        if (succ["element"], succ["idx"]) in fwd[(t, i, succ["x"] - mid["x"], succ["y"] - mid["y"])]:
            out.append(i)
    return sorted(out)


def run_variant(a, qb, base, target, control_rbf, alt):
    vdir = WORK / a.design / f"v_{re.sub(r'[^A-Za-z0-9]+', '_', target[0])}_{target[1]}_{target[2]}_{target[3]}_{alt}"
    fresh_copy(base, vdir)
    net, el, x, y, n, old, dest = target
    text = edit_rcf((base / "build.rcf").read_text(), net, el, x, y, n, old, alt, dest)
    (vdir / "build.rcf").write_text(text)
    fail = flow(qb, vdir, vdir / "logs")
    row = dict(alt_idx=alt, mode="edit", excluded=None, new_route=None, replay=None)
    if fail:
        row.update(status=f"fail:{fail}", n_changed=None, changed_bits=None, bt_diff=None,
                   note=None)
        return row
    want = net_routes(vdir / "edited.rcf", net)
    got = net_routes(vdir / "build.rcf", net)
    # 170097/170098/170119 = "routing constrained / error on line N / constraint removed, rerouted"
    ids = sorted({m for m in re.findall(r"\((170097|170098|170119)\)",
                                        (vdir / "logs" / "quartus_fit.log").read_text())})
    msgs = ["fitter msgs " + ",".join(ids)] if ids else []
    bits = rbf_bits(control_rbf, vdir / "build.rbf")
    btd = None
    if bits:
        btd = bt_diff(toolchain.mistral_cv(), control_rbf, vdir / "build.rbf", vdir)
    row.update(status="accepted" if want == got else "rerouted",
               n_changed=None if bits is None else len(bits), changed_bits=bits, bt_diff=btd,
               note="; ".join(msgs)[:500] if msgs else None)
    return row


def pick_target(base_rcf, spec):
    net, dest, el, nth = spec.split("|")
    rows = [r for r in rp.parse(base_rcf) if r["net"] == net and r["element"] == el
            and r["dest_atom"] == dest]
    rows.sort(key=lambda r: (r["branch"], r["hop"]))
    if int(nth) >= len(rows):
        sys.exit(f"target {spec}: only {len(rows)} {el} element(s)")
    return rows[int(nth)]


def neighbours(base_rcf, t):
    """pred / succ I-form elements of t inside its own branch (None when absent)."""
    rs = sorted((r for r in rp.parse(base_rcf) if r["net"] == t["net"] and r["branch"] == t["branch"]
                 and r["kind"] == "elem" and r["port_path"] is None), key=lambda r: r["hop"])
    k = next(i for i, r in enumerate(rs) if r["hop"] == t["hop"])
    return (rs[k - 1] if k else None), (rs[k + 1] if k + 1 < len(rs) else None)


def list_targets(rcf, fwd):
    rows = [r for r in rp.parse(rcf) if r["kind"] == "elem" and r["port_path"] is None]
    br = {}
    for r in rows:
        br.setdefault((r["net"], r["branch"]), []).append(r)
    for (net, _), rs in br.items():
        rs.sort(key=lambda r: r["hop"])
        for k in range(1, len(rs) - 1):
            alts = mined_alts(fwd, rs[k - 1], rs[k], rs[k + 1])
            if alts:
                nth = sum(1 for r in rs[:k] if r["element"] == rs[k]["element"])
                print(f"{net}|{rs[k]['dest_atom']}|{rs[k]['element']}|{nth}  idx {rs[k]['idx']} alts {alts}")


def main():
    setup_logging()
    with heavy_guard.heavy_lock("cyclonev_rcf_fuzz", log):
        _main()


def _main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--design", required=True)
    ap.add_argument("--target", action="append", help="net|dest|element|nth")
    ap.add_argument("--list", action="store_true", help="print targets that have mined alternatives")
    ap.add_argument("--mode", choices=("edit", "exclude"), default="exclude")
    ap.add_argument("--depth", type=int, default=3, help="exclude mode: alternatives per target")
    ap.add_argument("--alts", default="auto", help="'auto' (mined) or idx range e.g. 0-19")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    import db
    import schema
    from sqlalchemy import delete, insert
    schema.init()
    qb = Path(toolchain.quartus_bin())
    ddir = REPO / "corpus" / "cyclonev" / a.design
    if a.list:
        list_targets(ddir / "build.rcf", mine_edges())
        return
    if not a.target:
        sys.exit("--target required")
    base = WORK / a.design / "base"
    # base = quartus project + RCF/locations written by cdb (scratch copy: it rewrites the .qsf)
    fresh_copy(ddir / "quartus", base)
    heavy_guard.wait_available(log, "rcf_fuzz base cdb")
    if not cb.run("quartus_cdb", [qb / "quartus_cdb", "build", "-c", "build",
                                  "--back_annotate=routing", "--write_settings_files=on"],
                  base, WORK / a.design / "logs_base"):
        sys.exit("cdb failed")
    # control = unedited RCF through the same flow
    ctl = WORK / a.design / "control"
    fresh_copy(base, ctl)
    fail = flow(qb, ctl, ctl / "logs", with_cdb=False)
    if fail:
        sys.exit(f"control failed at {fail}")
    orig_bits = rbf_bits(ddir / "bitstream.rbf", ctl / "build.rbf")
    log.info("control vs corpus bitstream.rbf: %s bits differ", None if orig_bits is None else len(orig_bits))
    fwd = mine_edges() if a.mode == "edit" and a.alts == "auto" else None
    bid = db.connect_threadsafe().execute(
        "select id from postfit_builds where design=?", (a.design,)).fetchone()[0]
    tt = schema.rcf_fuzz_bits
    if a.mode == "exclude":
        with ThreadPoolExecutor(a.workers) as ex:
            outs = list(ex.map(lambda sp: exclude_chain(a, qb, base, ctl / "build.rbf", sp, a.depth),
                               a.target))
        for spec, (t, rows) in zip(a.target, outs):
            net = spec.split("|")[0]
            common = dict(build=bid, net=net, branch=t["branch"], hop=t["hop"], element=t["element"],
                          x=t["x"], y=t["y"], orig_idx=t["idx"])
            with db.engine().begin() as conn:
                conn.execute(delete(tt).where((tt.c.build == bid) & (tt.c.net == net)
                                              & (tt.c.element == t["element"]) & (tt.c.x == t["x"])
                                              & (tt.c.y == t["y"]) & (tt.c.mode == "exclude")))
                conn.execute(insert(tt), [dict(common, mode="exclude", alt_idx=None, status="control",
                                               excluded=None, new_route=None, replay=None,
                                               n_changed=len(orig_bits) if orig_bits is not None else None,
                                               changed_bits=None, bt_diff=None,
                                               note="control vs corpus bitstream.rbf")]
                             + [dict(common, **r) for r in rows])
            for r in rows:
                log.info("%s depth %s %s bits=%s replay=%s new=%s", spec, r["alt_idx"], r["status"],
                         r["n_changed"], r["replay"], (r["new_route"] or [])[:8])
        return
    for spec in a.target:
        t = pick_target(base / "build.rcf", spec)
        net, dest, el, _ = spec.split("|")
        target = (net, el, t["x"], t["y"], t["n"], t["idx"], dest)
        if fwd is not None:
            pred, succ = neighbours(base / "build.rcf", t)
            alts = mined_alts(fwd, pred, t, succ) if pred and succ else []
        else:
            lo, hi = (int(v) for v in a.alts.split("-"))
            alts = [i for i in range(lo, hi + 1) if i != t["idx"]]
        log.info("target %s; %d alternatives %s", target, len(alts), alts[:12])
        with ThreadPoolExecutor(a.workers) as ex:
            results = list(ex.map(lambda alt: run_variant(a, qb, base, target, ctl / "build.rbf", alt),
                                  alts))
        # a tool killed by the host-load guard (cb.OVERALL_S) is not a fit verdict: retry serially once
        for k, r in enumerate(results):
            if str(r["status"]).startswith("fail:"):
                log.info("retry alt %s after %s", r["alt_idx"], r["status"])
                results[k] = run_variant(a, qb, base, target, ctl / "build.rbf", r["alt_idx"])
        common = dict(build=bid, net=net, branch=t["branch"], hop=t["hop"], element=el,
                      x=t["x"], y=t["y"], orig_idx=t["idx"])
        with db.engine().begin() as conn:
            conn.execute(delete(tt).where((tt.c.build == bid) & (tt.c.net == net)
                                          & (tt.c.element == el) & (tt.c.x == t["x"])
                                          & (tt.c.y == t["y"]) & (tt.c.mode == "edit")))
            conn.execute(insert(tt), [dict(common, mode="edit", alt_idx=None, status="control",
                                           excluded=None, new_route=None, replay=None, n_changed=len(orig_bits) if orig_bits is not None else None,
                                           changed_bits=None, bt_diff=None,
                                           note="control vs corpus bitstream.rbf")] +
                         [dict(common, **r) for r in results])
        for r in results:
            log.info("%s alt %2s %-10s changed_bits=%s %s", spec, r["alt_idx"], r["status"],
                     r["n_changed"], (r["note"] or "")[:100])


if __name__ == "__main__":
    main()
