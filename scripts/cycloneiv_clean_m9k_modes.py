#!/usr/bin/env python3.15t
"""M9K mode counts of the third-party EP4CGX150 image (#165, #169): counts only (env PLURIBUS_DJI_IMAGE = the .bin path).

  python3.15t scripts/cycloneiv_clean_m9k_modes.py        log: tmp/logs/m9k_modes.log
Population = instances with a routed output (m9k_usage "outputs", 542 on the image).  Mode from the CRAM groups only:
  RAM_USE_TRUE_DUAL_PORT_MODE (m9k.true_dual_port_value: 1 for ROM / single / bidir / packed, 0 for simple dual port)
  rom     tdp=1, no data-in group, no write enable
  single  tdp=1, data-in wired, no read-address group, no port-B data group
  sdp     tdp=0
  tdp     tdp=1 with a read-address group or a port-B data group (not packed)
Features counted inside the population: read-during-write (RAM_NEW_DATA_MODE A / B), packed, mixed width (class A != class B), x36 atom
(class by32/36 in sdp), output registers, clock-enable selects, byte enables.  `modelled` = the emit decodes the tile (nl.m9k modelled).
"""
import collections
import logging
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
    logging.FileHandler(os.path.join(REPO, "tmp", "logs", "m9k_modes.log")), logging.StreamHandler()])
log = logging.getLogger("m9k_modes")


def modes(mk, sel):
    """-> {instance: mode} for the instances in `sel` (bool array)."""
    ctl = mk["ctl"]
    tdp = ctl[("RAM_USE_TRUE_DUAL_PORT_MODE", -1)][:, 0] == 1
    pk = ctl[("RAM_USE_PACKED_MODE", -1)][:, 0] == 1
    data = (mk["data"][:, :18] >= 0).any(1)
    datab = (mk["data_b"] >= 0).any(1)
    rd = mk["read_groups"] > 0
    we = mk["we"] >= 0
    out = {}
    for i in np.where(sel)[0]:
        if not tdp[i]:
            m = "sdp"
        elif rd[i] or (datab[i] and not pk[i]):
            m = "tdp"
        elif not data[i] and not we[i]:
            m = "rom"
        else:
            m = "single"
        out[int(i)] = m
    return out


def cls_of(ctl, name):
    a = ctl[(name, -1)]
    return np.where(a.sum(1) == 1, a.argmax(1), -1)


def main():
    path = os.environ.get("PLURIBUS_DJI_IMAGE")
    if not path or not os.path.exists(path):
        raise SystemExit("PLURIBUS_DJI_IMAGE not set or missing")
    import cycloneiv_decompress as cd
    from lifters.cycloneiv_clean import emit, m9k, m9k_usage
    plane = os.path.join(REPO, "tmp", "m9k_modes_plane.rbf")
    open(plane, "wb").write(cd.decompress(open(path, "rb").read(), {}))      # read-only on the image; derived plane removed below
    try:
        cx = emit.Ctx()
        b = emit.Builder(cx, plane, "image", 2)
        nl = b.run()
        mk = cx.m9kctl.decode(b.bits)
        u = m9k_usage.usage(cx, b.bits, b.edges, mk)
    finally:
        os.remove(plane)
    sel = u["outputs"]
    md = modes(mk, sel)
    ctl = mk["ctl"]
    ca, cb = cls_of(ctl, "RAM_DATA_WRITE_MODE"), cls_of(ctl, "RAM_DATA_WRITE_MODE_B")
    modelled = {m9k.instance(M["x"], M["y"]): bool(M.get("modelled")) for M in nl.m9k}
    cnt = collections.Counter()
    for i, m in md.items():
        cnt[f"mode_{m}"] += 1
        cnt[f"mode_{m}_modelled"] += int(modelled.get(i, False))
        cnt[f"cls_A_{ca[i]}"] += 1
        if m in ("sdp", "tdp"):
            cnt[f"{m}_cls_{ca[i]}_{cb[i]}"] += 1
            cnt[f"{m}_mixed_width"] += int(ca[i] >= 0 and cb[i] >= 0 and ca[i] != cb[i])
        if m == "sdp" and ca[i] == 5:
            cnt["x36_atom_sdp"] += 1
            cnt["x36_atom_sdp_modelled"] += int(modelled.get(i, False))
        cnt["rdw_new_data_A"] += int(ctl[("RAM_NEW_DATA_MODE", -1)][i, 0])
        cnt["rdw_new_data_B"] += int(ctl[("RAM_NEW_DATA_MODE_B", -1)][i, 0])
        cnt["packed"] += int(ctl[("RAM_USE_PACKED_MODE", -1)][i, 0])
        cnt["oreg_A"] += int(mk["oreg"][i])
        cnt["oreg_B"] += int(mk["oreg_b"][i])
        cnt["byte_enable_A"] += int((mk["be"][i] >= 0).any())
        cnt["byte_enable_B"] += int((mk["be_b"][i] >= 0).any())
        for nm in ("RAM_CE_SELECT_INPUT", "RAM_CE_SELECT_CORE", "RAM_CE_SELECT_OUTPUT", "RAM_CE_SELECT_INPUT_B", "RAM_CE_SELECT_CORE_B", "RAM_CE_SELECT_OUTPUT_B"):
            cnt[f"ce_{nm[14:].lower()}"] += int(ctl[(nm, -1)][i].any())
        cnt["clear_data_out"] += int(ctl[("RAM_USE_CLR_DATA_OUT", -1)][i, 0] | ctl[("RAM_USE_CLR_DATA_OUT_B", -1)][i, 0])
        cnt["clear_read_address"] += int(ctl[("RAM_USE_CLR_READ_ADDRESS", -1)][i, 0] | ctl[("RAM_USE_CLR_READ_ADDRESS_B", -1)][i, 0])
        cnt["content_init"] += int(u["init"][i])
    log.info("tiles with routed outputs %d", int(sel.sum()))
    for k in sorted(cnt):
        log.info("  %s %d", k, cnt[k])
    log.info("modelled (emit decodes the tile) %d of %d", sum(modelled.get(i, False) for i in md), len(md))
    for k, v in sorted(nl.und.items()):
        if k.startswith("M9K"):
            log.info("  undecoded %s %d", k, v)


if __name__ == "__main__":
    main()
