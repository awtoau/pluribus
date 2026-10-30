#!/usr/bin/env python3
"""Per-file numerology fit of every DJI video-link capture (#165), label-independent.

Reuses the awto-dji measurement functions (scripts/re/lightbridge_ofdm_params.py, imported read-only):
CP-lag correlation -> Tu, df; cyclic spectrum -> T, CP ratio; carrier map -> used carriers, DC null,
BPSK^2-coherent (pilot-like) bins and their spacing. Adds burst length, start-to-start period and a
count of narrowband (second-link) bursts. One JSON line per file: tmp/ofdm_pop/num_<job>.jsonl.
Usage: python3 -I scripts/lightbridge_numerology_fit.py --job zenodo|genesys|ku   (ku: /usr/bin/python3 -I)
"""
import argparse
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
from scipy import signal

sys.dont_write_bytecode = True  # awto-dji is read-only: no __pycache__ there
sys.path.insert(0, "/mnt/2tb/git/awto-dji/scripts/re")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lightbridge_ofdm_params as P  # noqa: E402
import lightbridge_ofdm_demod as D  # noqa: E402
import lightbridge_ofdm_population as POPM  # noqa: E402

POP = D.ROOT / "tmp" / "ofdm_pop"
quiet = lambda *a: None  # noqa: E731


def burst_list(x, fs):
    t, f, S_db, active, _ = occupancy_nopng(x, fs)
    return P.find_bursts(t, f, S_db, active, fs, quiet)


def occupancy_nopng(x, fs, nfft=1024, hop_us=20.0):
    hop = max(1, int(fs * hop_us * 1e-6))
    f, t, S = signal.spectrogram(x, fs=fs, nperseg=nfft, noverlap=nfft - hop, return_onesided=False, mode="psd", window="hann")
    f = np.fft.fftshift(f)
    S_db = 10 * np.log10(np.fft.fftshift(S, axes=0) + 1e-30)
    floor = np.median(S_db)
    return t, f, S_db, S_db > floor + 10.0, floor


