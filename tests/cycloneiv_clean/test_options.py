"""Option register decode (docs/cycloneiv-clean-options.md, #169).  Skips when the local vendor / pair data is missing.

Counts (matched / missing / extra / wrong) per bit class are reported to tmp/logs/cycloneiv_clean_oracles.log.
Missing is a fault: the 130 listed bits without a group have no decoded function and are counted, not hidden.
"""
import collections
import json
import os
import sys

import numpy as np
import pytest

from conftest import REPO, need, report

from lifters.cycloneiv_clean import options as O

BUILDS = os.path.join(REPO, "tmp", "cycloneiv_clean", "option_pairs", "builds")
PAIRS = os.path.join(REPO, "databases", "cycloneiv", "option_pairs.json")
sys.path.insert(0, os.path.join(REPO, "scripts"))


def test_table_shape_and_sources():
    es = O.entries()
    assert [e["index"] for e in es] == list(range(160))
    assert all(e["source"] for e in es)
    c = {k: len(v) for k, v in O.classes().items()}
    assert c == {"group": 30, "forced": 35, "default": 95}, c            # 160 = 30 + 35 + 95, no bit in neither list nor group
    assert len(O.groups()) == 13


def test_flag_half_is_default_list():
    """flag 0 <=> default-list bit (silent_set_bits wrote it); flag 1 <=> forced / group bit (set_bits)."""
    es = O.entries()
    assert all((e["vendor_flag"] == 0) == (e["klass"] == "default") for e in es)
    assert sum(e["vendor_flag"] == 0 for e in es) == 95
    assert all(e["vendor_value"] == 1 for e in es if e["klass"] in ("default", "forced"))     # all 130 listed bits read 1


def test_rbf_cells_only_in_frame0_value_half():
    es = O.entries()
    assert not any(e["rbf_cells_flag"] for e in es)                      # tag-18 flag half never reaches the rbf
    assert all(c[0] == 0 for e in es for c in e["rbf_cells"])            # option cells sit in rbf frame 0
    assert sum(bool(e["rbf_cells"]) for e in es) == 32                    # 35 plane-derived minus bits 71 / 106 / 112 (header CRC artifacts)
    assert not any(c[1] in (41, 42) for e in es for c in e["rbf_cells"])  # header CRC bytes are no option storage


def test_groups_match_live_asmdb():
    from lifters.cycloneiv_clean import asmdb_walk as W
    try:
        w = W.Walk()
    except Exception as e:                     # vendor install missing
        pytest.skip(str(e))
    d = {b & 0x77FFFFFF for b in w.default_bits if (b >> 27) == 0x11}
    f = {b & 0x77FFFFFF for b in w.forced_bits if (b >> 27) == 0x11}
    cl = O.classes()
    assert d == set(cl["default"]) and f == set(cl["forced"])
    got = {b & 0x77FFFFFF for g in w.groups() for b in (g["bits"] if g["cls"] == 7 else [x for p in g["paths"] for r in p if r for x in w.mux(r)["bits"]])
           if (b >> 27) == 0x11}
    assert got == set(cl["group"])


def test_jtag_interface_resolved():
    j = {r["klass"]: r for r in O.table()["jtag"]}
    assert len(j) == 15
    assert sum(r["in_asmdb"] for r in j.values()) == 4                       # 11 of 15 classes have no group on this die
    assert j["ASM_JTAG_PIA_TO_TDOUSER"]["n_bits"] == 16 and j["ASM_JTAG_PIA_TO_TDOUTAP"]["n_bits"] == 16
    assert all(r["space"] == "CRAM" for r in j.values() if r["n_bits"])
    assert all(r["n_bits"] == 0 for r in j.values() if "INVERT" in r["klass"])


def _vec(build):
    z = np.load(os.path.join(BUILDS, build, "result.npz"))
    return [int(x) for x in z["opt"][:160]], [int(x) for x in z["opt"][160:]]


def test_encoder_vs_pair_builds():
    need(PAIRS)
    rows = json.load(open(PAIRS))["rows"]
    ok = [r for r in rows if r["status"] == "ok"]
    assert len(ok) > 100
    cls = O.classes()
    tot = {k: collections.Counter() for k in cls}
    flips = collections.Counter()
    flag_changed = 0
    for r in ok:
        sb, ref = f"{r['base']}.{r['id']}", f"{r['base']}.{r['ref']}"
        if not (os.path.exists(os.path.join(BUILDS, sb)) and os.path.exists(os.path.join(BUILDS, ref))):
            continue
        obs, fl = _vec(sb)
        base_obs, base_fl = _vec(ref)
        flag_changed += fl != base_fl
        # the reference build's config = its own assignments (chain refs) or the base build
        ref_row = next((x for x in rows if x["id"] == r["ref"] and x["base"] == r["base"]), None)
        ref_assign = ref_row["assign"] if ref_row else None
        pred = O.encode(O.config_from_qsf([tuple(x) for x in (r["assign"] or [])], r["jtag"]))
        pref = O.encode(O.config_from_qsf([tuple(x) for x in (ref_assign or [])], ref_row["jtag"] if ref_row else None))
        for k, c in O.score(obs, pred).items():
            tot[k].update(c)
        flips.update(O.flip_score(base_obs, obs, pref, pred))
    report("options_encoder_vs_pairs", builds=len(ok), flag_half_changed=flag_changed, flips=dict(flips),
           per_class={k: dict(v) for k, v in tot.items()})
    assert flag_changed == 0
    assert all(v["wrong"] == 0 for v in tot.values()), tot
    assert flips["missing"] == 0 and flips["extra"] == 0, flips


def test_pair_flips_only_group_bits():
    need(PAIRS)
    rows = json.load(open(PAIRS))["rows"]
    grp = set(O.classes()["group"])
    flipped = {b for r in rows if r["status"] == "ok" for b in r["opt_value"]}
    assert flipped <= grp, sorted(flipped - grp)                              # 0 forced / default bit ever changed
    unconfirmed = sorted(grp - flipped)
    report("options_pair_coverage", group_bits=len(grp), flipped=len(flipped), group_bits_without_setting=unconfirmed,
           listed_bits_without_function=len(O.classes()["forced"]) + len(O.classes()["default"]))
    assert unconfirmed == list(range(11, 19))                                 # POF id: decoded from the assembler, no QSF setting


def test_usercode_pairs():
    need(PAIRS)
    rows = {(r["base"], r["id"]): r for r in json.load(open(PAIRS))["rows"] if r["status"] == "ok"}
    z = lambda b: bytes(np.load(os.path.join(BUILDS, b, "result.npz"))["t19"][12:16])
    if not os.path.exists(os.path.join(BUILDS, "min.usercode_chk_off_aabb")):
        pytest.skip("usercode builds missing")
    assert z("min.usercode_chk_off") == b"\xff\xff\xff\xff"                    # checksum default off -> unset
    assert z("min.usercode_chk_off_aabb") == bytes.fromhex("ddccbbaa")         # STRATIX_JTAG_USER_CODE AABBCCDD, little endian
    assert z("min.BASE") != z("min.usercode_chk_off")                          # default = per-build checksum
    assert not rows[("min", "usercode_chk_off_aabb")]["opt_value"]
