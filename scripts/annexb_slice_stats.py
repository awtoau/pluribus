#!/usr/bin/env python3
"""Generic H.264 Annex-B slice / macroblock statistics (no vendor data, stdlib only).

  python3 scripts/annexb_slice_stats.py stream.h264 [--mbmap] [--json out.json]

Bitstream pass (always): NAL type histogram, SEI payload types (6 = recovery point), IDR count,
per-access-unit slice layout (first_mb_in_slice, size, slice_type, frame_num), SPS/PPS/IDR/recovery
spacing in access units, frame_num gaps.
--mbmap: decode with ffmpeg (-debug mb_type, one thread) and report per-frame intra macroblocks,
rows / columns that are mostly intra, and runs of consecutive frames whose intra band advances
(gradual refresh: rolling intra rows or columns) with run lengths and start spacing.
Log: tmp/logs/annexb_slice_stats.log
"""
import argparse
import collections
import json
import logging
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(REPO, "tmp", "logs", "annexb_slice_stats.log")
log = logging.getLogger("annexb_slice_stats")
BAND_FRAC = 0.6  # a row / column counts as an intra band line when >= this share of its MBs is intra


class Bits:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def u(self, n):
        v = 0
        for _ in range(n):
            byte = self.d[self.p >> 3] if (self.p >> 3) < len(self.d) else 0
            v = (v << 1) | ((byte >> (7 - (self.p & 7))) & 1)
            self.p += 1
        return v

    def ue(self):
        z = 0
        while self.p < len(self.d) * 8 and self.u(1) == 0:
            z += 1
        return (1 << z) - 1 + self.u(z)

    def se(self):
        k = self.ue()
        return (k + 1) // 2 if k & 1 else -(k // 2)


def unescape(b):
    return re.sub(b"\x00\x00\x03", b"\x00\x00", b)


def split_nals(data):
    """Return [(offset_of_nal_header, nal_bytes_without_start_code)]."""
    marks = [m.start() for m in re.finditer(b"\x00\x00\x01", data)]
    out = []
    for i, s in enumerate(marks):
        end = marks[i + 1] if i + 1 < len(marks) else len(data)
        nal = data[s + 3:end]
        out.append((s + 3, nal.rstrip(b"\x00") if i + 1 < len(marks) else nal))
    return out


def parse_sps(rbsp):
    b = Bits(rbsp)
    profile = b.u(8)
    b.u(8)
    level = b.u(8)
    sps_id = b.ue()
    chroma = 1
    if profile in (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135):
        chroma = b.ue()
        if chroma == 3:
            b.u(1)
        b.ue()
        b.ue()
        b.u(1)
        if b.u(1):  # scaling matrices: sizes only, values not needed
            for i in range(8 if chroma != 3 else 12):
                if b.u(1):
                    last = nxt = 8
                    for _ in range(16 if i < 6 else 64):
                        if nxt:
                            nxt = (last + b.se()) % 256
                        last = last if nxt == 0 else nxt
    log2_fn = b.ue() + 4
    poc_type = b.ue()
    if poc_type == 0:
        b.ue()
    elif poc_type == 1:
        b.u(1)
        b.se()
        b.se()
        for _ in range(b.ue()):
            b.se()
    b.ue()
    b.u(1)
    w = b.ue() + 1
    h = b.ue() + 1
    frame_mbs_only = b.u(1)
    return {"profile": profile, "level": level, "sps_id": sps_id, "log2_max_frame_num": log2_fn,
            "mb_w": w, "mb_h": h * (1 if frame_mbs_only else 2), "frame_mbs_only": frame_mbs_only}


def sei_payload_types(rbsp):
    out, p = [], 0
    while p + 2 <= len(rbsp) and rbsp[p] != 0x80:
        t = 0
        while rbsp[p] == 0xFF:
            t += 255
            p += 1
        t += rbsp[p]
        p += 1
        sz = 0
        while rbsp[p] == 0xFF:
            sz += 255
            p += 1
        sz += rbsp[p]
        p += 1
        out.append(t)
        p += sz
    return out


def bitstream_pass(data):
    spss, nal_hist, sei_hist, aus, cur = {}, collections.Counter(), collections.Counter(), [], None
    has_aud = b"\x00\x00\x01\x09" in data
    for off, nal in split_nals(data):
        if not nal:
            continue
        t = nal[0] & 31
        nal_hist[t] += 1
        rb = unescape(nal[1:])
        if t == 9 or cur is None or (not has_aud and t in (6, 7, 8) and cur["slices"]):
            cur = {"sps": False, "pps": False, "idr": False, "recovery": False, "slices": []}
            aus.append(cur)
        if t == 7:
            s = parse_sps(rb)
            spss[s["sps_id"]] = s
            cur["sps"] = True
        elif t == 8:
            cur["pps"] = True
        elif t == 6:
            ts = sei_payload_types(rb)
            sei_hist.update(ts)
            cur["recovery"] |= 6 in ts
        elif t in (1, 5):
            b = Bits(rb[:16])
            fm, st, pid = b.ue(), b.ue(), b.ue()
            sp = next(iter(spss.values()), None)
            fn = b.u(sp["log2_max_frame_num"]) if sp else None
            if fm == 0 and cur["slices"] and not has_aud:  # no AUD in stream: first_mb 0 opens a new AU
                cur = {"sps": False, "pps": False, "idr": False, "recovery": False, "slices": []}
                aus.append(cur)
            cur["idr"] |= t == 5
            cur["slices"].append((fm, len(nal), st % 5, fn))
    return aus, nal_hist, sei_hist, spss


