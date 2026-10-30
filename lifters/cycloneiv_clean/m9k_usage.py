"""One definition of M9K instance usage (#165, #169); shared by scripts/cycloneiv_clean_m9k_dump.py and scripts/cycloneiv_clean_m9k_image_ports.py.

Instance = MEAB index = column rank * 90 + (Y - 1) (m9k.instance); one instance per M9K tile.  Counts over all instances of the die (720 on EP4CGX150):
  init        any RAM_CONTENT_YGR_MEAB mux position set (content bit = mux position value 1)
  config      any bit set in a MEAB group other than the content group; config_nondefault = config differs from the most common pattern of the die
  outputs     a programmed edge whose source is an M4K_BUFFER record of the tile
  inputs      a programmed edge whose destination is a BLOCK_INPUT_MUX or M4K_LEFT_CONTROL_INPUT record of the tile
  ports       a connected data / address / byte-enable / write-enable selection (m9kctl.decode): the decoded pin groups, a subset of inputs
`edges` = programmed edge ids of the headline variant (Builder.edges).
"""
import numpy as np

from . import ddb, ffctl, m9k, names, plane as P
from . import fields as F


def config_columns(walk):
    """[instances, n] plane cell ids of every non-content MEAB group bit (all paths of all groups)."""
    import sys
    sys.path.insert(0, ddb.SCRIPTS)
    import cycloneiv_clean_dirt as D
    gt = D.enum_tables()["arch_group_type"]
    tab = P.load_tables()
    bs = F.bases(walk, m9k.MEAB)
    cols = []
    for g in walk.groups():
        if g["btype"] != m9k.MEAB or gt.get(g["type"]) == m9k.CONTENT_GROUP:
            continue
        for path in g["paths"]:
            c = ffctl._cols(bs, walk.mux(path[0])["bits"], tab)
            cols.extend(c[k] for k in sorted(c))
    return np.stack(cols, axis=1)


def usage(cx, bits, edges, mk=None):
    """-> {name: bool [instances]}."""
    st, rt = cx.st, cx.rt
    n = len(cx.m9kctl.decode(bits)["cls"]) if mk is None else len(mk["cls"])
    out = {}
    out["init"] = cx.m9k_content(bits).any(1)
    cfg = bits[config_columns(cx.lut.walk)].astype(bool)
    out["config"] = cfg.any(1)                                  # any bit set (the erased pattern already has set bits: every instance)
    rows, inv, cnt = np.unique(cfg, axis=0, return_inverse=True, return_counts=True)
    out["config_nondefault"] = (inv.ravel() != cnt.argmax())    # differs from the most common config pattern of the die
    e = np.asarray(edges, np.int64)
    s, d = st.esrc[e].astype(np.int64), st.edst[e].astype(np.int64)
    cols = m9k.columns()
    rank = {x: k for k, x in enumerate(cols)}

    def inst_of(rec):
        ok = np.isin(rt.x[rec], cols) & (rt.y[rec] >= 1) & (rt.y[rec] <= F.ROWS_PER_COLUMN)
        rec = rec[ok]
        return np.array([rank[int(x)] * F.ROWS_PER_COLUMN + int(y) - 1 for x, y in zip(rt.x[rec], rt.y[rec])], np.int64)
    o = np.zeros(n, bool)
    o[inst_of(s[cx.enum[s] == names.enum_of("M4K_BUFFER")])] = True
    out["outputs"] = o
    i = np.zeros(n, bool)
    i[inst_of(d[np.isin(cx.enum[d], [names.enum_of("BLOCK_INPUT_MUX"), names.enum_of("M4K_LEFT_CONTROL_INPUT")])])] = True
    out["inputs"] = i
    mk = mk if mk is not None else cx.m9kctl.decode(bits)
    out["ports"] = (mk["data"] >= 0).any(1) | (mk["waddr"] >= 0).any(1) | (mk["be"] >= 0).any(1) | (mk["we"] >= 0)
    return out


def summary(u):
    """Counts of each definition plus the overlaps the reports quote."""
    c = {k: int(v.sum()) for k, v in u.items()}
    c["instances"] = len(u["init"])
    c["any_of_init_config_outputs_inputs"] = int((u["init"] | u["config"] | u["outputs"] | u["inputs"]).sum())
    c["init_and_outputs"] = int((u["init"] & u["outputs"]).sum())
    c["init_and_inputs"] = int((u["init"] & u["inputs"]).sum())
    c["outputs_and_inputs"] = int((u["outputs"] & u["inputs"]).sum())
    c["outputs_no_init"] = int((u["outputs"] & ~u["init"]).sum())
    return c
