"""Bitstream-decode A/B for scripts/perf_pass_verify.py decode (#145): new decompress() / cram_plane()
vs the frozen pre-pass decoder tests/ref_cycloneiv_decompress.py.  Byte-identical output, identical
info dict, identical plane keys; any difference or differing exception is a failure."""
import json
import time
from pathlib import Path

import numpy as np

import cycloneiv_corpus as cc
import cycloneiv_decompress as cd
import cycloneiv_geom as cg
import ref_cycloneiv_decompress as ref

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "sources" / "cycloneiv-corpus"


def ref_cram_plane(rbf_bytes, geom):
    """The pre-pass cram_plane (per-frame unpackbits) on the pre-pass decompressor."""
    info = {}
    u = ref.decompress(rbf_bytes, info)
    f, r, n = info["frame"], info["periphery_frames"], info["cram_frames"]
    nfr = r + n
    vmap = cc.vmap_for(f, tuple(geom.lane_bytes), tuple(map(tuple, geom.lane_swaps)))
    nv = len(vmap)
    parts = []
    for fr in range(1, nfr):
        base = cd.PREAMBLE + fr * f
        width = f if fr < r else f - 2
        chunk = np.frombuffer(u[base:base + width], dtype=np.uint8)
        idx = np.nonzero(np.unpackbits(chunk, bitorder="little"))[0]
        if len(idx):
            parts.append(fr * nv + vmap[idx])
    keys = np.sort(np.concatenate(parts)).astype(np.int64) if parts else np.zeros(0, dtype=np.int64)
    return keys, (nfr, nv)


def targets(n_corpus):
    out = []
    man = json.load(open(SRC / "manifest.json"))["entries"]
    for e in man:
        dev = e["analysis"].get("device") if e["analysis"].get("geometry_supported") else None
        d = SRC / e["name"]
        for p in sorted(d.glob("*.rbf")):
            out.append((f"src:{e['name']}/{p.name}", p, dev))
    names = sorted(p.name for p in (REPO / "corpus" / "cycloneiv").iterdir() if (p / "bitstream.rbf").exists())
    dev_of = {n: cc.device_of(n) for n in names}
    e6 = [n for n in names if not dev_of[n].startswith("EP4CGX150")]
    gx = [n for n in names if dev_of[n].startswith("EP4CGX150")]
    step = max(1, len(gx) // max(n_corpus, 1))
    for n in e6 + gx[::step]:
        out.append((n, REPO / "corpus" / "cycloneiv" / n / "bitstream.rbf", dev_of[n]))
    return out


def run(a, log):
    res, bad = [], 0
    geoms = {}
    tot = dict(ref_dec=0.0, new_dec=0.0, ref_plane=0.0, new_plane=0.0)
    items = targets(a.corpus)
    log.info("%d images", len(items))
    for name, path, dev in items:
        data = path.read_bytes()
        geom = None
        if dev:
            geom = geoms.get(dev) or geoms.setdefault(dev, cg.load(cg.die_of(dev)))
        ok, err = True, None
        i_ref, i_new = {}, {}
        try:
            t = time.perf_counter(); u_ref = ref.decompress(data, i_ref); t_ref = time.perf_counter() - t
            e_ref = None
        except cd.FormatError as e:
            u_ref, e_ref, t_ref = None, str(e), 0.0
        try:
            t = time.perf_counter(); u_new = cd.decompress(data, i_new); t_new = time.perf_counter() - t
            e_new = None
        except cd.FormatError as e:
            u_new, e_new, t_new = None, str(e), 0.0
        if e_ref != e_new or u_ref != u_new or i_ref != i_new:
            ok, err = False, f"decompress differs (ref err {e_ref!r}, new err {e_new!r})"
        r = dict(image=name, dev=dev, bytes=len(data), identical=ok, ref_dec_s=round(t_ref, 4), new_dec_s=round(t_new, 4))
        if ok and u_ref is not None:
            t = time.perf_counter(); k_ref, sh = ref_cram_plane(data, geom); t_rp = time.perf_counter() - t
            t = time.perf_counter(); pl = cc.cram_plane(data, geom); t_np = time.perf_counter() - t
            if not (np.array_equal(k_ref, pl.keys) and k_ref.dtype == pl.keys.dtype and sh == pl.shape):
                ok, err = False, "plane keys differ"
            r.update(identical=ok, set_bits=len(k_ref), ref_plane_s=round(t_rp, 4), new_plane_s=round(t_np, 4))
            tot["ref_plane"] += t_rp; tot["new_plane"] += t_np
        tot["ref_dec"] += t_ref; tot["new_dec"] += t_new
        if err:
            r["error"] = err
        bad += not ok
        res.append(r)
        log.info("%s", r)
    json.dump(dict(totals=tot, results=res), open(REPO / "tmp" / "perf_pass_verify_decode.json", "w"), indent=1)
    log.info("decode: %d images, %d differ, totals %s", len(res), bad, {k: round(v, 2) for k, v in tot.items()})
    return bad
