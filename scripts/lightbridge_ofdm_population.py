#!/usr/bin/env python3
"""Population check of the Lightbridge OFDM demod over many bursts/devices (#165).

Per burst: numerology fit, symbol count, lead symbols, pilot even/odd amplitude ratio (per symbol
parity), pilot phase offset, symbol 0/1/2 features, data kurtosis, SNR. Writes one JSON line per burst
to tmp/ofdm_pop/pop_<job>.jsonl and the equalisation inputs to tmp/ofdm_pop/X/<tag>.npz.
Usage: python3 -I scripts/lightbridge_ofdm_population.py --job zenodo|genesys|ku
KU Leuven (h5py) needs /usr/bin/python3 -I.
"""
import argparse
import json
import sys
import zipfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lightbridge_ofdm_demod as D  # noqa: E402

POP = D.ROOT / "tmp" / "ofdm_pop"
(POP / "X").mkdir(parents=True, exist_ok=True)
PS = D.pilot_sets()
KC = np.arange(865) - 432


def fitset(X, m, cls, par):
    kp = PS[cls][par::2]
    t, p, met, _ = D.sq_fit(X[m, kp], kp)
    ref = np.exp(1j * (p - 2 * np.pi * (kp - 432) * t / 1024))
    return t, p, met, float(np.median(np.abs(X[m, kp] / ref)))


def parity_stats(R, mmax=60):
    X, exp = R["X"], R["exp"]
    ro, re_, dphi, dtau, mets = [], [], [], [], []
    for m in range(1, min(X.shape[0] - 1, mmax)):
        te, pe, me, ae = fitset(X, m, exp[m], 0)
        to, po, mo, ao = fitset(X, m, exp[m], 1)
        r = ae / max(ao, 1e-12)
        (ro if m % 2 else re_).append(r)
        dphi.append(pe - po)
        dtau.append(te - to)
        mets.append(min(me, mo))
    rodd, reven = float(np.median(ro)), float(np.median(re_))
    z = np.mean(np.exp(2j * np.array(dphi)))
    d = (np.degrees(np.angle(z)) / 2) % 180
    return {"r_oddsym": rodd, "r_evensym": reven,
            "hilo": float(np.sqrt(max(rodd, 1 / rodd) * max(reven, 1 / reven))),
            "alt_prod": rodd * reven, "swap": bool((rodd - 1) * (reven - 1) < 0),
            "dphi_deg": float(min(d, 180 - d)), "dphi_signed_deg": float(d), "dphi_conc": float(abs(z)),
            "dtau_samp": float(np.median(dtau)), "par_fit_metric": float(np.median(mets))}


def snr_db(y, R):
    first = R["s0"] + R["m0"] * D.NSYM
    n0 = first + 8 * D.NSYM
    rows = D.fft_symbols_raw(y, n0, 16, R["cfo_total"])
    if rows.shape[0] < 8:
        return None
    P = np.mean(np.abs(rows) ** 2, 0)
    sh = (R["shift"]) if False else 0
    used = P[80 + 20:944 - 20]
    guard = np.concatenate([P[62:76], P[948:962]])
    return float(10 * np.log10(np.mean(used) / np.mean(guard)))


def features(R, y, meta):
    X, Y, PM = R["X"], R["Y"], R["PM"]
    out = dict(meta)
    out.update({"nsym": R["nsym"], "lead": R["m0"], "cp_q": R["cp_q"], "edge_err": R["edge_err"],
                "occ_bins": R["occ_bins"], "cfo_hz": R["cfo_total"], "pilot_agree": R["pat_agree"],
                "pat_phase": R["pat_phase"], "class_steps": R["theta"]})
    out.update(parity_stats(R))
    sf = D.symbol_features(R, 3)
    out["sym0_k4"] = sf[0]["k4"]
    out["sym0_met_min"] = float(min(R["met"][0]))
    out["sym0_met_max"] = float(max(R["met"][0]))
    out["sym1_cv"] = sf[1]["mod_cv"]
    out["sym2_cv"] = sf[2]["mod_cv"]
    out["sym1_k4"] = sf[1]["k4"]
    out["sym2_k4"] = sf[2]["k4"]
    if R["nsym"] > 20:
        pts = np.concatenate([Y[m][~PM[m] & ~np.isnan(Y[m])] / np.sqrt(np.mean(np.abs(Y[m][~PM[m] & ~np.isnan(Y[m])]) ** 2))
                              for m in range(12, R["nsym"] - 1)])
        out["k4"] = float(np.mean(np.abs(pts) ** 4))
        out["m4"] = float(abs(np.mean(pts ** 4)) / np.mean(np.abs(pts) ** 4))
    out["snr_db"] = snr_db(y, R)
    return out