def fit_burst(x, fs, b):
    y = P.channelise(x, fs, b["fc"], b["bw"], b["t0"], b["t1"])
    if y.size < 4 * fs / 3e3:
        return None
    Lu, c, z, cfo = P.useful_len(y, fs)
    T, snr_T, p = P.symbol_period(y, Lu, fs)
    ncp, s0, _ = P.fold_cp(p, T, Lu)
    df = fs / Lu
    r = {"t0_ms": b["t0"] * 1e3, "dur_ms": (b["t1"] - b["t0"]) * 1e3, "bw_mhz": b["bw"] / 1e6, "fc_mhz": b["fc"] / 1e6,
         "df_hz": df, "z": z, "T_snr": snr_T, "cp_ratio": (T - Lu) / Lu, "cp_fold_ratio": ncp / Lu, "tsym_us": T / fs * 1e6}
    if z > 8 and snr_T > 8:
        cm = P.carrier_map(y, fs, Lu, T, s0, cfo)
        if cm is not None:
            occ, k = cm["occ"], np.arange(cm["occ"].size) - cm["occ"].size // 2
            idx = np.flatnonzero(occ)
            r["used_1024"] = int(occ.sum())
            r["span_1024"] = int(idx[-1] - idx[0] + 1)
            r["dc_db"] = float(cm["pw_db"][occ.size // 2] - np.median(cm["pw_db"][occ]))
            r["nsym_map"] = cm["nsym"]
            for name, key in (("coh2", "coh2"), ("coh1", "coh1")):
                hi = idx[cm[key][occ] > 0.6]
                r[f"{name}_n"] = int(hi.size)
                if hi.size > 4:
                    v, cn = np.unique(np.diff(k[hi]), return_counts=True)
                    j = int(np.argmax(cn))
                    r[f"{name}_spacing"] = int(v[j])
                    r[f"{name}_spacing_frac"] = float(cn[j] / (hi.size - 1))
            try:
                pil = P.pilot_search(cm, quiet)
                r["pilot9_lag"] = pil["lag"]
                r["pilot9_q"] = pil["q_seq"][:12]
            except Exception as e:  # noqa: BLE001
                r["pilot9_err"] = str(e)[:60]
    return r


def fit_file(x, fs, meta, fout, single=False, nmax=6):
    rec = dict(meta, fs_msps=fs / 1e6, ms=x.size / fs * 1e3)
    if single:
        f0 = D.psd_centre(x, fs)
        bursts = [{"t0": 0.0, "t1": x.size / fs, "fc": f0, "bw": 9.5e6}]
        wide, narrow = bursts, []
    else:
        bursts = burst_list(x, fs)
        wide = [b for b in bursts if b["bw"] >= 5e6 and (b["t1"] - b["t0"]) >= 3e-3]
        narrow = [b for b in bursts if b["bw"] <= 3e6 and 0.3e-3 <= (b["t1"] - b["t0"]) <= 6e-3]
        rec["n_bursts_all"] = len(bursts)
        rec["n_wide"] = len(wide)
        rec["n_narrow"] = len(narrow)
        if len(wide) > 2:
            d = np.diff([b["t0"] for b in wide]) * 1e3
            rec["frame_period_ms_med"] = float(np.median(d))
            rec["frame_period_ms_min"] = float(d.min())
            rec["frame_period_ms_max"] = float(d.max())
        if wide:
            rec["wide_dur_ms_med"] = float(np.median([(b["t1"] - b["t0"]) * 1e3 for b in wide]))
            rec["wide_bw_mhz_med"] = float(np.median([b["bw"] / 1e6 for b in wide]))
        if narrow:
            rec["narrow_dur_ms_med"] = float(np.median([(b["t1"] - b["t0"]) * 1e3 for b in narrow]))
            rec["narrow_bw_mhz_med"] = float(np.median([b["bw"] / 1e6 for b in narrow]))
            fcs = np.array([b["fc"] for b in narrow]) / 1e6
            rec["narrow_n_centres"] = int(np.unique(np.round(fcs)).size)
        # skip first wide burst (may be truncated at capture start)
        wide = wide[1:1 + nmax] if len(wide) > nmax else wide[1:] or wide
    rs = [r for r in (fit_burst(x, fs, b) for b in wide[:nmax]) if r]
    rec["bursts"] = rs
    good = [r for r in rs if r["z"] > 8 and r["T_snr"] > 8]
    rec["n_fit"] = len(good)
    rec["n_tried"] = len(rs)

    def med(key):
        v = [r[key] for r in good if key in r]
        return (float(np.median(v)), float(np.std(v))) if v else None

    for key in ("df_hz", "cp_ratio", "tsym_us", "used_1024", "span_1024", "dc_db", "coh2_n", "coh2_spacing", "coh2_spacing_frac", "dur_ms", "bw_mhz"):
        rec["med_" + key] = med(key)
    fout.write(json.dumps(rec, default=float) + "\n")
    fout.flush()
    D.log(f"{meta.get('file') or meta.get('tag')}: wide={rec.get('n_wide')} fit {len(good)}/{len(rs)} df={rec['med_df_hz']} "
          f"cp={rec['med_cp_ratio']} used={rec['med_used_1024']} coh2sp={rec['med_coh2_spacing']} narrow={rec.get('n_narrow')}")


def job_zenodo(fout):
    for p in sorted(D.ZEN.glob("DJI_*.bin")):
        fs = 200e6 if "5G" in p.name else 120e6
        x = D.load_zenodo(p.name)
        x = x - x.mean()
        fit_file(x, fs, {"dataset": "zenodo", "file": p.name, "band": "5.8" if "5G" in p.name else "2.4"}, fout)
        del x


def job_ku(fout):
    plan = [("inspire2Vid.zip", "inspire2Vid/inspire2_0.mat", "Inspire2"), ("inspire2Vid.zip", "inspire2Vid/inspire2_40.mat", "Inspire2"),
            ("matricevid.zip", "matricevid/matrice_50.mat", "Matrice300"), ("matricevid.zip", "matricevid/matrice_10.mat", "Matrice300"),
            ("MavicVid1.zip", "MavicVid1/Mavic_0.mat", "Mavic"), ("MavicVid2.zip", None, "Mavic"),
            ("mini2vid.zip", "mini2vid/mini2_0.mat", "Mini2"), ("mini2vid.zip", "mini2vid/mini2_40.mat", "Mini2")]
    for zipname, member, dev in plan:
        if member is None:
            with zipfile.ZipFile(D.KUL / zipname) as z:
                member = [i.filename for i in z.infolist() if i.filename.endswith(".mat")][0]
        try:
            x = POPM.load_ku(zipname, member, 20_000_000)
        except Exception as e:  # noqa: BLE001
            D.log(f"{member}: load failed {e}")
            fout.write(json.dumps({"dataset": "kuleuven", "file": member, "device": dev, "load_failed": str(e)[:80]}) + "\n")
            continue
        x = x - x.mean()
        fit_file(x, 100e6, {"dataset": "kuleuven", "file": member, "device": dev}, fout)
        del x


def job_genesys(fout):
    fs = 10e6
    rng = np.random.default_rng(7)
    with zipfile.ZipFile(D.GEN) as z:
        by = {}
        for i in z.infolist():
            if i.filename.endswith(".bin") and i.file_size >= 380000:
                s = Path(i.filename).stem.split("_")
                by.setdefault((s[0], s[1]), []).append(i)
        for key in sorted(by):
            info = by[key][int(rng.integers(len(by[key])))]
            x = D.load_genesys_member(z, info.filename)
            x = x - x.mean()
            fit_file(x, fs, {"dataset": "genesys", "file": Path(info.filename).stem, "device": key[0], "dist": key[1]}, fout, single=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True, choices=["zenodo", "genesys", "ku"])
    a = ap.parse_args()
    D.LOGF = open(D.ROOT / "tmp" / "logs" / f"lightbridge_numerology_fit_{a.job}.log", "w")
    with open(POP / f"num_{a.job}.jsonl", "w") as fout:
        {"zenodo": job_zenodo, "genesys": job_genesys, "ku": job_ku}[a.job](fout)
    D.log("done")


if __name__ == "__main__":
    main()
