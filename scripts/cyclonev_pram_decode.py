#!/usr/bin/env python3
"""Cyclone V PRAM (peripheral RAM) decode: cleartext section of any .rbf, CRAM never read.

Stages (log: tmp/logs/cyclonev_pram_decode.log; local output: vendor-analysis/altera/pram/, gitignored):
  cff      parse the Quartus-shipped config-field CSVs (local copies) into a role/group table
  oracle   FPLL: PRAM raw fields vs the Quartus post-fit .vo defparams, corpus/cyclonev PLL builds
  images   decode the images named in a local {label: path} config; tiers, unmapped counts, pair diffs
  all      cff + oracle + images

Predictions (written before the runs; results in docs/altera/cycloneV/cyclonev-pram.md):
  P1 cff:    every IO-cell group is 4 pads x 38 bits (BIT_SEQ 0..37 per pad); the 4 PLL groups share one
             identical (BINDEX, field) list; the CSV covers a strict subset of the PRAM bits (fewer rows
             than PRAM bits of the die).
  P2 oracle: for every corpus build with one enabled FPLL, each field in FPLL_MAP read from the PRAM plane
             equals the defparam value of the post-fit .vo (all builds, all fields). A miss = wrong bit
             position or encoding, never a tolerance.
  P3 images: set PRAM bits outside every mux claim are ~0 with the die's geometry origin and rise sharply
             when the origin is shifted by 1..3 bit positions (control).
Evidence tiers per field:
  V  varies across the Quartus oracle builds and always matched (position-discriminating)
  C  matched but constant across builds (consistent; does not pin the bit position)
  G  GPIO fields covered by the #103 Quartus fuzz (docs/altera/cycloneV/cyclonev-blockmux-fuzz-status.md), die 0x05 only
  T  table only (Mistral-derived mux table, no Quartus value check on this die)
  U  unmapped: set PRAM bit claimed by no mux
Usage: python3.15t scripts/cyclonev_pram_decode.py {cff,oracle,images,all} [--config images.json]
"""
import argparse
import collections
import csv
import json
import logging
import os
import re
import sys
import zlib

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_pram_core as pc  # noqa: E402

log = logging.getLogger("pram")
OUT = os.path.join(REPO, "vendor-analysis", "altera", "pram")
CORPUS = os.path.join(REPO, "corpus", "cyclonev")
ENC = os.path.join(REPO, "vendor-analysis", "altera", "analysis", "enc")
DEFAULT_CFG = os.path.join(REPO, "vendor-analysis", "altera", "aes", "images.json")

# defparam (post-fit .vo, FRACTIONAL_PLL) -> (mux name in fpll-mux, kind). int = raw field value, bool = 1 bit.
FPLL_MAP = {
    "pll_enable": ("fpll_enable", "bool"), "pll_cp_comp": ("cp_comp", "bool"),
    "pll_m_cnt_bypass_en": ("m_cnt_bypass_en", "bool"), "pll_n_cnt_bypass_en": ("n_cnt_bypass_en", "bool"),
    "pll_m_cnt_odd_div_duty_en": ("m_cnt_odd_div_duty_en", "bool"),
    "pll_n_cnt_odd_div_duty_en": ("n_cnt_odd_div_duty_en", "bool"),
    "pll_ctrl_override_setting": ("ctrl_override_setting", "bool"), "pll_lock_fltr_test": ("lock_filter_test", "bool"),
    "pll_tclk_mux_en": ("tclk_mux_en", "bool"), "forcelock": ("forcelock", "bool"),
    "pll_dsm_reset": ("dsm_reset", "bool"), "pll_ecn_bypass": ("ecn_bypass", "bool"),
    "pll_ecn_test_en": ("ecn_test_en", "bool"), "pll_lf_testen": ("lf_testen", "bool"),
    "pll_regulator_bypass": ("regulation_bypass", "bool"), "pll_test_enable": ("test_enable", "bool"),
    "pll_testdn_enable": ("testdn_enable", "bool"), "pll_testup_enable": ("testup_enable", "bool"),
    "vccr_pd": ("vccr_pd", "bool"), "pll_fractional_value_ready": ("fractional_value_ready", "bool"),
    "nreset_invert": ("nrevert_invert", "bool"),
    **{f"pll_vco_ph{k}_en": (f"vco_ph{k}_en", "bool") for k in range(8)},
    "pll_m_cnt_hi_div": ("m_cnt_hi_div_setting", "int"), "pll_m_cnt_lo_div": ("m_cnt_lo_div_setting", "int"),
    "pll_n_cnt_hi_div": ("n_cnt_hi_div_setting", "int"), "pll_n_cnt_lo_div": ("n_cnt_lo_div_setting", "int"),
    "pll_m_cnt_prst": ("m_cnt_lo_preset_setting", "int"),
    "pll_m_cnt_ph_mux_prst": ("m_cnt_ph_mux_preset_setting", "int"),
    "pll_lock_fltr_cfg": ("lock_filter_cfg_setting", "int"),
    "pll_unlock_fltr_cfg": ("unlock_filter_cfg_setting", "int"),
}
# defparam (PLL_OUTPUT_COUNTER) -> (mux in fpll-mux 'c' class, kind); instance = output_counter_index
CNT_MAP = {
    "dprio0_cnt_hi_div": ("dprio0_cnt_hi_div", "int"), "dprio0_cnt_lo_div": ("dprio0_cnt_lo_div", "int"),
    "dprio0_cnt_bypass_en": ("bypass_en", "bool"),
    "dprio0_cnt_odd_div_even_duty_en": ("dprio0_cnt_odd_div_even_duty_en", "bool"),
    "c_cnt_prst": ("cnt_preset", "int"), "c_cnt_ph_mux_prst": ("cnt_ph_mux_preset", "int"),
}

