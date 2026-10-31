#!/usr/bin/env python3.15t
"""Where ground->air DUML enters the FPGA fabric (#177), anchored on the Master-ID registers.

The MCU writes the 5-byte Master-ID to SPI write registers 3..7 (awto-dji docs/id-entry-point.md), so those
40 FFs have known content and a known role: RX frame filter (compare) and TX frame header (insert). This
script, read-only on the netlist, reuses cycloneiv_clean_spi_trace.py's register map (tmp/dji_spi/<tag>.json)
and reports, each with cell names:
  A  forward cone of every ID-register FF: comparator pairs vs everything else, sinks (M9K pin / MAC / pad / FF)
  B  comparator other side (the received-ID field): backward hops to its source (pads / M9K / FF groups)
  C  combiner (frame-accept) output: what it enables downstream
  D  AD9363 TX bus: M9K tiles behind the pad drivers, their write-side sources, backward to RF / pads / M9K
  E  FX3 DQ pads as inputs: forward sinks, overlap with the TX tiles
  F  the readback snapshot FFs: overlap of their D-cone with the comparator-other-side neighbourhood

  python3.15t scripts/cycloneiv_clean_duml_entry_trace.py --nl NL.pkl [--spi tmp/dji_spi/image.json]
Log tmp/logs/cycloneiv_clean_duml_entry_trace.log, JSON tmp/cycloneiv_clean/duml_entry_trace.json.
Walks are bounded (visited-node cap + FF-hop cap): comb chains in this image are long (#177 interior-bus pass).
"""
import argparse
import collections
import json
import logging
import os
import pickle
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("duml_entry")
ID_REGS = ("0x3", "0x4", "0x5", "0x6", "0x7")
TX_PADS = ["E25", "E26", "F26", "G25", "G26", "H24", "H25", "H26", "J26", "K26", "L25", "L26"]
FX3_DQ = ["A3", "A4", "B4", "C2", "C3", "C4", "D2", "D3"]
CAP = 3000      # visited-node cap per walk; 4000 was enough for the interior-bus sweep, this is per-bit so lower
FF_HOPS = 4     # FF stages per forward walk; the regfile->packer distance in section 5 is 1-3 stages


def xy(name):
    m = re.match(r"(?:lc|ff)_(\d+)_(\d+)_", name)
    return (int(m.group(1)), int(m.group(2))) if m else None


def fwd(N, fanout, starts, ff_hops=FF_HOPS, cap=CAP):
    """bounded forward walk: {sinks: Counter((kind, detail, pin)), ffs_by_hop, luts, capped}."""
    seen, out = set(), dict(sinks=collections.Counter(), ffs=collections.defaultdict(set), luts=set(), capped=False)
    cur = [(s, 0) for s in starts]
    while cur:
        s, h = cur.pop()
        if s in seen:
            continue
        if len(seen) >= cap:
            out["capped"] = True
            break
        seen.add(s)
        for kind, iid, pin, idx in fanout.get(s, []):
            if kind == "lc":
                out["luts"].add(iid)
                cur.append((iid, h))
            elif kind == "ff":
                if pin == "clk":
                    continue
                out["ffs"][h + 1].add(iid)
                if h + 1 <= ff_hops and pin in ("d", "asdata", "sload", "ena", "sclr"):
                    cur.append((iid, h + 1))
            elif kind == "io":
                out["sinks"][("pad", iid, pin)] += 1
            else:
                out["sinks"][(kind, iid, pin)] += 1
    out["ffs"] = {h: sorted(v) for h, v in out["ffs"].items()}
    out["luts"] = sorted(out["luts"])
    return out


def back(N, sigs, hops):
    """per hop: (FFs first reached, pads, m9k outputs, other leaves) through D/ena/sclr/sload/asdata."""
    seen, cur, out = set(), set(sigs), []
    for _ in range(hops):
        leaves = set()
        for s in cur:
            leaves |= N.comb_leaves(s)
        ffs = {x for x in leaves if x in N.ff} - seen
        non = {x for x in leaves if x not in N.ff}
        out.append(dict(ffs=sorted(ffs), pads=sorted(x[4:] for x in non if x.startswith("pad_")),
                        m9k=sorted(x for x in non if x.startswith("m9k_")), other=sorted(x for x in non if not x.startswith(("pad_", "m9k_")))))
        seen |= ffs
        cur = {N.ff[x][k] for x in ffs for k in ("d", "ena", "sclr", "sload", "asdata") if N.ff[x].get(k)}
        if not cur:
            break
    return out


def _nset(content):
    """words with any set bit; content is None, a list or a numpy array (emit.py stores init as an array)."""
    if content is None:
        return 0
    try:
        return int(sum(1 for w in content if (w.any() if hasattr(w, "any") else bool(w))))
    except TypeError:
        return 0


def labs(names):
    return sorted(collections.Counter(xy(n) for n in names if xy(n)).items(), key=lambda kv: -kv[1])