def handle(y, tag, meta, fout):
    try:
        R = D.demod_burst(y, tag)
    except Exception as e:  # noqa: BLE001  record the failure, keep going
        D.log(f"  [{tag}] demod exception {type(e).__name__}: {e}")
        R = None
    if R is None:
        rec = dict(meta, tag=tag, failed=True)
    else:
        rec = features(R, y, meta)
        rec["tag"] = tag
        np.savez_compressed(POP / "X" / f"{tag}.npz", X=R["X"], exp=R["exp"], PM=R["PM"], nsym=R["nsym"])
        D.log(f"  [{tag}] nsym={rec['nsym']} lead={rec['lead']} cp_q={rec['cp_q']:.2f} agree={rec['pilot_agree']:.2f} "
              f"hilo={rec['hilo']:.2f} alt={rec['alt_prod']:.2f} dphi={rec['dphi_deg']:.0f} k4={rec.get('k4', float('nan')):.2f} "
              f"snr={rec['snr_db']}")
    fout.write(json.dumps(rec, default=float) + "\n")
    fout.flush()


def refine_fc(x, fs, fc, t0, t1):
    """Spectrogram band centre is +-100 kHz coarse (200 MS/s: 195 kHz bins); re-centre on the burst PSD."""
    from scipy import signal
    i0, i1 = int(t0 * fs), int(t1 * fs)
    n = np.arange(i0, i1)
    y = x[i0:i1] * np.exp(-2j * np.pi * (fc / fs) * n).astype(np.complex64)
    dn = max(1, int(fs // 25e6))
    y = signal.decimate(y, dn, ftype="fir", zero_phase=False).astype(np.complex64)
    return fc + D.psd_centre(y, fs / dn)


def job_zenodo(fout):
    plan = [("DJI_matrice_100_2G.bin", 20, "M100", "lightbridge"), ("DJI_inspire_2_2G.bin", 8, "Inspire2", "lightbridge"),
            ("DJI_matrice_210_2G.bin", 8, "M210", "lightbridge"), ("DJI_phantom_4_2G.bin", 8, "P4", "lightbridge"),
            ("DJI_phantom_4_pro_plus_2G.bin", 8, "P4P+", "lightbridge"),
            ("DJI_mavic_pro_2G.bin", 3, "MavicPro", "ocusync-label"), ("DJI_mavic_mini_2G.bin", 3, "MavicMini", "ocusync-label"),
            ("DJI_inspire_2_5G_1of2.bin", 4, "Inspire2-5G", "lightbridge"), ("DJI_matrice_210_5G_1of2.bin", 4, "M210-5G", "lightbridge"),
            ("DJI_phantom_4_pro_plus_5G_1of2.bin", 4, "P4P+-5G", "lightbridge")]
    for name, n, dev, kind in plan:
        fs = 200e6 if "5G" in name else 120e6
        x = D.load_zenodo(name)
        bs = D.find_video_bursts(x, fs)
        D.log(f"zenodo {name}: {len(bs)} wide bursts (using bursts 1..{n})")
        if not bs:
            fout.write(json.dumps({"dataset": "zenodo", "device": dev, "kind": kind, "file": name, "no_wide_bursts": True}) + "\n")
        for i, (t0, t1, fc) in enumerate(bs[1:1 + n], start=1):
            fc = refine_fc(x, fs, fc, max(t0, 0.0), t1)
            y, _ = D.to_11p2(x, fs, fc, t0, t1)
            handle(y, f"zen_{dev}_b{i}", {"dataset": "zenodo", "device": dev, "kind": kind, "file": name, "burst": i,
                                          "dur_ms": (t1 - t0) * 1e3, "fc_mhz": fc / 1e6}, fout)
        del x


def job_genesys(fout):
    fs = 10e6
    prev = {"uav1_12ft_burst1_1", "uav2_12ft_burst1_1", "uav3_12ft_burst1_1", "uav4_12ft_burst3_1", "uav4_15ft_burst1_1",
            "uav5_12ft_burst1_1", "uav5_15ft_burst1_1", "uav6_12ft_burst1_1", "uav6_15ft_burst1_1", "uav7_12ft_burst2_1"}
    with zipfile.ZipFile(D.GEN) as z:
        by = {}
        for i in z.infolist():
            if i.filename.endswith(".bin") and i.file_size >= 380000 and Path(i.filename).stem not in prev:
                s = Path(i.filename).stem.split("_")
                by.setdefault((s[0], s[1]), []).append(i)
        rng = np.random.default_rng(7)
        for key in sorted(by):
            info = by[key][int(rng.integers(len(by[key])))]
            x = D.load_genesys_member(z, info.filename)
            x = x - x.mean()
            fc = D.psd_centre(x, fs)
            y, _ = D.to_11p2(x, fs, fc, 0, x.size / fs, pad=0)
            handle(y, "gen_" + Path(info.filename).stem,
                   {"dataset": "genesys", "device": key[0], "dist": key[1], "kind": "lightbridge", "fc_mhz": fc / 1e6}, fout)


def load_ku(zipname, member, nmax):
    import h5py
    d = D.OUT / "ku"
    d.mkdir(parents=True, exist_ok=True)
    dst = d / Path(member).name
    with zipfile.ZipFile(D.KUL / zipname) as z, open(dst, "wb") as f, z.open(member) as src:
        while True:
            b = src.read(1 << 24)
            if not b:
                break
            f.write(b)
    with h5py.File(dst, "r") as h:
        ds = h["uhd_samps"]
        ax = int(np.argmax(ds.shape))
        sl = [slice(None)] * ds.ndim
        sl[ax] = slice(0, nmax)
        a = np.squeeze(ds[tuple(sl)])
    x = (a["real"] + 1j * a["imag"]).astype(np.complex64)
    dst.unlink()
    return x


def job_ku(fout):
    fs = 100e6
    plan = [("inspire2Vid.zip", "inspire2Vid/inspire2_%d.mat" % i, "Inspire2", "lightbridge", 3) for i in (0, 1, 2, 10, 20, 30, 40, 50, 60, 70)]
    plan += [("matricevid.zip", "matricevid/matrice_50.mat", "Matrice300", "ocusync-label", 3),
             ("MavicVid1.zip", "MavicVid1/Mavic_0.mat", "Mavic", "ocusync-label", 2),
             ("mini2vid.zip", "mini2vid/mini2_0.mat", "Mini2", "ocusync-label", 2)]
    for zipname, member, dev, kind, n in plan:
        x = load_ku(zipname, member, 20_000_000)
        x = x - x.mean()
        bs = D.find_video_bursts(x, fs, min_bw=5e6)
        D.log(f"ku {member}: {len(bs)} wide bursts")
        if not bs:
            fout.write(json.dumps({"dataset": "kuleuven", "device": dev, "kind": kind, "file": member, "no_wide_bursts": True}) + "\n")
        for i, (t0, t1, fc) in enumerate(bs[1:1 + n], start=1):
            y, _ = D.to_11p2(x, fs, fc, t0, t1)
            handle(y, f"ku_{dev}_{Path(member).stem}_b{i}",
                   {"dataset": "kuleuven", "device": dev, "kind": kind, "file": member, "burst": i, "dur_ms": (t1 - t0) * 1e3,
                    "fc_mhz": fc / 1e6}, fout)
        del x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True, choices=["zenodo", "genesys", "ku"])
    a = ap.parse_args()
    (D.ROOT / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    D.NRM_FLOOR_REL = 0.05
    D.LOGF = open(D.ROOT / "tmp" / "logs" / f"lightbridge_ofdm_population_{a.job}.log", "w")
    with open(POP / f"pop_{a.job}.jsonl", "w") as fout:
        {"zenodo": job_zenodo, "genesys": job_genesys, "ku": job_ku}[a.job](fout)
    D.log("done")


if __name__ == "__main__":
    main()