# Fields with Quartus-fuzz evidence on die 0x05 (docs/altera/cycloneV/cyclonev-blockmux-fuzz-status.md, cyclonev-native-decoder.md).
GPIO_VALIDATED = {"DRIVE_STRENGTH", "USE_BUS_HOLD", "USE_OPEN_DRAIN"}


# ---------------------------------------------------------------------------------------------- cff

def read_cff(name):
    with open(os.path.join(ENC, f"{name}_mtm_cff_mapping.csv"), encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    out = []
    for r in rows[2:]:
        if r and r[0] and r[1].isdigit():
            out.append(dict(field=r[0], bindex=int(r[1]), brow=int(r[2]), bcol=int(r[3]),
                            seq=int(r[4]) if r[4].isdigit() else -1, bit=r[4], owner=r[5]))
    return out


def role_of(field):
    p = re.split(r"[_0-9]", field)[0]
    return {"DDR": "io_cell", "LVDS": "lvds", "P": "pll", "DUMMY": "dummy", "VR": "vref", "ADC": "adc",
            "OCT": "oct", "OSC": "osc"}.get(p, "other")


def stage_cff():
    res = {}
    for nm in ("zb8", "zb16"):
        t = read_cff(nm)
        roles = collections.Counter(role_of(r["field"]) for r in t)
        groups = collections.defaultdict(list)
        for r in t:
            groups[(role_of(r["field"]), r["brow"], r["bcol"])].append(r)
        gsz = collections.defaultdict(collections.Counter)
        for (role, _, _), rs in groups.items():
            gsz[role][len(rs)] += 1
        # P1a: io_cell / lvds groups: pads x 38 bits
        pad_ok = pad_tot = 0
        for (role, _, _), rs in groups.items():
            if role in ("io_cell", "lvds"):
                for k, v in collections.Counter(r["owner"] for r in rs).items():
                    pad_tot += 1
                    seqs = sorted(r["seq"] for r in rs if r["owner"] == k)
                    pad_ok += seqs == list(range(38))
        # P1b: PLL groups identical field lists
        pll = [tuple((r["bindex"] - min(x["bindex"] for x in rs), r["field"], r["bit"], r["owner"])
                     for r in sorted(rs, key=lambda r: r["bindex"]))
               for (role, _, _), rs in groups.items() if role == "pll"]
        res[nm] = dict(rows=len(t), roles=dict(roles), group_sizes={k: dict(v) for k, v in gsz.items()},
                       pad_38bit_ok=f"{pad_ok}/{pad_tot}", pll_groups=len(pll), pll_identical=len(set(pll)) == 1,
                       bindex_unique=len({r["bindex"] for r in t}) == len(t))
        log.info("cff %s: %s", nm, json.dumps(res[nm]))
    # PRAM bits per die for the subset test
    for model in ("5CEBA4U19C8", "5CEBA7U19C8"):
        g = pc.light_tables(model)["geom"]
        tot = sum(g["pram_sizes"])
        res[model] = dict(pram_bits=tot, blocks={k: len(v) for k, v in pc.light_tables(model)["pram_blocks"].items()})
        log.info("cff vs %s: PRAM bits %d (csv rows zb8 %d, zb16 %d); blocks %s", model, tot,
                 res["zb8"]["rows"], res["zb16"]["rows"], res[model]["blocks"])
    t = read_cff("zb16")
    br = collections.Counter(r["owner"] for r in t if role_of(r["field"]) == "pll" and (r["brow"], r["bcol"]) == (1, 25))
    res["pll_group_fields"] = dict(br)
    os.makedirs(OUT, exist_ok=True)
    json.dump({n: read_cff(n) for n in ("zb8", "zb16")}, open(os.path.join(OUT, "cff_table.json"), "w"))
    return res


# -------------------------------------------------------------------------------------------- oracle

def parse_vo(path):
    """{'fpll': [ {attr: val} ], 'cnt': [ {attr: val} ]} from defparam lines, grouped by cell name."""
    cells = collections.defaultdict(dict)
    pat = re.compile(r"defparam (\S+) \.(\w+) = (.*);")
    for ln in open(path, errors="replace"):
        m = pat.match(ln.strip())
        if not m:
            continue
        cell, k, v = m.groups()
        v = v.strip().strip('"')
        cells[cell][k] = int(v) if re.fullmatch(r"-?\d+", v) else (1 if v == "true" else 0 if v == "false" else v)
    fp = [d for c, d in cells.items() if c.endswith("FRACTIONAL_PLL")]
    cn = [d for c, d in cells.items() if c.endswith("PLL_OUTPUT_COUNTER")]
    return fp, cn


def raw(plane, base, bits):
    return sum(int(plane[(base & 0xFFFF) + b]) << k for k, b in enumerate(bits))


def cmp_field(plane, base, bits, want, pins, key):
    """Compare a field bit by bit; record per-bit (expected value seen) for position pinning."""
    ok = True
    for k, b in enumerate(bits):
        e = (want >> k) & 1
        a = int(plane[(base & 0xFFFF) + b])
        pins[(key, k)].add(e)
        ok &= a == e
    return ok and want < (1 << len(bits))


def stage_oracle():
    tb = pc.light_tables("5CEBA4U19C8")
    mux = {}
    for m in tb["muxes"]:
        if m["dump_target"] == "fpll":
            mux[m["mux"]] = m
    names = sorted(d for d in os.listdir(CORPUS) if os.path.exists(os.path.join(CORPUS, d, "postfit.vo")))
    stat = collections.defaultdict(lambda: dict(n=0, ok=0, vals=set()))
    pins = collections.defaultdict(set)
    badbit = set()
    builds = nb_multi = nb_skipped = 0
    miss = []
    for d in names:
        fp, cn = parse_vo(os.path.join(CORPUS, d, "postfit.vo"))
        if not fp:
            continue
        if len(fp) != 1:
            nb_multi += 1
            continue
        mdl, bits, _, _ = pc.load_planes(open(os.path.join(CORPUS, d, "bitstream.rbf"), "rb").read(), tb)
        tiles = [t for k, mk, ts, mode in mdl.pram_group_list() if k == "FPLL" for t in ts]
        en = mux["fpll_enable"]
        on = [t for t in tiles if raw(bits.pram[(t[1] >> 16) & 31], t[1], en["bits"][0])]
        if len(on) != 1:
            nb_skipped += 1
            log.info("oracle %s: %d enabled FPLL tiles, skipped", d, len(on))
            continue
        pos, base, _ = on[0]
        plane = bits.pram[(base >> 16) & 31]
        builds += 1
        for dp, (mn, kind) in FPLL_MAP.items():
            if dp not in fp[0]:
                continue
            got = raw(plane, base, mux[mn]["bits"][0])
            key = "fpll." + mn
            s = stat[key]
            s["n"] += 1
            s["vals"].add(fp[0][dp])
            if cmp_field(plane, base, mux[mn]["bits"][0], fp[0][dp], pins, (pos, mn)) and got == fp[0][dp]:
                s["ok"] += 1
            else:
                miss.append((d, mn, got, fp[0][dp]))
        for c in cn:
            idx = c["output_counter_index"]
            for dp, (mn, kind) in CNT_MAP.items():
                if dp not in c:
                    continue
                bl = mux[mn]["bits"][idx]
                got = raw(plane, base, bl)
                key = "fpll.c." + mn
                s = stat[key]
                s["n"] += 1
                s["vals"].add((c[dp], idx))
                if cmp_field(plane, base, bl, c[dp], pins, (pos, mn, idx)) and got == c[dp]:
                    s["ok"] += 1
                else:
                    miss.append((d, f"{mn}[{idx}]", got, c[dp]))
    out = {}
    for k, s in sorted(stat.items()):
        nv = len({v[0] if isinstance(v, tuple) else v for v in s["vals"]})
        npos = len({v[1] for v in s["vals"] if isinstance(v, tuple)})
        tier = "V" if (s["ok"] == s["n"] and nv >= 2) else "C" if s["ok"] == s["n"] else "MISS"
        out[k] = dict(n=s["n"], ok=s["ok"], distinct_values=nv, distinct_instances=npos, tier=tier)
        log.info("oracle %-48s %3d/%3d distinct=%d inst=%d tier %s", k, s["ok"], s["n"], nv, npos, tier)
    tot = sum(s["n"] for s in stat.values())
    ok = sum(s["ok"] for s in stat.values())
    both = sum(1 for v in pins.values() if v == {0, 1})
    log.info("oracle: %d field-bit positions compared, %d seen as both 0 and 1 (position-pinned; FPLL tiles differ by "
             "build so pins are per tile)", len(pins), both)
    log.info("oracle: %d single-PLL builds (%d two-PLL skipped, %d unmatched), %d/%d field comparisons equal; misses %s",
             builds, nb_multi, nb_skipped, ok, tot, miss[:10])
    return dict(builds=builds, two_pll_skipped=nb_multi, unmatched=nb_skipped, compared=tot, equal=ok,
                bit_positions=len(pins), pinned=both,
                misses=miss, fields=out)


# -------------------------------------------------------------------------------------------- images

def decode_image(label, path, oracle_tiers):
    data = open(path, "rb").read()
    m, b, db, dev = pc.load_planes(data)
    st = m.pram_settings()
    own = pc.owners(m)
    sb = pc.set_bits(b)
    geo = m.geo
    claimed = {k for k in sb if k in own}
    unclaimed = sb - claimed
    total = sum(geo.pram_sizes)
    # P3 control: shift every claimed position by d inside its strip
    ctl = {}
    ownk = set(own)
    for d in (1, 2, 3):
        ctl[d] = sum(1 for (s, p) in sb if (s, p + d) in ownk)
    vals = {}
    for s in st:
        vals[(s[0], s[1], s[2], s[3])] = s[5:] if s[4] != "r" else (s[5], s[6].hex())
    # tiers
    tiers = collections.Counter()
    fieldtier = {}
    for (bt, pos, mn, mi) in vals:
        k = (bt, mn)
        if bt == "GPIO" and mn in GPIO_VALIDATED and dev == "5CEBA4U19C8":
            t = "G"
        elif bt == "FPLL" and dev == "5CEBA4U19C8":
            t = oracle_tiers.get("fpll." + mn.lower()) or oracle_tiers.get("fpll.c." + mn.lower()) or "T"
            if t == "MISS":
                t = "T"
        else:
            t = "T"
        fieldtier[k] = t
        tiers[t] += 1
    return dict(label=label, die=db, device=dev, frames=f"{geo.pram_blocks}x{geo.pram_frame_bytes}",
                pram_bits=total, owned_positions=len(own), set_bits=len(sb), claimed_set=len(claimed),
                unclaimed_set=len(unclaimed), shift_control=ctl, n_settings=len(vals), tiers=dict(tiers),
                fieldtier={f"{a}.{b_}": t for (a, b_), t in fieldtier.items()}, vals=vals, settings=st, model=m)


def summarize_plain(r):
    """Plain-terms facts (local report only)."""
    st = r["settings"]
    out = {}
    by = collections.Counter((s[0], s[2]) for s in st)
    out["settings_by_block"] = dict(collections.Counter(s[0] for s in st))
    drv = collections.Counter(str(s[5]) for s in st if s[0] == "GPIO" and s[2] == "DRIVE_STRENGTH")
    out["gpio_drive"] = dict(drv)
    out["gpio_iocsr"] = dict(collections.Counter(str(s[5]) for s in st if s[0] == "GPIO" and s[2] == "IOCSR_STD"))
    out["gpio_other"] = dict(collections.Counter(f"{s[2]}={s[5]}" for s in st
                                                 if s[0] == "GPIO" and s[2] not in ("DRIVE_STRENGTH", "IOCSR_STD")))
    plls = collections.defaultdict(dict)
    for s in st:
        if s[0] == "FPLL":
            plls[s[1]].setdefault(s[2], {})[s[3]] = s[5] if s[4] != "r" else int.from_bytes(s[6], "little")
    pl = {}
    for pos, f in plls.items():
        if "FPLL_ENABLE" not in f:
            continue
        g = lambda n, d=1: f.get(n, {}).get(-1, d)  # noqa: E731
        M = g("M_CNT_HI_DIV_SETTING") + g("M_CNT_LO_DIV_SETTING") if not g("M_CNT_BYPASS_EN", 0) else 1
        N = g("N_CNT_HI_DIV_SETTING") + g("N_CNT_LO_DIV_SETTING") if not g("N_CNT_BYPASS_EN", 0) else 1
        cnts = {}
        for i in f.get("CNT_IN_SRC", {}):
            pass
        for i in range(9):
            if f.get("C%d_COUT_EN" % i, {}).get(-1):
                hi = f.get("DPRIO0_CNT_HI_DIV", {}).get(i, 1)
                lo = f.get("DPRIO0_CNT_LO_DIV", {}).get(i, 1)
                cnts[i] = hi + lo
        pl[str(pos)] = dict(M=M, N=N, counters_enabled=cnts, vco_ratio=f"{M}/{N}",
                            clkin_src=f.get("CLKIN_0_SRC", {}).get(-1))
    out["fpll"] = pl
    out["hard_blocks_with_settings"] = sorted({s[0] for s in st if s[0] not in ("GPIO", "FPLL", "CMUXVG", "CMUXHG")})
    return out


def stage_images(cfg_path, oracle):
    cfg = json.load(open(cfg_path))
    tiers = {k: v["tier"] for k, v in oracle["fields"].items()} if oracle else {}
    res, rep = {}, {}
    for lab, p in cfg.items():
        r = decode_image(lab, p, tiers)
        res[lab] = r
        pl = summarize_plain(r)
        rep[lab] = dict({k: v for k, v in r.items() if k not in ("vals", "settings", "model")}, plain=pl)
        json.dump([[s[0], list(s[1]), s[2], s[3], s[4], str(s[5:])] for s in r["settings"]],
                  open(os.path.join(OUT, f"settings_{lab}.json"), "w"))
        log.info("%s die %#x %s PRAM %s: %d bits, owned %d, set %d, claimed %d, unclaimed %d (unclaimed if every claim is shifted +1/+2/+3 positions: %s); "
                 "%d non-default fields; tiers %s", lab, r["die"], r["device"], r["frames"], r["pram_bits"],
                 r["owned_positions"], r["set_bits"], r["claimed_set"], r["unclaimed_set"],
                 {d: r["set_bits"] - v for d, v in r["shift_control"].items()},
                 r["n_settings"], r["tiers"])
        log.info("%s plain: %s", lab, json.dumps(pl, default=str))
    # pair diffs
    labs = list(res)
    pairs = {}
    for i, a in enumerate(labs):
        for b in labs[i + 1:]:
            A, B = res[a], res[b]
            if A["die"] != B["die"]:
                continue
            keys = set(A["vals"]) | set(B["vals"])
            dif = sorted(k for k in keys if A["vals"].get(k) != B["vals"].get(k))
            ba = pc.set_bits(A["model"].bits)
            bb = pc.set_bits(B["model"].bits)
            pairs[f"{a}/{b}"] = dict(bits_differing=len(ba ^ bb), fields_differing=len(dif),
                                     by_block=dict(collections.Counter(k[0] for k in dif)),
                                     by_field=dict(collections.Counter(f"{k[0]}.{k[2]}" for k in dif)))
            pairs[f"{a}/{b}"]["detail"] = [(list(k[:3]) + [k[3]], str(A["vals"].get(k)), str(B["vals"].get(k))) for k in dif]
            log.info("pair %s/%s: %d PRAM bits differ, %d fields; %s", a, b, pairs[f"{a}/{b}"]["bits_differing"], len(dif),
                     pairs[f"{a}/{b}"]["by_block"])
    # compare dies: block-type presence
    return rep, pairs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=("cff", "oracle", "images", "all"))
    ap.add_argument("--config", default=DEFAULT_CFG, help="local untracked JSON {label: path}")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_pram_decode.log"), mode="w")])
    os.makedirs(OUT, exist_ok=True)
    result = {}
    if a.stage in ("cff", "all"):
        result["cff"] = stage_cff()
    if a.stage in ("oracle", "all", "images"):
        result["oracle"] = stage_oracle()
    if a.stage in ("images", "all"):
        result["images"], result["pairs"] = stage_images(a.config, result["oracle"])
    json.dump(result, open(os.path.join(OUT, f"report_{a.stage}.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