def m9k_tile(sig):
    m = re.match(r"m9k_(\d+)_(\d+)_o\[(\d+)\]", sig)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nl", required=True)
    ap.add_argument("--spi", default=os.path.join(REPO, "tmp", "dji_spi", "image.json"))
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    os.makedirs(os.path.join(REPO, "tmp", "cycloneiv_clean"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_duml_entry_trace.log"))])
    from lifters.cycloneiv_clean import functrace as FT
    import cycloneiv_clean_spi_trace as ST
    nl = pickle.load(open(a.nl, "rb"))
    N = ST.Net(nl)
    fanout = FT._build_fanout(nl)
    J = json.load(open(a.spi))
    RF = {n: (adr, b) for n, (adr, b) in J["rf_ffs"].items()}
    byreg = collections.defaultdict(list)
    for n, (adr, b) in RF.items():
        byreg[adr].append((b, n))
    R = {}

    # A. ID register forward cones
    trees = {t["root"]: t for t in J["equality_trees"]["trees"]}
    heq_luts = set()
    for root in trees:
        heq_luts |= set(ST._comb_nodes(N, root))
    log.info("== A. ID registers 3..7 forward cones (both copies; cap %d nodes, %d FF hops)", CAP, FF_HOPS)
    A = {}
    for adr in ID_REGS:
        ffs = [n for _b, n in sorted(byreg[adr])]
        copies = collections.defaultdict(list)
        for n in ffs:
            copies[N.ff[n].get("ena")].append(n)
        for ena, grp in copies.items():
            direct = collections.Counter()
            for n in grp:
                for c in N.cons.get(n, []):
                    direct["cmp" if c in heq_luts else ("ff." + c.split(".")[1] if c.startswith("ff_") else "lut")] += 1
            w = fwd(N, fanout, grp)
            sinks = collections.Counter()
            for (k, d, p), v in w["sinks"].items():
                sinks[(k, str(d), p)] += v
            rf_hit = sorted({RF[f][0] for h, fl in w["ffs"].items() for f in fl if f in RF})
            A[f"{adr}/{ena}"] = dict(ffs=grp, lab=labs(grp), direct=dict(direct), sinks={f"{k}:{d}:{p}": v for (k, d, p), v in sinks.items()},
                                     ffs_by_hop={h: len(v) for h, v in w["ffs"].items()}, lut_labs=labs(w["luts"])[:6],
                                     other_regs_reached=rf_hit, capped=w["capped"])
            log.info("[V] reg %s copy ena=%s FFs %s @%s: direct consumers %s; forward FFs by hop %s; sinks %s; LUT LABs %s; reaches regs %s%s",
                     adr, ena, grp, labs(grp), dict(direct), {h: len(v) for h, v in w["ffs"].items()},
                     dict(sinks) or "none", labs(w["luts"])[:5], rf_hit, " CAPPED" if w["capped"] else "")
    R["A_id_forward"] = A

    # B. comparator other side
    log.info("== B. comparator other side (received-ID field) and its source")
    B = {}
    other = []
    for root, t in trees.items():
        if set(t["reg_addresses"]) & {"0x3", "0x4", "0x5"}:
            leaves = N.comb_leaves(root)
            o = sorted(x for x in leaves if x not in RF)
            other += o
            B[root] = dict(reg=list(t["reg_addresses"]), other=o, ena=sorted({str(N.ff[x].get("ena")) for x in o if x in N.ff}),
                           clk=sorted({str(N.ff[x].get("clk")) for x in o if x in N.ff}))
            log.info("[V] tree %s vs reg %s: other side %s (ena %s, clk %s)", root, list(t["reg_addresses"]), o, B[root]["ena"], B[root]["clk"])
    bh = back(N, other, 8)
    for h, e in enumerate(bh):
        log.info("[V]  back hop %d: %d FFs %s; pads %s; m9k %s; other %s", h, len(e["ffs"]), labs(e["ffs"])[:6], e["pads"], e["m9k"][:8], e["other"][:6])
    B["back_hops"] = bh
    # D sources of the other-side FFs: shift register (prev FF) or parallel load?
    dsrc = {x: sorted(N.comb_leaves(N.ff[x]["d"])) for x in other if x in N.ff}
    B["d_sources"] = dsrc
    log.info("[V]  other-side D cones: %s", {x: v[:4] for x, v in list(dsrc.items())[:8]})
    R["B_comparator"] = B

    # C. combiner output
    log.info("== C. frame-accept combiner forward")
    C = {}
    for cb in J.get("combiners", []):
        w = fwd(N, fanout, [cb["lut"]], ff_hops=3)
        ens = collections.Counter()
        for h, fl in w["ffs"].items():
            for f in fl:
                F = N.ff[f]
                for k in ("ena", "sclr", "sload", "d"):
                    s = F.get(k)
                    if s and (s == cb["lut"] or (s in N.lut and cb["lut"] in N.comb_leaves(s))):
                        ens[k] += 1
        C[cb["lut"]] = dict(regs=cb["regs"], inputs=cb["inputs"], ffs_by_hop={h: len(v) for h, v in w["ffs"].items()}, hop1=w["ffs"].get(1, [])[:24],
                            hop1_labs=labs(w["ffs"].get(1, [])), sinks={f"{k}:{d}:{p}": v for (k, d, p), v in w["sinks"].items()}, direct_edge_kinds=dict(ens))
        log.info("[V] combiner %s (regs %s) inputs %s: hop-1 FFs %d @%s edge kinds %s; sinks %s", cb["lut"], cb["regs"], cb["inputs"],
                 len(w["ffs"].get(1, [])), labs(w["ffs"].get(1, []))[:4], dict(ens), dict(w["sinks"]) or "none")
    R["C_combiner"] = C

    # D. TX bus backward
    log.info("== D. AD9363 TX bus: M9K tiles behind the drivers and their write side")
    io = {i["ball"]: i for i in nl.ios}
    tiles = collections.defaultdict(set)
    sel = collections.Counter()
    for p in TX_PADS:
        drv = io[p]["drv"]
        for x in N.comb_leaves(drv):
            t = m9k_tile(x)
            if t:
                tiles[(t[0], t[1])].add(t[2])
            else:
                sel[x] += 1
    log.info("[V] TX pad driver leaves: M9K tiles %s; select/other leaves %s", {k: sorted(v) for k, v in tiles.items()}, dict(sel))
    D = dict(tiles={str(k): sorted(v) for k, v in tiles.items()}, select=dict(sel), write_side={})
    m9k = {(m["x"], m["y"]): m for m in nl.m9k}
    for k in tiles:
        m = m9k.get(k)
        if m is None:
            log.info("[V]  tile %s not in nl.m9k", k)
            continue
        info = dict(cls=m.get("cls"), sdp=m.get("sdp"), data=len(m.get("data") or []), addr=len(m.get("addr") or []), raddr=len(m.get("raddr") or []),
                    we=m.get("we"), A=m.get("A"), W=m.get("W"), content_set=sum(1 for w in (m.get("content") or []) if w))
        dsig = [s.lstrip("!") for s in (m.get("data") or []) if s and s not in ST.CV]
        bd = back(N, dsig, 8)
        info["data_back"] = []
        for h, e in enumerate(bd):
            rf = sorted({RF[f][0] for f in e["ffs"] if f in RF})
            info["data_back"].append(dict(hop=h, ffs=len(e["ffs"]), labs=labs(e["ffs"])[:4], rf=rf, pads=e["pads"], m9k=sorted({m9k_tile(x)[:2] for x in e["m9k"] if m9k_tile(x)})))
            log.info("[V]  tile %s data(%d) back hop %d: %d FFs %s; RF regs %s; pads %s; m9k %s", k, len(dsig), h, len(e["ffs"]), labs(e["ffs"])[:4], rf, e["pads"],
                     sorted({m9k_tile(x)[:2] for x in e["m9k"] if m9k_tile(x)}))
            if not e["ffs"]:
                break
        asig = [s.lstrip("!") for s in (m.get("addr") or []) if s and s not in ST.CV]
        ba = back(N, asig, 3)
        info["addr_back"] = [dict(hop=h, ffs=len(e["ffs"]), labs=labs(e["ffs"])[:3], rf=sorted({RF[f][0] for f in e["ffs"] if f in RF}), pads=e["pads"]) for h, e in enumerate(ba)]
        log.info("[V]  tile %s %s addr(%d) back: %s", k, info["cls"], len(asig), [(x["hop"], x["ffs"], x["rf"], x["pads"]) for x in info["addr_back"]])
        if m.get("we"):
            bw = back(N, [m["we"].lstrip("!")], 4)
            info["we_back"] = [dict(hop=h, ffs=len(e["ffs"]), labs=labs(e["ffs"])[:3], rf=sorted({RF[f][0] for f in e["ffs"] if f in RF}), pads=e["pads"]) for h, e in enumerate(bw)]
            log.info("[V]  tile %s we %s back: %s", k, m["we"], [(x["hop"], x["ffs"], x["rf"], x["pads"]) for x in info["we_back"]])
        D["write_side"][str(k)] = info
    R["D_tx"] = D

    # E. FX3 DQ as inputs
    log.info("== E. FX3 DQ input direction")
    E = {}
    for p in FX3_DQ:
        w = fwd(N, fanout, ["pad_" + p], ff_hops=3)
        tx_hit = sorted({str(d) for (k, d, pin) in w["sinks"] if k == "m9k" and d in tiles})
        E[p] = dict(ffs_by_hop={h: len(v) for h, v in w["ffs"].items()}, hop1=w["ffs"].get(1, []), sinks={f"{k}:{d}:{pin}": v for (k, d, pin), v in w["sinks"].items()},
                    tx_tile_hit=tx_hit, capped=w["capped"])
        log.info("[V] pad %s in: hop-1 FFs %s; FFs by hop %s; sinks %s; TX-tile overlap %s%s", p, w["ffs"].get(1, []), {h: len(v) for h, v in w["ffs"].items()},
                 dict(w["sinks"]) or "none", tx_hit or "none", " CAPPED" if w["capped"] else "")
    R["E_fx3_in"] = E

    # F. snapshot FFs vs comparator neighbourhood
    log.info("== F. readback snapshot FFs vs received-ID neighbourhood")
    snap = [x for x in J.get("readback_other_sources", {}) if x in N.ff]
    hood = set(other)
    for e in bh[:3]:
        hood |= set(e["ffs"])
    hit = {}
    for x in snap:
        lv = N.comb_leaves(N.ff[x]["d"])
        if lv & hood:
            hit[x] = sorted(lv & hood)
    snap_src = collections.Counter()
    for x in snap:
        for l in N.comb_leaves(N.ff[x]["d"]):
            snap_src[("rf" if l in RF else "pad" if l.startswith("pad_") else "m9k" if l.startswith("m9k_") else "ff" if l in N.ff else "other")] += 1
    sb = back(N, snap, 4)
    R["F_snapshot"] = dict(n=len(snap), d_leaf_kinds=dict(snap_src), hits_in_received_id_hood=hit,
                           back=[dict(hop=h, ffs=len(e["ffs"]), labs=labs(e["ffs"])[:5], pads=e["pads"], m9k=sorted({m9k_tile(x)[:2] for x in e["m9k"] if m9k_tile(x)})) for h, e in enumerate(sb)])
    log.info("[V] %d snapshot FFs: D-leaf kinds %s; D-leaves inside the received-ID neighbourhood: %d %s", len(snap), dict(snap_src), len(hit), list(hit.items())[:6])
    for e in R["F_snapshot"]["back"]:
        log.info("[V]  snapshot back hop %d: %d FFs %s pads %s m9k %s", e["hop"], e["ffs"], e["labs"], e["pads"], e["m9k"])

    # G. TX drivers one FF stage deeper: the M9K tiles behind the (22-24, 61-63) FFs, and their write side
    log.info("== G. TX driver FFs -> M9K tiles (2 hops) and write-side sources")
    drv = [io[p]["drv"] for p in TX_PADS]
    bt = back(N, drv, 3)
    tx_tiles = collections.defaultdict(set)
    for h, e in enumerate(bt):
        for x in e["m9k"]:
            t = m9k_tile(x)
            if t:
                tx_tiles[(t[0], t[1])].add((h, t[2]))
        log.info("[V]  TX back hop %d: %d FFs %s; m9k tiles %s; pads %s", h, len(e["ffs"]), labs(e["ffs"])[:5], sorted({m9k_tile(x)[:2] for x in e["m9k"] if m9k_tile(x)}), e["pads"])
    G = dict(tiles={str(k): sorted(v) for k, v in tx_tiles.items()}, write_side={})

    def tile_info(k, dhops=8):
        m = m9k.get(k)
        if m is None:
            return None
        info = dict(cls=m.get("cls"), sdp=m.get("sdp"), A=m.get("A"), W=m.get("W"), n_data=len([s for s in (m.get("data") or []) if s]),
                    n_addr=len([s for s in (m.get("addr") or []) if s]), n_raddr=len([s for s in (m.get("raddr") or []) if s]), we=m.get("we"),
                    content_set=_nset(m.get("content")))
        dsig = [s.lstrip("!") for s in (m.get("data") or []) if s and s not in ST.CV]
        info["data_sig"] = dsig[:12]
        bd = back(N, dsig, dhops)
        info["data_back"] = []
        for h, e in enumerate(bd):
            rf = sorted({RF[f][0] for f in e["ffs"] if f in RF})
            info["data_back"].append(dict(hop=h, ffs=len(e["ffs"]), labs=labs(e["ffs"])[:4], rf=rf, pads=e["pads"],
                                          m9k=sorted({m9k_tile(x)[:2] for x in e["m9k"] if m9k_tile(x)})))
            if not e["ffs"]:
                break
        for key, hops in (("addr", 3), ("raddr", 3)):
            sig = [s.lstrip("!") for s in (m.get(key) or []) if s and s not in ST.CV]
            if sig:
                b = back(N, sig, hops)
                info[key + "_back"] = [(h, len(e["ffs"]), labs(e["ffs"])[:2], sorted({RF[f][0] for f in e["ffs"] if f in RF}), e["pads"]) for h, e in enumerate(b)]
        if m.get("we") and m["we"] not in ST.CV:
            b = back(N, [m["we"].lstrip("!")], 4)
            info["we_back"] = [(h, len(e["ffs"]), labs(e["ffs"])[:2], sorted({RF[f][0] for f in e["ffs"] if f in RF}), e["pads"]) for h, e in enumerate(b)]
        return info

    for k in sorted(tx_tiles):
        info = tile_info(k)
        G["write_side"][str(k)] = info
        if info:
            log.info("[V]  TX tile %s %s A=%s W=%s data %d addr %d raddr %d we %s set-words %d", k, info["cls"], info["A"], info["W"], info["n_data"], info["n_addr"], info["n_raddr"], info["we"], info["content_set"])
            for e in info["data_back"]:
                log.info("[V]    data back hop %d: %d FFs %s RF %s pads %s m9k %s", e["hop"], e["ffs"], e["labs"], e["rf"], e["pads"], e["m9k"])
            for key in ("addr_back", "raddr_back", "we_back"):
                if key in info:
                    log.info("[V]    %s: %s", key, info[key])
    R["G_tx_tiles"] = G

    # H. the FX3-input M9K (7,46): write side and where its outputs go
    log.info("== H. FX3-input M9K tile and its forward path")
    H = {}
    for k in sorted({d for p in FX3_DQ for (kk, d, pin) in fwd(N, fanout, ["pad_" + p], ff_hops=3)["sinks"] if kk == "m9k"}):
        info = tile_info(k, dhops=3)
        outs = [f"m9k_{k[0]}_{k[1]}_o[{i}]" for i in range(36) if f"m9k_{k[0]}_{k[1]}_o[{i}]" in fanout]
        w = fwd(N, fanout, outs, ff_hops=4)
        H[str(k)] = dict(info=info, outputs=len(outs), ffs_by_hop={h: len(v) for h, v in w["ffs"].items()}, hop1_labs=labs(w["ffs"].get(1, []))[:6],
                         sinks={f"{kk}:{d}:{p}": v for (kk, d, p), v in w["sinks"].items()}, lut_labs=labs(w["luts"])[:8], capped=w["capped"],
                         reaches_tx_ffs=sorted(set(sum(w["ffs"].values(), [])) & set(sum((e["ffs"] for e in bt), []))))
        log.info("[V] tile %s %s A=%s W=%s data %d addr %d we %s; addr_back %s; we_back %s", k, info["cls"], info["A"], info["W"], info["n_data"], info["n_addr"], info["we"], info.get("addr_back"), info.get("we_back"))
        log.info("[V]  outputs %d forward: FFs by hop %s hop-1 LABs %s; sinks %s; LUT LABs %s; reaches TX-driver cone FFs %s%s", len(outs), H[str(k)]["ffs_by_hop"], H[str(k)]["hop1_labs"],
                 H[str(k)]["sinks"] or "none", H[str(k)]["lut_labs"], H[str(k)]["reaches_tx_ffs"][:8] or "none", " CAPPED" if w["capped"] else "")
    R["H_fx3_m9k"] = H

    # I. reg-3-addressed tiles (36,57..62) and the received-ID source tile (36,65)
    log.info("== I. tiles read-addressed by reg 3, and the received-ID source")
    I = {}
    for k in [(36, y) for y in range(57, 63)] + [(36, 65)]:
        info = tile_info(k, dhops=3)
        if info is None:
            continue
        outs = [f"m9k_{k[0]}_{k[1]}_o[{i}]" for i in range(36) if f"m9k_{k[0]}_{k[1]}_o[{i}]" in fanout]
        w = fwd(N, fanout, outs, ff_hops=2)
        I[str(k)] = dict(info={kk: v for kk, v in info.items() if kk != "data_back"}, data_back=info["data_back"][:3], outputs=len(outs),
                         ffs_by_hop={h: len(v) for h, v in w["ffs"].items()}, hop1_labs=labs(w["ffs"].get(1, []))[:5], sinks={f"{kk}:{d}:{p}": v for (kk, d, p), v in w["sinks"].items()})
        log.info("[V] tile %s %s A=%s W=%s data %d addr %d raddr %d we %s set-words %d; raddr_back %s; data back %s; outputs %d -> FFs by hop %s @%s sinks %s",
                 k, info["cls"], info["A"], info["W"], info["n_data"], info["n_addr"], info["n_raddr"], info["we"], info["content_set"], info.get("raddr_back"),
                 [(e["hop"], e["ffs"], e["labs"][:2], e["rf"], e["pads"]) for e in info["data_back"][:3]], len(outs), I[str(k)]["ffs_by_hop"], I[str(k)]["hop1_labs"], I[str(k)]["sinks"] or "none")
    R["I_reg3_tiles"] = I
    src = sorted({l for x in other if x in N.ff for l in N.comb_leaves(N.ff[x]["d"]) if l not in RF})
    log.info("[V] received-ID D-cone non-RF leaves: %s", src)
    for x in src[:3]:
        if x in N.ff:
            r = N.red(N.ff[x]["d"]) if N.ff[x]["d"] in N.lut else None
            log.info("[V]  %s ena=%s sclr=%s d-support %s", x, N.ff[x].get("ena"), N.ff[x].get("sclr"), r[0] if r else N.ff[x]["d"])
    bs = back(N, src, 6)
    for h, e in enumerate(bs):
        log.info("[V]  received-ID source back hop %d: %d FFs %s; pads %s; m9k %s; other %s", h, len(e["ffs"]), labs(e["ffs"])[:6], e["pads"], sorted({m9k_tile(x)[:2] for x in e["m9k"] if m9k_tile(x)}), e["other"][:4])
    R["I_received_id_source"] = dict(leaves=src, back=bs)
    ex = other[0]
    r = N.red(N.ff[ex]["d"])
    log.info("[V] example received-ID FF %s D = f%s tt=%s ena=%s", ex, r[0], "".join(map(str, r[1])), N.ff[ex].get("ena"))

    # J. the MAC the match flag reaches
    log.info("== J. MAC (43,84) fed by the match cone")
    J2 = {}
    for mac in nl.mac:
        if (mac["x"], mac["y"]) != (43, 84):
            continue
        sa = [s.lstrip("!") for s in mac["a"] if s and s not in ST.CV]
        sb = [s.lstrip("!") for s in mac["b"] if s and s not in ST.CV]
        ba, bb = back(N, sa, 2), back(N, sb, 2)
        outs = [s for s in fanout if s.startswith("mac_43_84_r[")]
        w = fwd(N, fanout, outs, ff_hops=3)
        J2 = dict(a=len(sa), b=len(sb), a_back=[(h, len(e["ffs"]), labs(e["ffs"])[:3], sorted({RF[f][0] for f in e["ffs"] if f in RF})) for h, e in enumerate(ba)],
                  b_back=[(h, len(e["ffs"]), labs(e["ffs"])[:3], sorted({RF[f][0] for f in e["ffs"] if f in RF})) for h, e in enumerate(bb)],
                  outputs=len(outs), out_ffs_by_hop={h: len(v) for h, v in w["ffs"].items()}, out_hop1_labs=labs(w["ffs"].get(1, []))[:5],
                  out_sinks={f"{kk}:{d}:{p}": v for (kk, d, p), v in w["sinks"].items()})
        log.info("[V] MAC(43,84) a %d bits back %s; b %d bits back %s; outputs %d -> FFs by hop %s @%s sinks %s", len(sa), J2["a_back"], len(sb), J2["b_back"], len(outs), J2["out_ffs_by_hop"], J2["out_hop1_labs"], J2["out_sinks"] or "none")
    R["J_mac"] = J2

    # K. cell-level detail of the two candidate entry structures: TX RAMs (23,62)/(23,63) and the FX3-input RAM (7,46)
    log.info("== K. cell detail: TX RAM write/read ports, FX3-input RAM and its serialiser")

    def ffdet(f):
        F = N.ff[f]
        r = N.red(F["d"]) if F["d"] in N.lut else None
        sup = r[0] if r else [F["d"]]
        return dict(ena=F.get("ena"), sclr=F.get("sclr"), sload=F.get("sload"), asdata=F.get("asdata"), clk=F.get("clk"),
                    d_support=sup, carry=any(s.startswith("co_") for s in N.comb_leaves(F["d"])), rf=RF.get(f))

    def port_detail(k, key):
        m = m9k[k]
        sig = [s for s in (m.get(key) or []) if s]
        out = []
        for s in sig:
            s0 = s.lstrip("!")
            if s0 in ST.CV:
                out.append((s, "const"))
            elif s0 in N.ff:
                d = ffdet(s0)
                out.append((s, "ff", d["ena"], d["sclr"], d["d_support"][:6], "carry" if d["carry"] else "", d["rf"]))
            elif s0 in N.lut:
                r = N.red(s0)
                out.append((s, "lut", r[0][:8] if r else None))
            else:
                out.append((s, "other"))
        return out

    K = {}
    for k in ((23, 62), (23, 63), (7, 46)):
        m = m9k[k]
        K[str(k)] = {}
        log.info("[V] tile %s: cls %s sdp %s A %s W %s out_idx %s ctl %s", k, m.get("cls"), m.get("sdp"), m.get("A"), m.get("W"), m.get("out_idx"), m.get("ctl"))
        for key in ("data", "addr", "raddr", "we", "be", "ce", "clk"):
            v = m.get(key)
            if v is None:
                continue
            if isinstance(v, list):
                det = port_detail(k, key)
                K[str(k)][key] = det
                distinct = sorted({s.lstrip("!") for s in v if s and s.lstrip("!") not in ST.CV})
                log.info("[V]  %s: %d signals, %d distinct non-const; %s", key, len(v), len(distinct), det[:40])
            else:
                s0 = str(v).lstrip("!")
                r = N.red(s0) if s0 in N.lut else None
                K[str(k)][key] = (v, r[0] if r else None, "".join(map(str, r[1])) if r else None)
                log.info("[V]  %s: %s support %s tt %s leaves %s", key, v, r[0] if r else "-", "".join(map(str, r[1])) if r else "-", sorted(N.comb_leaves(s0))[:10] if s0 in N.lut else "-")

    for lab in ((4, 46), (8, 46), (6, 46), (34, 61), (26, 63), (15, 62)):
        ffs = sorted(f for f in N.ff if xy(f) == lab)
        luts = sorted(l for l in N.lut if xy(l) == lab)
        rows = []
        for f in ffs:
            d = ffdet(f)
            rows.append((f, d["ena"], d["sclr"], d["d_support"][:5], "carry" if d["carry"] else "", d["rf"], [c for c in N.cons.get(f, [])][:4]))
        K[f"lab{lab}"] = rows
        log.info("[V] LAB %s: %d FFs %d LUTs", lab, len(ffs), len(luts))
        for r in rows:
            log.info("[V]   %s ena=%s sclr=%s d=%s %s rf=%s -> %s", *r)
    io_ac10 = io.get("AC10")
    if io_ac10:
        r = N.red(io_ac10["drv"]) if io_ac10["drv"] in N.lut else None
        log.info("[V] pad AC10 drv %s support %s; AC11 drv %s support %s", io_ac10["drv"], r[0] if r else io_ac10["drv"],
                 io["AC11"]["drv"], (N.red(io["AC11"]["drv"]) or ([io["AC11"]["drv"]],))[0] if io["AC11"]["drv"] in N.lut else io["AC11"]["drv"])
    R["K_detail"] = K

    # L. DATA provenance (D/asdata edges only -- the enable-edge walk pulls the SPI address decoder into every cone)
    log.info("== L. data-only provenance walks")

    def back_d(sigs, hops, stop=()):
        seen, cur, out = set(), set(sigs), []
        for _ in range(hops):
            leaves = set()
            for s in cur:
                leaves |= N.comb_leaves(s)
            ffs = {x for x in leaves if x in N.ff} - seen
            non = {x for x in leaves if x not in N.ff}
            out.append(dict(ffs=sorted(ffs), pads=sorted(x[4:] for x in non if x.startswith("pad_")),
                            m9k=sorted({m9k_tile(x)[:2] for x in non if m9k_tile(x)}), rf=sorted({RF[f][0] for f in ffs if f in RF}),
                            rf_ffs=sorted(f for f in ffs if f in RF)))
            seen |= ffs
            cur = {N.ff[x][k] for x in ffs if x not in stop for k in ("d", "asdata") if N.ff[x].get(k)}
            if not cur:
                break
        return out

    def show(tag, b):
        for h, e in enumerate(b):
            log.info("[V]  %s D-hop %d: %d FFs %s; RF %s %s; pads %s; m9k %s", tag, h, len(e["ffs"]), labs(e["ffs"])[:5], e["rf"], e["rf_ffs"][:6], e["pads"], e["m9k"])

    L = {}
    for k in ((23, 62), (23, 63)):
        dsig = sorted({s.lstrip("!") for s in (m9k[k].get("data") or []) if s and s.lstrip("!") not in ST.CV})
        L[f"tx_data{k}"] = back_d(dsig, 12)
        show(f"TX RAM {k} data({len(dsig)})", L[f"tx_data{k}"])
        asig = sorted({s.lstrip("!") for s in (m9k[k].get("addr") or []) if s and s.lstrip("!") not in ST.CV})
        rsig = sorted({s.lstrip("!") for s in (m9k[k].get("raddr") or []) if s and s.lstrip("!") not in ST.CV})
        if k == (23, 62):
            L["tx_addr"] = back_d(asig, 4)
            show("TX RAM write addr", L["tx_addr"])
            L["tx_raddr"] = back_d(rsig, 4)
            show("TX RAM read addr", L["tx_raddr"])
            for f in asig + rsig + ["ff_27_63_6", "ff_26_72_2", "ff_87_61_2"]:
                F = N.ff[f]
                r = N.red(F["d"]) if F["d"] in N.lut else None
                log.info("[V]   %s ena=%s sclr=%s D=f%s tt=%s", f, F.get("ena"), F.get("sclr"), r[0] if r else [F["d"]], "".join(map(str, r[1])) if r else "-")
    # pad-mux stage: non-RAM input
    stage = sorted({x for p in TX_PADS for x in N.comb_leaves(io[p]["drv"]) if x in N.ff})
    sel = [x for x in stage if sum(1 for p in TX_PADS if x in N.comb_leaves(io[p]["drv"])) == len(TX_PADS)]
    per = [x for x in stage if x not in sel]
    log.info("[V] TX pad mux: select FFs %s (RF %s); per-pad stage FFs %d", sel, [RF.get(s) for s in sel], len(per))
    for s in sel:
        F = N.ff[s]
        r = N.red(F["d"]) if F["d"] in N.lut else None
        log.info("[V]   select %s ena=%s D=f%s", s, F.get("ena"), r[0] if r else [F["d"]])
    L["sel_back"] = back_d(sel, 4)
    show("TX mux select", L["sel_back"])
    ram_out = {f for f in per if any(m9k_tile(x) for x in N.comb_leaves(N.ff[f]["d"]))}
    non_ram = sorted(set(per) - ram_out)
    log.info("[V]  per-pad stage: %d FFs read the RAMs directly, %d do not: %s", len(ram_out), len(non_ram), non_ram[:12])
    for f in non_ram[:3]:
        F = N.ff[f]
        r = N.red(F["d"]) if F["d"] in N.lut else None
        log.info("[V]   %s ena=%s sclr=%s D=f%s", f, F.get("ena"), F.get("sclr"), r[0] if r else [F["d"]])
    L["nonram_back"] = back_d(non_ram, 6)
    show("TX non-RAM stage", L["nonram_back"])
    # example pad driver function
    p0 = TX_PADS[0]
    r = N.red(io[p0]["drv"])
    log.info("[V]  pad %s driver %s = f%s tt=%s", p0, io[p0]["drv"], r[0], "".join(map(str, r[1])))
    # received-ID source, data only
    rid = sorted(f"ff_31_65_{i}" for i in range(5, 16) if f"ff_31_65_{i}" in N.ff)
    L["rid_back"] = back_d(rid, 8)
    show("received-ID (31,65)", L["rid_back"])
    F = N.ff["ff_31_65_5"]
    r = N.red(F["d"])
    log.info("[V]  ff_31_65_5 ena=%s D=f%s tt=%s; ena cone leaves %s", F.get("ena"), r[0], "".join(map(str, r[1])), sorted(N.comb_leaves(F["ena"]))[:10])
    # FX3 FIFO serialiser tick
    tick = "ff_4_45_8"
    F = N.ff[tick]
    r = N.red(F["d"]) if F["d"] in N.lut else None
    log.info("[V] serialiser tick %s ena=%s sclr=%s D=f%s tt=%s", tick, F.get("ena"), F.get("sclr"), r[0] if r else [F["d"]], "".join(map(str, r[1])) if r else "-")
    L["tick_back"] = back_d([tick], 3)
    show("tick", L["tick_back"])
    lab45 = sorted(f for f in N.ff if xy(f) == (4, 45))
    for f in lab45:
        Fq = N.ff[f]
        rq = N.red(Fq["d"]) if Fq["d"] in N.lut else None
        log.info("[V]   (4,45) %s ena=%s sclr=%s D=f%s tt=%s carry=%s", f, Fq.get("ena"), Fq.get("sclr"), rq[0] if rq else [Fq["d"]], "".join(map(str, rq[1])) if rq else "-",
                 any(s.startswith("co_") for s in N.comb_leaves(Fq["d"])))
    # the FIFO read-side counter enable and the AC10 bit-select counter
    for f in ("lc_6_46_5", "lc_6_46_3", "lc_4_46_0", "lc_4_46_1", "lc_4_46_11"):
        rq = N.red(f)
        log.info("[V]   %s = f%s tt=%s", f, rq[0], "".join(map(str, rq[1])))
    R["L_data_only"] = L

    # M. closers: AC10 baud divider, deserialiser payload consumers, per-pad lane decode, TX-RAM write trigger
    log.info("== M. closers")
    import itertools
    M = {}
    # (a) divider at (3,45) feeding the serialiser tick: unique terminal state of lc_4_45_3 over its FF support
    div = sorted(f for f in N.ff if xy(f) == (3, 45))
    sup = sorted(N.comb_leaves("lc_4_45_3"))
    log.info("[V] tick LUT lc_4_45_3 leaves %s; (3,45) FFs %d: ena %s sclr %s carry %s", sup, len(div), {N.ff[f].get("ena") for f in div}, {N.ff[f].get("sclr") for f in div},
             sum(1 for f in div if any(s.startswith("co_") for s in N.comb_leaves(N.ff[f]["d"]))))
    if sup and len(sup) <= 16 and all(s in N.ff for s in sup):
        sols = [b for b in itertools.product((0, 1), repeat=len(sup)) if N.ev("lc_4_45_3", dict(zip(sup, b)))]
        log.info("[V]  lc_4_45_3 satisfying assignments: %d%s", len(sols), (" state " + str(dict(zip(sup, sols[0]))) if len(sols) == 1 else ""))
        M["tick_lut"] = dict(support=sup, n_sat=len(sols), state=(dict(zip(sup, sols[0])) if len(sols) == 1 else None))
    # is (3,45) a counter? D cone of each, sclr/ena, self-reference
    for f in div[:16]:
        Fq = N.ff[f]
        rq = N.red(Fq["d"]) if Fq["d"] in N.lut else None
        log.info("[V]   %s ena=%s sclr=%s D=f%s", f, Fq.get("ena"), Fq.get("sclr"), (rq[0] if rq else [Fq["d"]])[:6])
    # (b) deserialiser (31,65) consumers other than the received-ID register
    rid = [f"ff_31_65_{i}" for i in range(5, 16) if f"ff_31_65_{i}" in N.ff]
    idreg = set(other)
    w = fwd(N, fanout, rid, ff_hops=3)
    hop1 = [f for f in w["ffs"].get(1, []) if f not in idreg and f not in rid]
    snap = {x for x in J.get("readback_other_sources", {}) if x in N.ff}
    allf = set(sum(w["ffs"].values(), []))
    log.info("[V] deserialiser (31,65) forward: FFs by hop %s; hop-1 non-ID FFs %d @%s %s; sinks %s; reaches snapshot FFs %d; reaches FX3 LAB (17,53) FFs %d; reaches (37,88)/(37,89) %d",
             {h: len(v) for h, v in w["ffs"].items()}, len(hop1), labs(hop1)[:6], hop1[:10], dict(w["sinks"]) or "none", len(allf & snap),
             sum(1 for f in allf if xy(f) == (17, 53)), sum(1 for f in allf if xy(f) in ((37, 88), (37, 89))))
    M["deser_fwd"] = dict(ffs_by_hop={h: len(v) for h, v in w["ffs"].items()}, hop1_non_id=hop1, sinks={f"{k}:{d}:{p}": v for (k, d, p), v in w["sinks"].items()},
                          snapshot_hits=sorted(allf & snap), lab_17_53=sum(1 for f in allf if xy(f) == (17, 53)))
    for f in hop1[:6]:
        Fq = N.ff[f]
        rq = N.red(Fq["d"]) if Fq["d"] in N.lut else None
        log.info("[V]   %s ena=%s sclr=%s D=f%s rf=%s", f, Fq.get("ena"), Fq.get("sclr"), (rq[0] if rq else [Fq["d"]])[:6], RF.get(f))
    # (c) per-pad lane decode for E25: the two per-pad sources one level down
    for f in ("ff_24_63_11", "ff_24_63_0", "ff_24_63_3"):
        Fq = N.ff[f]
        rq = N.red(Fq["d"]) if Fq["d"] in N.lut else None
        lv = sorted(N.comb_leaves(Fq["d"]))
        log.info("[V] per-pad %s ena=%s sclr=%s D=f%s tt=%s; leaves %s", f, Fq.get("ena"), Fq.get("sclr"), rq[0] if rq else [Fq["d"]], "".join(map(str, rq[1])) if rq else "-", lv[:10])
        for g in (rq[0] if rq else []):
            if g in N.ff:
                G2 = N.ff[g]
                r2 = N.red(G2["d"]) if G2["d"] in N.lut else None
                log.info("[V]     %s ena=%s D=f%s", g, G2.get("ena"), (r2[0] if r2 else [G2["d"]])[:8])
    # (d) TX-RAM write trigger: do the reg-8/9 write enables sit in the cone of the RAM we / write-pointer enable?
    reg_we = {"0x8": [e["enable"] for e in J["register_map"]["0x8"]], "0x9": [e["enable"] for e in J["register_map"]["0x9"]]}
    for root in ("lc_15_62_13", "lc_34_61_2", "ff_26_72_2", "ff_31_73_4", "lc_28_72_3"):
        b = back(N, [root], 6)
        hits = {}
        for h, e in enumerate(b):
            for adr, ens in reg_we.items():
                for en in ens:
                    if en in e["other"] or any(en in N.comb_leaves(x) for x in e["other"][:0]):
                        hits.setdefault(adr, []).append(h)
            # the write-enable nets are LUT outputs; comb_leaves stops at FFs, so look for the RF FFs of 8/9 and the chain instead
            rf = sorted({RF[f][0] for f in e["ffs"] if f in RF})
            if rf:
                hits.setdefault("rf@hop" + str(h), rf)
        log.info("[V] write trigger %s: RF regs per hop %s; FFs per hop %s", root, {k: v for k, v in hits.items()}, [(h, len(e["ffs"]), labs(e["ffs"])[:3]) for h, e in enumerate(b)])
    # which FFs of (38,83) sit on the TX data path
    tx38 = sorted(set(sum((e["ffs"] for e in L["tx_data(23, 62)"]), [])) | set(sum((e["ffs"] for e in L["tx_data(23, 63)"]), [])))
    tx38 = [f for f in tx38 if xy(f) in ((38, 83), (37, 83))]
    for f in tx38:
        Fq = N.ff[f]
        rq = N.red(Fq["d"]) if Fq["d"] in N.lut else None
        log.info("[V] TX-path SPI-area FF %s ena=%s D=f%s", f, Fq.get("ena"), (rq[0] if rq else [Fq["d"]])[:6])
    R["M_closers"] = M

    # N. the 56-byte uplink record: regs 0x44..0x7B (m1400 FUN_0001698a, #177) -- where do those 448 FFs go?
    log.info("== N. uplink record registers 0x44..0x7B forward")
    rec = [f"0x{a:x}" for a in range(0x44, 0x7c)]
    recffs = collections.defaultdict(list)
    for adr in rec:
        for b, n in sorted(byreg.get(adr, [])):
            recffs[N.ff[n].get("ena")].append(n)
    log.info("[V] %d registers, %d FFs in %d enable groups; LABs %s", len(rec), sum(len(v) for v in recffs.values()), len(recffs),
             labs(sum(recffs.values(), []))[:12])
    allrec = sum(recffs.values(), [])
    w = fwd(N, fanout, allrec, ff_hops=4, cap=20000)
    direct = collections.Counter()
    for n in allrec:
        for c in N.cons.get(n, []):
            direct["ff." + c.split(".")[1] if c.startswith("ff_") else ("cmp" if c in heq_luts else "lut")] += 1
    log.info("[V] direct consumers %s; forward FFs by hop %s; hop-1 LABs %s; LUT LABs %s; sinks %s%s", dict(direct), {h: len(v) for h, v in w["ffs"].items()},
             labs(w["ffs"].get(1, []))[:10], labs(w["luts"])[:10], dict(w["sinks"]) or "none", " CAPPED" if w["capped"] else "")
    # per register: hop-1 FF count and LAB, to see whether the record is read as a block (one structure) or per byte
    per = {}
    for adr in rec:
        ffs = [n for _b, n in sorted(byreg.get(adr, []))]
        if not ffs:
            continue
        w1 = fwd(N, fanout, ffs, ff_hops=1, cap=2000)
        per[adr] = dict(ffs=len(ffs), hop1=len(w1["ffs"].get(1, [])), hop1_labs=labs(w1["ffs"].get(1, []))[:3], sinks={f"{k}:{d}:{p}": v for (k, d, p), v in w1["sinks"].items()})
    log.info("[V] per-register hop-1: %s", {a: (v["hop1"], v["hop1_labs"][:2]) for a, v in per.items()})
    # the common consumer: LUTs reading >= 8 record FFs (a mux/packer), and FFs whose D cone holds record bits from >= 2 registers
    lutcnt = collections.Counter()
    for n in allrec:
        for c in N.cons.get(n, []):
            if c in N.lut:
                lutcnt[c] += 1
    big = [(l, k) for l, k in lutcnt.most_common(12)]
    log.info("[V] LUTs reading the most record bits: %s", big)
    ffmix = {}
    for f in w["ffs"].get(1, [])[:4000]:
        lv = N.comb_leaves(N.ff[f]["d"])
        regs = sorted({RF[x][0] for x in lv if x in RF and RF[x][0] in rec})
        if len(regs) >= 2:
            ffmix[f] = regs
    log.info("[V] hop-1 FFs whose D cone mixes >= 2 record registers: %d, e.g. %s", len(ffmix), list(ffmix.items())[:6])
    # does the record cone meet the TX RAM write pipeline / the TX pad stage / the ID regs' cone?
    txpipe = set(sum((e["ffs"] for e in L["tx_data(23, 62)"][:6]), []))
    recall = set(sum(w["ffs"].values(), []))
    log.info("[V] record cone (<=4 hops) meets TX-RAM write pipeline FFs: %d %s; TX pad stage: %d; received-ID reg: %d; (37,88)/(37,89): %d",
             len(recall & txpipe), sorted(recall & txpipe)[:8], len(recall & set(stage)), len(recall & idreg), sum(1 for f in recall if xy(f) in ((37, 88), (37, 89))))
    R["N_record"] = dict(groups={str(k): len(v) for k, v in recffs.items()}, ffs_by_hop={h: len(v) for h, v in w["ffs"].items()}, hop1_labs=labs(w["ffs"].get(1, []))[:10],
                         sinks={f"{k}:{d}:{p}": v for (k, d, p), v in w["sinks"].items()}, per_register=per, big_luts=big, mix=dict(list(ffmix.items())[:40]),
                         meets_tx_pipe=sorted(recall & txpipe))

    # O. UART-transmitter scan over every output pad: serial FF whose D-cone is a bit mux over a byte register
    #    stepped by a bit counter enabled by a tick FF, the tick being the terminal count of a divider counter
    log.info("== O. UART transmitter scan over all output pads")
    tagged = set()
    for line in open(os.path.join(REPO, "boards", "dji-m2001", "pins.tsv"), encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        p = line.rstrip("\n").split("\t")
        if len(p) > 9 and p[9].strip():
            tagged.add(p[0])
    O = {}

    def counter_order(ffs):
        """ripple order guess: sort by the number of same-group FFs in each FF's own D cone (LSB depends on fewest)."""
        s = set(ffs)
        return sorted(ffs, key=lambda f: (len(N.comb_leaves(N.ff[f]["d"]) & s), f))

    for i in nl.ios:
        if i["dir"] == "input" or not i.get("drv"):
            continue
        ball = i["ball"]
        drv = i["drv"]
        f0 = drv if drv in N.ff else None
        if f0 is None:
            r = N.red(drv) if drv in N.lut else None
            if r and len(r[0]) == 1 and r[0][0] in N.ff:
                f0 = r[0][0]
        if f0 is None:
            continue
        lv1 = {x for x in N.comb_leaves(N.ff[f0]["d"]) if x in N.ff}
        lv2 = set(lv1)
        for x in lv1:
            lv2 |= {y for y in N.comb_leaves(N.ff[x]["d"]) if y in N.ff}
        ticks = {N.ff[x].get("ena") for x in lv2 | {f0} if N.ff[x].get("ena") in N.ff}
        best = None
        for t in ticks:
            Ft = N.ff[t]
            sup = sorted(N.comb_leaves(Ft["d"]))
            supff = [s for s in sup if s in N.ff and s != t]
            if 6 <= len(supff) <= 16 and len(sup) == len(supff) + (1 if t in sup else 0):
                sols = [b for b in itertools.product((0, 1), repeat=len(supff)) if N.ev(Ft["d"], dict(zip(supff, b)) | {t: 0})]
                if len(sols) == 1:
                    order = counter_order(supff)
                    val = sum(dict(zip(supff, sols[0]))[f] << k for k, f in enumerate(order))
                    cand = dict(tick=t, divider_ffs=len(supff), lab=labs(supff)[:2], state=val, clk=Ft.get("clk"), sclr=sorted({N.ff[f].get("sclr") for f in supff}, key=str))
                    if best is None or cand["divider_ffs"] > best["divider_ffs"]:
                        best = cand
        m9ks = {m9k_tile(x)[:2] for x in N.comb_leaves(N.ff[f0]["d"]) if m9k_tile(x)}
        for x in lv1:
            m9ks |= {m9k_tile(y)[:2] for y in N.comb_leaves(N.ff[x]["d"]) if m9k_tile(y)}
        if best or (len(lv2) >= 6 and m9ks):
            O[ball] = dict(driver_ff=f0, clk=N.ff[f0].get("clk"), ffs_2hops=len(lv2), labs=labs(lv2)[:3], m9k=sorted(m9ks), divider=best, tagged=ball in tagged)
            log.info("[V] pad %s%s: serial FF %s clk %s; %d FFs within 2 D-hops @%s; m9k %s; divider %s", ball, "" if ball in tagged else " (untagged)", f0, N.ff[f0].get("clk"),
                     len(lv2), labs(lv2)[:3], sorted(m9ks), best)
    R["O_uart_scan"] = O

    # P. U22: periodic frame pulse or status bit?  driver ff_37_83_8 and its D cone, plus the other untagged outputs' drivers
    log.info("== P. U22 and the other untagged output pads")
    for ball in sorted({i["ball"] for i in nl.ios if i["dir"] != "input" and i.get("drv")} - tagged):
        drv = io[ball]["drv"]
        f0 = drv if drv in N.ff else None
        r0 = N.red(drv) if drv in N.lut else None
        src = f0 or (r0[0] if r0 else drv)
        detail = ""
        if f0:
            Fq = N.ff[f0]
            rq = N.red(Fq["d"]) if Fq["d"] in N.lut else None
            lv = sorted(N.comb_leaves(Fq["d"]))
            detail = f"D=f{(rq[0] if rq else [Fq['d']])[:6]} ena={Fq.get('ena')} sclr={Fq.get('sclr')} leaves-RF={sorted({RF[x][0] for x in lv if x in RF})} chain={sorted(set(lv) & set(J['chain']['ffs']))}"
        log.info("[V] untagged out %s drv %s %s", ball, src, detail)
    u = N.ff.get("ff_37_83_8")
    if u:
        b = back_d(["ff_37_83_8"], 4)
        show("U22 src", b)
    R["P_untagged"] = sorted({i["ball"] for i in nl.ios if i["dir"] != "input" and i.get("drv")} - tagged)

    # Q. the M9K tiles the TX-RAM data pipeline reads at depth: their write side vs the uplink-record cone
    log.info("== Q. TX pipeline source tiles (23,55) (23,58) (23,61) (36,54) (36,55): write side")
    recall4 = recall
    w8 = fwd(N, fanout, allrec, ff_hops=8, cap=60000)
    recall8 = set(sum(w8["ffs"].values(), []))
    rec_m9k = sorted({str(d) for (k, d, p) in w8["sinks"] if k == "m9k"})
    log.info("[V] record cone <=8 hops: %d FFs%s; M9K sinks %s", len(recall8), " CAPPED" if w8["capped"] else "", rec_m9k[:40])
    Q = {}
    for k in ((23, 55), (23, 58), (23, 61), (36, 54), (36, 55)):
        m = m9k.get(k)
        if m is None:
            continue
        dsig = sorted({s.lstrip("!") for s in (m.get("data") or []) if s and s.lstrip("!") not in ST.CV})
        b = back_d(dsig, 8)
        meet = [(h, len(set(e["ffs"]) & recall8)) for h, e in enumerate(b)]
        Q[str(k)] = dict(cls=m.get("cls"), A=m.get("A"), W=m.get("W"), n_data=len(dsig), we=m.get("we"), back=b, meets_record=meet)
        log.info("[V] tile %s cls %s A %s W %s data %d we %s; data D-back: %s; overlap with record cone per hop %s", k, m.get("cls"), m.get("A"), m.get("W"), len(dsig), m.get("we"),
                 [(h, len(e["ffs"]), labs(e["ffs"])[:3], e["rf"], e["m9k"]) for h, e in enumerate(b)], meet)
    R["Q_tx_source_tiles"] = Q

    # R. SPI-address decode of the TX pipeline capture enables
    log.info("== R. which SPI addresses gate the TX pipeline capture FFs")
    addr = J["address_register"]["ffs"]
    aset = set(addr)
    pipe = set()
    for e in L["tx_data(23, 62)"][:8] + L["tx_data(23, 63)"][:8]:
        pipe |= set(e["ffs"])
    ens = collections.Counter(N.ff[f].get("ena") for f in pipe if N.ff[f].get("ena"))
    Rr = {}
    for en, cnt in ens.most_common(20):
        if not N.has(en, aset):
            Rr[en] = dict(ffs=cnt, addresses="not address-decoded", leaves=sorted(N.comb_leaves(en))[:8])
            log.info("[V] ena %s (%d pipeline FFs): not address-decoded; leaves %s", en, cnt, sorted(N.comb_leaves(en))[:8])
            continue
        op, sat = ST.decode(N, en, addr, aset)
        if sat is None:
            Rr[en] = dict(ffs=cnt, addresses="undecodable (wide)")
            log.info("[V] ena %s (%d pipeline FFs): wide, undecoded", en, cnt)
            continue
        adrs = sorted({a for v in sat.values() for a in v})
        Rr[en] = dict(ffs=cnt, addresses=[hex(a) for a in adrs][:80], opaque=op)
        log.info("[V] ena %s (%d pipeline FFs): addresses %s (%d) opaque terms %s", en, cnt, [hex(a) for a in adrs][:40], len(adrs), op)
    R["R_pipe_enables"] = Rr

    # S. divider periods by simulation (counter FFs + terminal LUT); AC10's (3,45) first, then every output pad
    log.info("== S. divider periods by simulation")

    def sim_period(ffs, limit=70000):
        """step the sub-circuit of `ffs` from all-zero with every other input held 0 and enables 1; period = first return to 0 after a change."""
        env = {f: 0 for f in ffs}

        def val(sig, e):
            if sig in ST.CV:
                return ST.CV[sig]
            if sig in e:
                return e[sig]
            if sig in N.lut:
                r = N.red(sig)
                if r is None:
                    return 0
                i = 0
                for k, x in enumerate(r[0]):
                    i |= val(x, e) << k
                return r[1][i]
            return 0
        moved = False
        for step in range(1, limit):
            nxt = {}
            for f in ffs:
                F = N.ff[f]
                en = val(F["ena"], env) if F.get("ena") else 1
                en = (1 - en) if F.get("ena_inv") else en
                v = env[f]
                if en:
                    v = val(F["d"], env)
                if F.get("sclr") and val(F["sclr"], env):
                    v = 0
                nxt[f] = v
            env = nxt
            zero = all(v == 0 for v in env.values())
            if not zero:
                moved = True
            elif moved:
                return step
            elif step > 4:
                return None      # never leaves zero with external inputs held 0: not a free-running divider
        return None

    S = {}
    p = sim_period(div)
    S["ac10_divider_period"] = p
    log.info("[V] AC10 divider (3,45): simulated period %s clocks (sclr by lc_4_45_3)", p)
    # bit-select counter of the serialiser: ff_4_46_4..7 stepped by the tick
    bits = [f"ff_4_46_{i}" for i in (4, 5, 6, 7)]
    log.info("[V] serialiser bit counter %s: ena %s; tt lc_4_46_11 (terminal?) over %s", bits, {N.ff[f].get("ena") for f in bits}, N.red("lc_4_46_11")[0])
    # generic: every output pad, ticks among enables within 2 D-hops of the driver FF
    for i in nl.ios:
        if i["dir"] == "input" or not i.get("drv"):
            continue
        ball, drv = i["ball"], i["drv"]
        f0 = drv if drv in N.ff else None
        if f0 is None:
            r = N.red(drv) if drv in N.lut else None
            if r and len(r[0]) == 1 and r[0][0] in N.ff:
                f0 = r[0][0]
        if f0 is None:
            continue
        lv1 = {x for x in N.comb_leaves(N.ff[f0]["d"]) if x in N.ff}
        lv2 = set(lv1)
        for x in lv1:
            lv2 |= {y for y in N.comb_leaves(N.ff[x]["d"]) if y in N.ff}
        ticks = {N.ff[x].get("ena") for x in lv2 | {f0} if N.ff[x].get("ena")}
        found = []
        for t in ticks:
            if t in N.ff:
                sup = [s for s in N.comb_leaves(N.ff[t]["d"]) if s in N.ff and s != t]
            else:
                sup = [s for s in N.comb_leaves(t) if s in N.ff]
            if 4 <= len(sup) <= 20 and len({xy(s) for s in sup}) <= 2:
                per_ = sim_period(sup)
                if per_ and per_ > 4:
                    found.append(dict(tick=t, divider_ffs=len(sup), lab=labs(sup)[:2], period=per_, clk=N.ff[sup[0]].get("clk")))
        if found:
            S[ball] = dict(driver_ff=f0, ffs_2hops=len(lv2), tagged=ball in tagged, dividers=found)
            log.info("[V] pad %s%s: serial FF %s, %d FFs in 2 D-hops; dividers %s", ball, "" if ball in tagged else " (untagged)", f0, len(lv2), found)
    R["S_dividers"] = S

    # T. frame-sync candidates AC8 (= ff_40_88_10, TX gate) and AB12 (ff_40_88_11): generating logic
    log.info("== T. AC8 / AB12 generating logic, and the (37,88)/(37,89) convergence LAB")
    for f in ("ff_40_88_10", "ff_40_88_11"):
        lv = sorted(N.comb_leaves(N.ff[f]["d"]))
        log.info("[V] %s D leaves %s RF %s", f, lv, {x: RF[x] for x in lv if x in RF})
    for lab in ((38, 86), (38, 88), (39, 86), (40, 88)):
        ffs = sorted(f for f in N.ff if xy(f) == lab)
        rows = []
        for f in ffs:
            Fq = N.ff[f]
            rq = N.red(Fq["d"]) if Fq["d"] in N.lut else None
            rows.append((f, Fq.get("ena"), Fq.get("sclr"), (rq[0] if rq else [Fq["d"]])[:5], RF.get(f), "carry" if any(s.startswith("co_") for s in N.comb_leaves(Fq["d"])) else ""))
        log.info("[V] LAB %s: %s", lab, rows)
    conv = sorted(f for f in N.ff if xy(f) in ((37, 88), (37, 89)))
    rows = []
    for f in conv:
        Fq = N.ff[f]
        rq = N.red(Fq["d"]) if Fq["d"] in N.lut else None
        rows.append((f, Fq.get("ena"), Fq.get("sclr"), (rq[0] if rq else [Fq["d"]])[:5]))
    log.info("[V] convergence LAB (37,88)/(37,89) %d FFs: %s", len(conv), rows[:24])
    wconv = fwd(N, fanout, conv, ff_hops=3)
    log.info("[V]  forward: FFs by hop %s @%s sinks %s", {h: len(v) for h, v in wconv["ffs"].items()}, labs(wconv["ffs"].get(1, []))[:5], dict(wconv["sinks"]) or "none")
    # U. RX payload latch (29,87) forward
    pay = sorted(f for f in N.ff if xy(f) == (29, 87))
    wp = fwd(N, fanout, pay, ff_hops=3)
    log.info("[V] RX payload latch (29,87) %d FFs ena %s sclr %s -> FFs by hop %s @%s; sinks %s; snapshot hits %d; readback slices hit %d",
             len(pay), {N.ff[f].get("ena") for f in pay}, {N.ff[f].get("sclr") for f in pay}, {h: len(v) for h, v in wp["ffs"].items()}, labs(wp["ffs"].get(1, []))[:6],
             dict(wp["sinks"]) or "none", len(set(sum(wp["ffs"].values(), [])) & snap), len(set(sum(wp["ffs"].values(), [])) & set(J.get("readback_slices", []))))
    R["U_payload"] = dict(ffs_by_hop={h: len(v) for h, v in wp["ffs"].items()}, hop1_labs=labs(wp["ffs"].get(1, []))[:8], sinks={f"{k}:{d}:{p}": v for (k, d, p), v in wp["sinks"].items()})

    # V. follow the RX payload through its 1-FF bottleneck to a sink; AC11 neighbourhood; FSM and convergence-LAB leaves
    log.info("== V. payload bottleneck, AC11, FSM leaves")
    for h in (2, 3):
        for f in wp["ffs"].get(h, []):
            Fq = N.ff[f]
            rq = N.red(Fq["d"]) if Fq["d"] in N.lut else None
            log.info("[V] payload hop-%d FF %s ena=%s sclr=%s D=f%s", h, f, Fq.get("ena"), Fq.get("sclr"), (rq[0] if rq else [Fq["d"]])[:8])
            wd = fwd(N, fanout, [f], ff_hops=10, cap=20000)
            pads = sorted({str(d) for (k, d, p) in wd["sinks"] if k == "pad"})
            m9s = sorted({str(d) for (k, d, p) in wd["sinks"] if k == "m9k"})
            log.info("[V]   forward 10 hops: FFs by hop %s; pads %s; m9k %s%s", {hh: len(v) for hh, v in wd["ffs"].items()}, pads, m9s[:12], " CAPPED" if wd["capped"] else "")
            # the first hop at which each pad is reached, by re-walking with increasing ff_hops
            first = {}
            for hh in range(1, 9):
                ws = fwd(N, fanout, [f], ff_hops=hh, cap=20000)
                for (k, d, p) in ws["sinks"]:
                    if k == "pad" and d not in first:
                        first[d] = hh
            log.info("[V]   first FF-hop at which each pad is reached: %s", first)
    # payload hop-1 FFs: are they a shift register (serial) or a latch?
    for f in wp["ffs"].get(1, [])[:6]:
        Fq = N.ff[f]
        rq = N.red(Fq["d"]) if Fq["d"] in N.lut else None
        log.info("[V] payload hop-1 %s ena=%s sclr=%s D=f%s", f, Fq.get("ena"), Fq.get("sclr"), (rq[0] if rq else [Fq["d"]])[:6])
    # AC11
    for lab in ((6, 33), (6, 32), (5, 33)):
        ffs = sorted(f for f in N.ff if xy(f) == lab)
        rows = []
        for f in ffs:
            Fq = N.ff[f]
            rq = N.red(Fq["d"]) if Fq["d"] in N.lut else None
            rows.append((f, Fq.get("ena"), Fq.get("sclr"), (rq[0] if rq else [Fq["d"]])[:5], [m9k_tile(x)[:2] for x in N.comb_leaves(Fq["d"]) if m9k_tile(x)][:2]))
        log.info("[V] AC11 LAB %s: %s", lab, rows)
    b11 = back_d(["ff_6_33_12"], 5)
    show("AC11", b11)
    # FSM (38,86)/(39,86) leaves and the convergence-LAB LUT leaves
    fsm = ["ff_38_86_4", "ff_38_86_5", "ff_39_86_0", "ff_39_86_15"]
    for f in fsm:
        lv = sorted(N.comb_leaves(N.ff[f]["d"]))
        log.info("[V] FSM %s D leaves %s RF %s", f, lv, {x: RF[x] for x in lv if x in RF})
    bf = back_d(fsm, 4)
    show("FSM", bf)
    lv = sorted(N.comb_leaves("lc_37_88_13"))
    log.info("[V] convergence enable lc_37_88_13 leaves %s RF %s", lv, {x: RF[x] for x in lv if x in RF})
    for l in ("lc_37_88_0", "lc_37_88_1", "lc_37_89_5"):
        lv = sorted(N.comb_leaves(l))
        log.info("[V] convergence D %s leaves %s RF %s", l, lv[:12], {x: RF[x] for x in lv if x in RF})

    # W. periods (sclr-agnostic), AC11's source tiles, the descrambled serial bit's consumers, reg-3 table index, carry check
    log.info("== W. closers 2")
    log.info("[V] ff record keys: %s; ff_3_45_1 = %s", sorted(N.ff["ff_3_45_1"].keys()), {k: v for k, v in N.ff["ff_3_45_1"].items() if k != "name"})

    def period_to_terminal(ffs, term, limit=70000):
        """count steps of the FF sub-circuit (other inputs 0, enables honoured, sclr ignored) until LUT `term` first reads 1 after step 0."""
        env = {f: 0 for f in ffs}

        def val(sig, e):
            if sig in ST.CV:
                return ST.CV[sig]
            if sig in e:
                return e[sig]
            if sig in N.lut:
                r = N.red(sig)
                if r is None:
                    return 0
                i = 0
                for k, x in enumerate(r[0]):
                    i |= val(x, e) << k
                return r[1][i]
            return 0
        t0 = val(term, env)
        for step in range(1, limit):
            nxt = {}
            for f in ffs:
                F = N.ff[f]
                en = val(F["ena"], env) if F.get("ena") else 1
                en = (1 - en) if F.get("ena_inv") else en
                nxt[f] = val(F["d"], env) if en else env[f]
            env = nxt
            if val(term, env) and step > 1:
                return step, t0
        return None, t0

    W = {}
    p, t0 = period_to_terminal(div, "lc_4_45_3")
    W["ac10"] = dict(period=p, term_at_zero=t0)
    log.info("[V] AC10 divider (3,45) 16 FFs: terminal lc_4_45_3 first true after %s clocks (value at zero state %s) -> bit period; baud = Fclk / that", p, t0)
    # AC11: tick ff_8_34_4
    t = N.ff["ff_8_34_4"]
    r = N.red(t["d"]) if t["d"] in N.lut else None
    sup = sorted(s for s in N.comb_leaves(t["d"]) if s in N.ff)
    log.info("[V] AC11 tick ff_8_34_4 ena=%s sclr=%s D support %s leaves %d @%s", t.get("ena"), t.get("sclr"), r[0] if r else [t["d"]], len(sup), labs(sup))
    cnt = sorted(f for f in N.ff if xy(f) in {xy(s) for s in sup} and f not in ("ff_8_34_4",))
    cnt = [f for f in cnt if xy(f) == labs(sup)[0][0]] if sup else []
    if cnt and t["d"] in N.lut:
        p2, t02 = period_to_terminal(cnt, t["d"])
        W["ac11"] = dict(period=p2, term_at_zero=t02, counter=cnt)
        log.info("[V] AC11 divider %s (%d FFs, sclr %s): tick first true after %s clocks (at zero %s)", labs(cnt), len(cnt), {N.ff[f].get("sclr") for f in cnt}, p2, t02)
    # AC11 source tiles
    for k in ((7, 32), (7, 33)):
        m = m9k.get(k)
        if not m:
            continue
        dsig = sorted({s.lstrip("!") for s in (m.get("data") or []) if s and s.lstrip("!") not in ST.CV})
        b = back_d(dsig, 6)
        log.info("[V] AC11 tile %s cls %s A %s W %s data %d addr %d raddr %d we %s", k, m.get("cls"), m.get("A"), m.get("W"), len(dsig), len([s for s in (m.get("addr") or []) if s]),
                 len([s for s in (m.get("raddr") or []) if s]), m.get("we"))
        show(f"AC11 tile {k} data", b)
        we = m.get("we")
        if we and we not in ST.CV:
            bw = back(N, [we.lstrip("!")], 4)
            log.info("[V]   we %s back: %s", we, [(h, len(e["ffs"]), labs(e["ffs"])[:3], e["pads"]) for h, e in enumerate(bw)])
        W[f"ac11_tile{k}"] = dict(n_data=len(dsig), back=b)
    for l in ("lc_6_33_8", "lc_6_33_5"):
        rq = N.red(l)
        log.info("[V]   AC11 bit mux %s = f%s", l, rq[0] if rq else None)
    # descrambled serial bit consumers
    xor = N.ff["ff_31_65_5"]["d"]
    cons_x = N.cons.get(xor, [])
    cons_a = N.cons.get("ff_21_65_0", [])
    cons_b = N.cons.get("ff_29_65_0", [])
    log.info("[V] deserialiser input node %s consumers %s; ff_21_65_0 consumers %s; ff_29_65_0 consumers %d", xor, cons_x[:10], cons_a[:12], len(cons_b))
    ws = fwd(N, fanout, ["ff_21_65_0"], ff_hops=6, cap=30000)
    pads = sorted({str(d) for (k, d, pp) in ws["sinks"] if k == "pad"})
    m9s = sorted({str(d) for (k, d, pp) in ws["sinks"] if k == "m9k"})
    log.info("[V] demod bit ff_21_65_0 forward 6 hops: FFs by hop %s; hop-1 @%s; pads %s; m9k %s%s", {h: len(v) for h, v in ws["ffs"].items()}, labs(ws["ffs"].get(1, []))[:6], pads, m9s[:12], " CAPPED" if ws["capped"] else "")
    hit = set(sum(ws["ffs"].values(), []))
    log.info("[V]   reaches AC11 LAB (6,33) FFs %d, AC10 LAB (4,46) %d, (7,32)/(7,33) data FFs %s", sum(1 for f in hit if xy(f) == (6, 33)), sum(1 for f in hit if xy(f) == (4, 46)),
             [k for k in ((7, 32), (7, 33)) if m9k.get(k) and set(s.lstrip("!") for s in (m9k[k].get("data") or []) if s) & hit])
    W["demod_bit_fwd"] = dict(ffs_by_hop={h: len(v) for h, v in ws["ffs"].items()}, pads=pads, m9k=m9s)
    # reg-3 bits in the (36,57) read address
    rs = [s for s in (m9k[(36, 57)].get("raddr") or []) if s]
    log.info("[V] (36,57) raddr by position: %s", [(i, s, RF.get(s.lstrip("!"))) for i, s in enumerate(rs)])
    # carry check on the convergence LAB
    log.info("[V] (37,88)/(37,89) LUT modes: %s", collections.Counter(N.lut[l]["mode"] for l in N.lut if xy(l) in ((37, 88), (37, 89))))
    R["W"] = W

    # X. dividers with sclr polarity honoured; FX3 video source tiles vs AC11's tiles; the split point
    log.info("== X. dividers (sclr_inv honoured), FX3 vs AC11 source tiles, split point")

    def period_to_clear(ffs, limit=70000):
        """step the counter (other inputs 0, enables honoured, clear ignored) until its own sync-clear condition becomes active."""
        env = {f: 0 for f in ffs}

        def val(sig, e):
            if sig in ST.CV:
                return ST.CV[sig]
            if sig in e:
                return e[sig]
            if sig in N.lut:
                r = N.red(sig)
                if r is None:
                    return 0
                i = 0
                for k, x in enumerate(r[0]):
                    i |= val(x, e) << k
                return r[1][i]
            return 0

        def clear_active(e):
            for f in ffs:
                F = N.ff[f]
                if F.get("sclr"):
                    v = val(F["sclr"], e)
                    if F.get("sclr_inv"):
                        v = 1 - v
                    if v:
                        return True
            return False
        c0 = clear_active(env)
        moved = False
        for step in range(1, limit):
            nxt = {}
            for f in ffs:
                F = N.ff[f]
                en = val(F["ena"], env) if F.get("ena") else 1
                en = (1 - en) if F.get("ena_inv") else en
                nxt[f] = val(F["d"], env) if en else env[f]
            env = nxt
            if any(env.values()):
                moved = True
            if clear_active(env) and moved:
                return step + 1, c0     # the clear takes effect on the next edge: state 0 again after step+1 clocks
            if step > 8 and not moved:
                return None, c0
        return None, c0

    X = {}
    for tag, ffs in (("AC10 (3,45)", div), ("AC11 (9,34)", sorted(f for f in N.ff if xy(f) == (9, 34)))):
        p, c0 = period_to_clear(ffs)
        enas = {N.ff[f].get("ena") for f in ffs}
        X[tag] = dict(period=p, clear_active_at_zero=c0, n=len(ffs), ena=sorted(map(str, enas)))
        log.info("[V] divider %s: %d FFs, ena %s, sclr %s inv %s -> period %s clocks (clear active at zero state: %s)", tag, len(ffs), sorted(map(str, enas)),
                 {N.ff[f].get("sclr") for f in ffs}, {N.ff[f].get("sclr_inv") for f in ffs}, p, c0)
    # FX3 DQ drivers: data provenance (D only) -> tiles
    fx3drv = [io[p]["drv"] for p in FX3_DQ]
    bfx = back_d(fx3drv, 5)
    show("FX3 DQ drivers", bfx)
    fx3_tiles = sorted({t for e in bfx for t in e["m9k"]})
    X["fx3_tiles"] = fx3_tiles
    # AC11 tiles' read/write ports and we cone; FX3 tiles' we cone; intersection = split point candidates
    def we_cone(k, hops=3):
        m = m9k.get(k)
        if not m or not m.get("we") or m["we"] in ST.CV:
            return set(), None
        b = back(N, [m["we"].lstrip("!")], hops)
        return set(sum((e["ffs"] for e in b), [])), b
    for k in ((7, 32), (7, 33)):
        m = m9k[k]
        for key in ("addr", "raddr"):
            sig = sorted({s.lstrip("!") for s in (m.get(key) or []) if s and s.lstrip("!") not in ST.CV})
            b = back_d(sig, 2)
            log.info("[V] AC11 tile %s %s(%d): %s", k, key, len(sig), [(h, len(e["ffs"]), labs(e["ffs"])[:3]) for h, e in enumerate(b)])
        lv = sorted(N.comb_leaves("lc_12_47_12"))
        log.info("[V] AC11 tile %s we !lc_12_47_12 leaves %s", k, lv)
    ac11_we, b11 = we_cone((7, 32))
    log.info("[V] AC11 we cone 3 hops: %s", [(h, len(e["ffs"]), labs(e["ffs"])[:4], e["pads"]) for h, e in enumerate(b11 or [])])
    for k in fx3_tiles[:6]:
        m = m9k.get(tuple(k)) if not isinstance(k, tuple) else m9k.get(k)
        kk = tuple(k)
        if not m:
            continue
        dsig = sorted({s.lstrip("!") for s in (m.get("data") or []) if s and s.lstrip("!") not in ST.CV})
        bd = back_d(dsig, 3)
        cone, bw = we_cone(kk)
        log.info("[V] FX3 tile %s cls %s A %s W %s data %d we %s; data D-back %s; we cone %s; we-cone FFs shared with AC11 we cone: %d %s", kk, m.get("cls"), m.get("A"), m.get("W"), len(dsig), m.get("we"),
                 [(h, len(e["ffs"]), labs(e["ffs"])[:3], e["m9k"][:6]) for h, e in enumerate(bd)], [(h, len(e["ffs"]), labs(e["ffs"])[:3]) for h, e in enumerate(bw or [])],
                 len(cone & ac11_we), sorted(cone & ac11_we)[:10])
        X[f"fx3_tile{kk}"] = dict(data_back=bd, shared_we=sorted(cone & ac11_we))
    # do the two data paths share an upstream FF set (the demux)?
    a11 = set()
    for k in ((7, 32), (7, 33)):
        dsig = sorted({s.lstrip("!") for s in (m9k[k].get("data") or []) if s and s.lstrip("!") not in ST.CV})
        for e in back_d(dsig, 4):
            a11 |= set(e["ffs"])
    fx = set(sum((e["ffs"] for e in bfx), []))
    log.info("[V] FX3-driver D-cone (5 hops) vs AC11-tile data D-cone (4 hops): shared FFs %d @%s %s", len(a11 & fx), labs(a11 & fx)[:6], sorted(a11 & fx)[:10])
    X["shared_data_ffs"] = sorted(a11 & fx)
    R["X"] = X

    # Y. dividers with external leaves forced; the demux select; the video-buffer bank width
    log.info("== Y. divider external inputs, demux select, video bank")

    def ext_leaves(ffs):
        s = set(ffs)
        ext = set()
        for f in ffs:
            F = N.ff[f]
            for k in ("d", "ena", "sclr"):
                if F.get(k) and F[k] not in ST.CV:
                    ext |= {x for x in N.comb_leaves(F[k]) if x not in s and x not in ST.CV}
        return sorted(ext)

    def period_forced(ffs, force, limit=70000):
        env = {f: 0 for f in ffs}

        def val(sig, e):
            if sig in ST.CV:
                return ST.CV[sig]
            if sig in e:
                return e[sig]
            if sig in force:
                return force[sig]
            if sig in N.lut:
                r = N.red(sig)
                if r is None:
                    return 0
                i = 0
                for k, x in enumerate(r[0]):
                    i |= val(x, e) << k
                return r[1][i]
            return 0

        def clear_active(e):
            for f in ffs:
                F = N.ff[f]
                if F.get("sclr"):
                    v = val(F["sclr"], e)
                    if F.get("sclr_inv"):
                        v = 1 - v
                    if v:
                        return True
            return False
        moved, seen = False, {}
        for step in range(1, limit):
            nxt = {}
            for f in ffs:
                F = N.ff[f]
                en = val(F["ena"], env) if F.get("ena") else 1
                en = (1 - en) if F.get("ena_inv") else en
                nxt[f] = val(F["d"], env) if en else env[f]
            env = nxt
            key = tuple(env[f] for f in ffs)
            if any(key):
                moved = True
            if clear_active(env) and moved:
                return ("clear", step + 1)
            if key in seen:
                return ("cycle", step - seen[key])
            seen[key] = step
            if step > 8 and not moved:
                return ("stuck", None)
        return ("limit", None)

    Y = {}
    for tag, ffs, term in (("AC10 (3,45)", div, "lc_4_45_3"), ("AC11 (9,34)", sorted(f for f in N.ff if xy(f) == (9, 34)), "lc_8_34_3")):
        ext = ext_leaves(ffs)
        res = {}
        for name, force in (("ext=0", {x: 0 for x in ext}), ("ext=1", {x: 1 for x in ext})):
            res[name] = period_forced(ffs, force)
        # also each single external leaf high, others low
        for x in ext[:8]:
            res["only " + x] = period_forced(ffs, {y: int(y == x) for y in ext})
        Y[tag] = dict(ext=ext, results=res)
        log.info("[V] divider %s: external leaves %s; results %s", tag, ext, res)
        # the terminal LUT's own leaves outside the counter
        tl = sorted(N.comb_leaves(term))
        log.info("[V]   terminal %s leaves outside counter: %s", term, [x for x in tl if x not in ffs])
    # demux select
    for f in ("ff_11_45_3", "ff_11_45_6", "ff_12_47_4", "ff_9_35_14"):
        Fq = N.ff[f]
        lv = sorted(N.comb_leaves(Fq["d"]))
        log.info("[V] demux sel %s ena=%s sclr=%s D leaves %s RF %s", f, Fq.get("ena"), Fq.get("sclr"), lv[:14], {x: RF[x] for x in lv if x in RF})
    for l in ("lc_19_45_15", "lc_19_45_11", "lc_12_47_12"):
        lv = sorted(N.comb_leaves(l))
        log.info("[V] we %s leaves %s", l, lv)
    we11 = {x for x in N.comb_leaves("lc_12_47_12") if x in N.ff}
    wefx = {x for l in ("lc_19_45_15", "lc_19_45_11") for x in N.comb_leaves(l) if x in N.ff}
    log.info("[V] shared we-leaf FFs video vs AC11: %s", sorted(we11 & wefx))
    bsel = back_d(sorted(we11 | wefx), 3)
    show("demux select", bsel)
    # the (13,25) staging register
    st = sorted(f for f in N.ff if xy(f) == (13, 25))
    rows = []
    for f in st:
        Fq = N.ff[f]
        rq = N.red(Fq["d"]) if Fq["d"] in N.lut else None
        rows.append((f, Fq.get("ena"), Fq.get("sclr"), (rq[0] if rq else [Fq["d"]])[:4]))
    log.info("[V] staging LAB (13,25): %s", rows)
    # video bank: tiles whose data port reads a (13,25)/(12,25) FF
    vid = []
    for m in nl.m9k:
        d = [FT._strip_inv(s) for s in (m.get("data") or []) if s]
        d = [s for s in d if s and s not in ST.CV]
        if d and all(xy(s) in ((13, 25), (12, 25)) for s in d if s in N.ff) and any(s in N.ff for s in d):
            vid.append(((m["x"], m["y"]), m.get("cls"), m.get("A"), m.get("W"), FT._strip_inv(m.get("we") or "")))
    bywe = collections.Counter(v[4] for v in vid)
    log.info("[V] tiles written from the (13,25)/(12,25) staging register: %d; by we %s; shapes %s", len(vid), dict(bywe), collections.Counter((v[1], v[2], v[3]) for v in vid))
    Y["staged_tiles"] = vid
    R["Y"] = Y

    # Z. divider periods from the terminal LUT: the counters are carry-chain LEs (cin-mode, not evaluable by red()),
    #    so take LE index = bit index (LE0 = toggle LSB, carry from LE1 up) and find the smallest count at which the
    #    sync clear (active-low here, sclr_inv) fires: period = that count + 1.
    log.info("== Z. divider periods from the terminal LUT")
    Z = {}
    for tag, lab, term in (("AC10", (3, 45), "lc_4_45_3"), ("AC11", (9, 34), "lc_8_34_3")):
        ffs = sorted((int(f.rsplit("_", 1)[1]), f) for f in N.ff if xy(f) == lab)
        inv = {N.ff[f].get("sclr_inv") for _i, f in ffs if N.ff[f].get("sclr") == term}
        sup = sorted(x for x in N.comb_leaves(term) if x in N.ff)   # ev() recurses through the LUT tree; leaves are the counter FFs
        idx = {f: i for i, f in ffs}
        first = None
        for v in range(1, 1 << 16):
            env = {f: (v >> idx[f]) & 1 for f in sup}
            t = N.ev(term, env)
            clear = (1 - t) if True in inv else t
            if clear:
                first = v
                break
        Z[tag] = dict(lab=lab, term=term, sclr_inv=sorted(map(str, inv)), terminal_count=first, period=(first + 1) if first else None)
        log.info("[V] %s divider %s: terminal %s (sclr_inv %s) first fires at count %s -> bit period %s clocks; Fclk for 115200 = %.2f MHz, for 256000 = %.2f MHz, for 230400 = %.2f MHz",
                 tag, lab, term, inv, first, (first + 1) if first else None, (first + 1) * 115200 / 1e6 if first else 0, (first + 1) * 256000 / 1e6 if first else 0,
                 (first + 1) * 230400 / 1e6 if first else 0)
    # serialiser bit counters: terminal state of the 4-bit counters
    for tag, bits, term in (("AC10", ["ff_4_46_4", "ff_4_46_5", "ff_4_46_6", "ff_4_46_7"], "lc_4_46_11"), ("AC11", ["ff_6_33_0", "ff_6_33_1", "ff_6_33_2", "ff_6_33_3"], None)):
        if term:
            s, tt = N.red(term)
            sols = [b for b in itertools.product((0, 1), repeat=len(s)) if N.ev(term, dict(zip(s, b)))]
            log.info("[V] %s bit counter %s terminal %s over %s: satisfying %s", tag, bits, term, s, sols)
        cons = collections.Counter(c for b in bits for c in N.cons.get(b, []))
        log.info("[V]   consumers of %s bit counter: %s", tag, dict(cons))
    R["Z"] = Z

    out = os.path.join(REPO, "tmp", "cycloneiv_clean", "duml_entry_trace.json")
    json.dump(R, open(out, "w"), indent=1, default=str)
    log.info("-> %s", out)


if __name__ == "__main__":
    main()