def spacing(aus, key):
    idx = [i for i, a in enumerate(aus) if a[key]]
    return idx, collections.Counter(b - a for a, b in zip(idx, idx[1:])).most_common(6)


def mbmap_pass(path, spss):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "debug", "-debug", "mb_type", "-threads", "1", "-flags",
           "+output_corrupt", "-err_detect", "ignore_err", "-max_error_rate", "1.0", "-i", path, "-f", "null", "-"]
    rowre = re.compile(r"^\[h264 @ 0x[0-9a-f]+\]\s+(\d+) (.*)$")
    frames, cur = [], None
    p = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, errors="replace")
    for line in p.stderr:
        if "New frame, type:" in line:
            cur = {}
            frames.append(cur)
            continue
        m = rowre.match(line.rstrip("\n"))
        if cur is not None and m and len(m.group(2)) >= 3 * 4:
            s = m.group(2)
            cur[int(m.group(1)) // 16] = [s[i] for i in range(0, len(s), 3)]
    p.wait()
    mb_h = next(iter(spss.values()))["mb_h"] if spss else None
    res = []
    for f in frames:
        if not f or (mb_h and len(f) < mb_h):
            continue
        rows = sorted(f)
        intra = [[c in "iIP" for c in f[y]] for y in rows]
        nrow, ncol = len(intra), len(intra[0])
        rband = [y for y in range(nrow) if sum(intra[y]) >= BAND_FRAC * ncol]
        cband = [x for x in range(ncol) if sum(intra[y][x] for y in range(nrow)) >= BAND_FRAC * nrow]
        res.append({"intra": sum(map(sum, intra)), "mbs": nrow * ncol, "rows": rband, "cols": cband})
    return res


def runs_of_advancing(res, key):
    """Runs of consecutive frames whose band (rows or cols) is non-empty and starts at/after the previous band start."""
    runs, i = [], 0
    while i < len(res):
        if res[i][key]:
            j = i
            while j + 1 < len(res) and res[j + 1][key] and min(res[j + 1][key]) >= min(res[j][key]):
                j += 1
            runs.append((i, j - i + 1, min(res[i][key]), max(res[j][key])))
            i = j + 1
        else:
            i += 1
    return runs


def summarise_mb(res):
    out = {"frames": len(res)}
    for key in ("rows", "cols"):
        runs = [r for r in runs_of_advancing(res, key) if r[1] >= 3]
        out[key] = {"runs": len(runs), "run_lengths": collections.Counter(r[1] for r in runs).most_common(5),
                    "start_spacing": collections.Counter(b[0] - a[0] for a, b in zip(runs, runs[1:])).most_common(5)}
    band = {i for i, r in enumerate(res) if r["rows"] or r["cols"]}
    rest = [r["intra"] / r["mbs"] for i, r in enumerate(res) if i not in band]
    out["intra_share_outside_bands"] = round(sum(rest) / len(rest), 4) if rest else None
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stream")
    ap.add_argument("--mbmap", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(LOG), logging.StreamHandler(sys.stdout)])
    data = open(a.stream, "rb").read()
    aus, nal_hist, sei_hist, spss = bitstream_pass(data)
    rep = {"bytes": len(data), "access_units": len(aus), "nal_types": dict(nal_hist), "sei_payload_types": dict(sei_hist),
           "idr_aus": sum(x["idr"] for x in aus), "recovery_point_aus": sum(x["recovery"] for x in aus),
           "sps": list(spss.values())}
    for k in ("sps", "pps", "idr", "recovery"):
        idx, sp = spacing(aus, k)
        rep[f"{k}_aus"] = len(idx)
        rep[f"{k}_spacing"] = sp
    rep["slices_per_au"] = collections.Counter(len(x["slices"]) for x in aus).most_common(6)
    rep["layouts"] = collections.Counter(tuple(s[0] for s in x["slices"]) for x in aus).most_common(4)
    rep["slice_types"] = dict(collections.Counter(s[2] for x in aus for s in x["slices"]))
    fns = [x["slices"][0][3] for x in aus if x["slices"] and x["slices"][0][3] is not None]
    mod = 1 << next(iter(spss.values()))["log2_max_frame_num"] if spss else 1
    rep["frame_num_gaps"] = sum(1 for p, q in zip(fns, fns[1:]) if (q - p) % mod not in (0, 1))
    if a.mbmap:
        rep["mbmap"] = summarise_mb(mbmap_pass(a.stream, spss))
    for k, v in rep.items():
        log.info("%s: %s", k, v)
    if a.json:
        json.dump(rep, open(a.json, "w"), indent=1, default=list)


if __name__ == "__main__":
    main()
