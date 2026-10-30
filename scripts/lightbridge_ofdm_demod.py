#!/usr/bin/env python3
"""Software OFDM demodulator for the DJI Lightbridge video burst from public IQ captures (#165).

Numerology (awto-dji doc, Matrice 100): 11.2 MS/s, FFT 1024, CP 128, 864 used carriers
k=-432..+432 (DC null), 96 pilots (one per 9 carriers, residue (k+432) mod 9 = 5,5,8,8,2,2).

Stages per burst: detect -> mix/resample to 11.2 MS/s -> CP correlation (timing + CFO) ->
FFT -> pilot class + squared-pilot channel fit -> pilot sign recovery -> equalise ->
constellation / EVM, pilot PRBS11 tests, PRBS15 descramble search.
Usage: python3 -I scripts/lightbridge_ofdm_demod.py --source zenodo|genesys|kuleuven [...]
h5py (KU Leuven .mat v7.3) needs /usr/bin/python3, not the free-threaded build.
"""
import argparse
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
from scipy import signal

FS = 11.2e6
NFFT = 1024
NCP = 128
NSYM = NFFT + NCP
KMAX = 432
PILOT_RES = (5, 5, 8, 8, 2, 2)  # (k+432) mod 9 per symbol, period 6
NRM_FLOOR_REL = 0.0  # option: floor the CP-correlation norm at this fraction of its p90 (digital-zero gaps, 5.8 GHz files)


def repo_root():
    env = os.environ.get("PLURIBUS_REPO")
    if env:
        return Path(env)
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             check=True, cwd=Path(__file__).resolve().parent)
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, OSError):
        return Path(__file__).resolve().parents[1]


ROOT = repo_root()
OUT = ROOT / "tmp" / "ofdm"
LOGF = None


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    if LOGF:
        LOGF.write(s + "\n")
        LOGF.flush()


# ------------------------------------------------------------------ sources
ZEN = Path("/mnt/2tb/git/awto-dji/sources/lightbridge-iq/zenodo")
GEN = Path("/mnt/2tb/git/awto-dji/sources/lightbridge-iq/genesys/UAV-M100-Hovering.zip")
KUL = Path("/mnt/2tb/git/awto-dji/sources/lightbridge-iq/kuleuven")


def load_zenodo(name, nsamp=1 << 25):
    raw = np.memmap(ZEN / name, dtype="<i2", mode="r")[: 2 * nsamp]
    return raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)


def load_genesys_member(z, member):
    raw = np.frombuffer(z.read(member), dtype="<f2").astype(np.float32)
    return raw[0::2] + 1j * raw[1::2]


def load_kuleuven(zipname, member, nsamp=None):
    import h5py
    d = OUT / "ku"
    d.mkdir(parents=True, exist_ok=True)
    dst = d / Path(member).name
    if not dst.exists():
        with zipfile.ZipFile(KUL / zipname) as z, open(dst, "wb") as f:
            with z.open(member) as src:
                while True:
                    b = src.read(1 << 24)
                    if not b:
                        break
                    f.write(b)
    with h5py.File(dst, "r") as h:
        ds = h["uhd_samps"]
        n = ds.shape[-1] if ds.ndim > 1 and ds.shape[0] == 1 else ds.shape[0]
        a = ds[...]
    a = np.squeeze(a)
    x = (a["real"] + 1j * a["imag"]).astype(np.complex64)
    return x[:nsamp] if nsamp else x


# ------------------------------------------------------------------ burst detect
def find_video_bursts(x, fs, min_ms=5.0, min_bw=5e6, max_bw=30e6):
    """Spectrogram (floor+10 dB) -> wide long bursts. Returns [(t0, t1, fc)] seconds / Hz."""
    hop = int(fs * 20e-6)
    f, t, S = signal.spectrogram(x, fs=fs, nperseg=1024, noverlap=1024 - hop, return_onesided=False,
                                 mode="psd", window="hann")
    f = np.fft.fftshift(f)
    Sd = 10 * np.log10(np.fft.fftshift(S, axes=0) + 1e-30)
    fl = np.median(Sd)
    on = (Sd > fl + 10).sum(0) >= 8
    e = np.flatnonzero(np.diff(np.concatenate([[0], on.astype(int), [0]])))
    dt = t[1] - t[0]
    out = []
    for s, en in zip(e[::2], e[1::2]):
        if (en - s) * dt * 1e3 < min_ms:
            continue
        prof = Sd[:, s:en].mean(1)
        band = np.flatnonzero(prof > prof.max() - 20)
        runs = np.split(band, np.flatnonzero(np.diff(band) > 2) + 1)
        run = max(runs, key=lambda r: prof[r].sum())
        lo, hi = f[run[0]], f[run[-1]]
        if min_bw <= hi - lo <= max_bw:
            out.append((float(t[s] - dt / 2), float(t[en - 1] + dt / 2), float((lo + hi) / 2)))
    return out


def ratio(fs):
    from fractions import Fraction
    r = Fraction(FS / fs).limit_denominator(2000)
    return r.numerator, r.denominator


def to_11p2(x, fs, fc, t0, t1, pad=0.4e-3):
    """Mix fc to DC, resample to exactly 11.2 MS/s (polyphase). Returns complex64 + abs start time."""
    i0 = max(0, int((t0 - pad) * fs))
    i1 = min(x.size, int((t1 + pad) * fs))
    n = np.arange(i0, i1)
    y = x[i0:i1] * np.exp(-2j * np.pi * (fc / fs) * n).astype(np.complex64)
    up, dn = ratio(fs)
    y = signal.resample_poly(y, up, dn).astype(np.complex64)
    return y, i0 / fs


# ------------------------------------------------------------------ timing / CFO
def cp_metric(y):
    """M[n] = sum_{j<NCP} y[n+j+NFFT] conj(y[n+j]); |M| peaks at symbol (CP) starts."""
    c = y[NFFT:] * np.conj(y[:-NFFT])
    cs = np.concatenate([[0], np.cumsum(c)])
    M = cs[NCP:] - cs[:-NCP]
    p = np.abs(y) ** 2
    ps = np.concatenate([[0], np.cumsum(p)])
    E = ps[NCP:] - ps[:-NCP]
    n = min(M.size, E.size - NFFT)
    return M[:n], np.sqrt(E[:n] * E[NFFT:NFFT + n] + 1e-9)


def coarse_sync(y):
    """Symbol-grid offset s0 (mod NSYM), frac CFO (Hz, within +-df/2), correlation quality."""
    M, nrm = cp_metric(y)
    if NRM_FLOOR_REL > 0:
        nrm = np.maximum(nrm, NRM_FLOOR_REL * np.percentile(nrm, 90))
    rho = np.abs(M) / nrm
    # fold |M| over the burst core (>= half of max energy) at period NSYM
    core = rho > 0.5 * np.percentile(rho, 99)
    idx = np.flatnonzero(core)
    if idx.size < 4 * NSYM:
        return None
    lo, hi = idx[0], idx[-1]
    ph = np.arange(lo, hi) % NSYM
    prof = np.bincount(ph, weights=np.abs(M[lo:hi]), minlength=NSYM)
    prof = np.convolve(np.concatenate([prof[-8:], prof, prof[:8]]), np.ones(9) / 9, "same")[8:-8]
    s0 = int(np.argmax(prof))
    # CFO from M at the peaks (plateau start + a few samples is full-correlation)
    pk = np.arange(lo, hi)
    sel = pk[(pk - s0) % NSYM == 0]
    sel = sel[sel < M.size]
    # M is a sum over exactly NCP samples starting at the CP start: peak = full CP overlap
    ang = np.angle(np.sum(M[sel]))
    cfo = ang * FS / (2 * np.pi * NFFT)
    q = float(np.abs(np.sum(M[sel])) / np.sum(nrm[sel]))
    return s0, float(cfo), q, rho


# ------------------------------------------------------------------ OFDM front end
def used_index():
    """Bin index (fftshift grid, DC at 512) for kidx = 0..864 (k=-432..432)."""
    return NFFT // 2 - KMAX + np.arange(2 * KMAX + 1)


def pilot_sets():
    k = np.arange(2 * KMAX + 1)
    return {r: k[(k % 9 == r) & (k != KMAX)] for r in (5, 8, 2)}


def data_idx():
    k = np.arange(2 * KMAX + 1)
    m = (k != KMAX) & np.isin(k % 9, [5, 8, 2], invert=True)
    # pilots of other classes are data in a given symbol: the per-symbol mask is built in demod
    return k[k != KMAX]


def fft_symbols(y, s_first, nsym, shift_bins, cfo, win_off=96):
    """FFT of nsym symbols; window starts win_off inside each CP. Returns X[m, 0..864] (kidx grid)."""
    n = np.arange(y.size)
    yc = y * np.exp(-2j * np.pi * (cfo / FS) * n).astype(np.complex64)
    X = np.empty((nsym, 2 * KMAX + 1), np.complex64)
    ui = used_index()
    for m in range(nsym):
        a = s_first + m * NSYM + win_off
        if a < 0 or a + NFFT > yc.size:
            X = X[:m]
            break
        F = np.fft.fftshift(np.fft.fft(yc[a:a + NFFT]))
        X[m] = F[ui + shift_bins]
    return X


def find_shift(y, s0, cfo, nsym=40):
    """Integer carrier shift: centre of the occupied span (p90-10 dB) vs bin 512."""
    X = fft_symbols_raw(y, s0, nsym, cfo)
    pw = 10 * np.log10(np.mean(np.abs(X) ** 2, 0) + 1e-30)
    occ = pw > np.percentile(pw, 90) - 10
    idx = np.flatnonzero(occ)
    return int(round((idx[0] + idx[-1]) / 2)) - NFFT // 2, int(occ.sum()), pw


def fft_symbols_raw(y, s_first, nsym, cfo, win_off=96):
    n = np.arange(y.size)
    yc = y * np.exp(-2j * np.pi * (cfo / FS) * n).astype(np.complex64)
    rows = []
    for m in range(nsym):
        a = s_first + m * NSYM + win_off
        if a + NFFT > yc.size:
            break
        rows.append(np.fft.fftshift(np.fft.fft(yc[a:a + NFFT])))
    return np.array(rows)


def burst_edges(y, s0):
    """First/last OFDM symbol index (grid s0 + m*NSYM): per-symbol FFT power and CW-ness."""
    nall = (y.size - s0 - NSYM) // NSYM
    rows = fft_symbols_raw(y, s0, nall, 0.0)
    P = np.abs(rows) ** 2
    tot = P.sum(1)
    pk = P.max(1) / (tot + 1e-30)
    return tot, pk


# ------------------------------------------------------------------ pilots / channel
def sq_fit(Xp, kp, taus=np.arange(-10, 10.01, 0.1)):
    """Fit H(k) ~ a exp(j phi - j 2 pi k tau / N) from X^2 (BPSK pilot sign drops out).

    Returns (tau, phi mod pi, metric = |sum z e^..| / sum|z|, amplitude).
    """
    z = Xp.astype(np.complex128) ** 2
    kc = kp - KMAX
    best = (0.0, 0.0, 0.0)
    ph = np.exp(4j * np.pi * np.outer(taus, kc) / NFFT)
    S = ph @ z
    i = int(np.argmax(np.abs(S)))
    # parabolic refine
    if 0 < i < taus.size - 1:
        a, b, d = np.abs(S[i - 1]), np.abs(S[i]), np.abs(S[i + 1])
        den = a - 2 * b + d
        fr = 0.5 * (a - d) / den if den != 0 else 0.0
    else:
        fr = 0.0
    tau = taus[i] + fr * (taus[1] - taus[0])
    s = np.sum(z * np.exp(4j * np.pi * tau * kc / NFFT))
    return float(tau), float(np.angle(s) / 2), float(np.abs(s) / np.sum(np.abs(z))), float(np.sqrt(np.abs(s) / kp.size))


def detect_pilots(X, nuse=None):
    """Per-symbol pilot class metric for the 3 residue classes. Returns metric[m,3], tau, phi."""
    ps = pilot_sets()
    cls = (5, 8, 2)
    M = X.shape[0]
    met = np.zeros((M, 3))
    for m in range(M):
        for j, r in enumerate(cls):
            met[m, j] = sq_fit(X[m, ps[r]], ps[r])[2]
    return met


def align_pattern(met):
    """Best phase (0..5) of PILOT_RES against per-symbol class metrics. Returns phase, score, per-sym detect."""
    cls = (5, 8, 2)
    ci = {5: 0, 8: 1, 2: 2}
    det = np.array([cls[i] for i in np.argmax(met, 1)])
    best = (-1, 0)
    for ph in range(6):
        exp = np.array([PILOT_RES[(m + ph) % 6] for m in range(met.shape[0])])
        sc = float(np.mean([met[m, ci[exp[m]]] for m in range(met.shape[0])]))
        if sc > best[0]:
            best = (sc, ph)
    ph = best[1]
    exp = np.array([PILOT_RES[(m + ph) % 6] for m in range(met.shape[0])])
    return ph, best[0], det, exp


def track_channel(X, exp_cls):
    """Per-symbol (tau, phi mod pi); no cross-symbol continuity (symbol-to-symbol phase step is ~90 deg, ambiguous mod pi)."""
    ps = pilot_sets()
    M = X.shape[0]
    tau = np.zeros(M)
    phi = np.zeros(M)
    amp = np.zeros(M)
    met = np.zeros(M)
    prev = None
    for m in range(M):
        kp = ps[exp_cls[m]]
        t, p, mt, a = sq_fit(X[m, kp], kp)
        tau[m], phi[m], met[m], amp[m] = t, p, mt, a
    return tau, phi, amp, met


def pilot_signs(X, exp_cls, tau, phi):
    """b = sign(Re(X_p / H_p)), plus residual complex pilot values after de-rotation."""
    ps = pilot_sets()
    M = X.shape[0]
    B = []
    R = []
    for m in range(M):
        kp = ps[exp_cls[m]]
        kc = kp - KMAX
        rot = np.exp(1j * (phi[m] - 2 * np.pi * kc * tau[m] / NFFT))
        v = X[m, kp] / rot
        # amplitude normalise by median |v|
        v = v / (np.median(np.abs(v)) + 1e-30)
        B.append(np.where(v.real >= 0, 1, -1).astype(np.int8))
        R.append(v)
    return B, R


def class_offsets(phi, exp_cls):
    """Diagnostic: mean phase step (deg, mod 180) at pair boundaries minus mean intra-pair step."""
    d = (np.diff(phi) + np.pi / 2) % np.pi - np.pi / 2
    intra = [d[m] for m in range(1, d.size) if exp_cls[m] == exp_cls[m + 1]]
    ref = 0.5 * np.angle(np.mean(np.exp(2j * np.array(intra)))) if intra else 0.0
    out = {}
    for a, b in ((8, 2), (2, 5), (5, 8)):
        v = [d[m] for m in range(1, d.size) if exp_cls[m] == a and exp_cls[m + 1] == b]
        out[f"{a}->{b}"] = float(np.degrees(((0.5 * np.angle(np.mean(np.exp(2j * np.array(v)))) - ref + np.pi / 2) % np.pi) - np.pi / 2)) if v else None
    out["intra_step_deg"] = float(np.degrees(ref))
    return out


def pilot_levels(v):
    """Pilot amplitudes are two-level (~2:1, complementary between the two symbols of a pair): hi/lo split."""
    t0 = np.median(v)
    hi = v > t0
    t = 0.5 * (np.median(v[hi]) + np.median(v[~hi])) if hi.any() and (~hi).any() else t0
    return v > t


def equalise(X, exp_cls, tau, phi, amp_deg=2):
    """Per symbol: H = A(k) exp(j phi - j2pi k tau/N) from this symbol's pilots (hi/lo level normalised,
    sign by sign(Re)). Y = X / H (NaN at DC). Returns Y, pilot mask, pilot signs, pilot rms error,
    hi/lo level fraction per symbol."""
    ps = pilot_sets()
    M = X.shape[0]
    kk = np.arange(2 * KMAX + 1)
    kc = kk - KMAX
    Y = np.full(X.shape, np.nan, np.complex64)
    PM = np.zeros(X.shape, bool)
    SG = np.zeros(X.shape, np.int8)
    PEV = np.zeros(M)
    HI = np.zeros((M, 96), bool)
    for m in range(M):
        kp = ps[exp_cls[m]]
        ref = np.exp(1j * (phi[m] - 2 * np.pi * (kp - KMAX) * tau[m] / NFFT))
        v = X[m, kp] / ref
        sg = np.where(v.real >= 0, 1.0, -1.0)
        a = np.abs(v)
        hi = pilot_levels(a)
        HI[m] = hi
        ratio = np.median(a[hi]) / (np.median(a[~hi]) if (~hi).any() else np.median(a[hi]))
        an = np.where(hi, a, a * ratio)
        c = np.polyfit((kp - KMAX) / KMAX, an, amp_deg)
        PEV[m] = float(np.sqrt(np.mean(np.abs(v * sg * np.where(hi, 1.0, ratio) / np.polyval(c, (kp - KMAX) / KMAX) - 1) ** 2)))
        amp = np.maximum(np.polyval(c, kc / KMAX), 1e-3 * np.max(an))
        H = amp * np.exp(1j * (phi[m] - 2 * np.pi * kc * tau[m] / NFFT))
        Y[m] = X[m] / H
        Y[m, KMAX] = np.nan
        PM[m, kp] = True
        SG[m, kp] = sg.astype(np.int8)
    return Y, PM, SG, PEV, HI


def alamouti_pairs(Y, PM, first=1, step=2):
    """Pairs (m, m+step-1 .. ) -> list of (y1, y2) on carriers that are data in both symbols."""
    out = []
    for m in range(first, Y.shape[0] - 1, 2):
        msk = ~PM[m] & ~PM[m + 1] & ~np.isnan(Y[m]) & ~np.isnan(Y[m + 1])
        out.append((Y[m][msk], Y[m + 1][msk]))
    return out


def alamouti_decode(y1, y2, th, psi):
    a1 = np.cos(th)
    a2 = np.sin(th) * np.exp(1j * psi)
    best = None
    for sg in (1, -1):
        s1 = np.conj(a1) * y1 + a2 * np.conj(sg * y2)
        s2 = np.conj(a2) * y1 - a1 * np.conj(sg * y2)
        z = np.concatenate([s1, s2])
        z = z / np.sqrt(np.mean(np.abs(z) ** 2))
        k4 = float(np.mean(np.abs(z) ** 4))
        if best is None or k4 < best[0]:
            best = (k4, z)
    return best


def alamouti_scan(Y, PM, npair=24):
    """Global (theta, psi) grid for the 2-TX Alamouti hypothesis on symbol pairs (1,2),(3,4)..; control = the
    same decode on non-pairs (m, m+3). Metric: mean kurtosis E|s|^4/E|s|^2^2 (lower = more lattice-like)."""
    pr = alamouti_pairs(Y, PM, 1)[5:5 + npair]
    ctl = []
    for m in range(6, 6 + 2 * npair, 2):
        if m + 3 < Y.shape[0]:
            msk = ~PM[m] & ~PM[m + 3] & ~np.isnan(Y[m]) & ~np.isnan(Y[m + 3])
            ctl.append((Y[m][msk], Y[m + 3][msk]))
    grid_t = np.linspace(0.02, np.pi / 2 - 0.02, 20)
    grid_p = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    best = (9.0, 0, 0)
    for t in grid_t:
        for p in grid_p:
            k = np.mean([alamouti_decode(a, b, t, p)[0] for a, b in pr])
            if k < best[0]:
                best = (float(k), float(t), float(p))
    kc = np.mean([alamouti_decode(a, b, best[1], best[2])[0] for a, b in ctl]) if ctl else float("nan")
    return {"k4_pairs": best[0], "theta": best[1], "psi": best[2], "k4_control_pairs": float(kc)}


# ------------------------------------------------------------------ burst demod
def demod_burst(y, tag):
    """Full front end on a resampled burst. Returns dict (X, Y, masks, params) or None."""
    cs = coarse_sync(y)
    if cs is None:
        log(f"  [{tag}] no CP correlation")
        return None
    s0, cfo, q, rho = cs
    tot, pk = burst_edges(y, s0)
    if tot.size < 20:
        return None
    ofdm = pk < 0.1
    core = np.median(tot[ofdm]) if ofdm.any() else 0
    good = ofdm & (tot > 0.3 * core)
    idx = np.flatnonzero(good)
    if idx.size < 20:
        log(f"  [{tag}] too few OFDM symbols")
        return None
    # longest run of good symbols
    runs = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
    run = max(runs, key=len)
    m0, m1 = int(run[0]), int(run[-1])
    nsym = m1 - m0 + 1
    first = s0 + m0 * NSYM
    sh0, nocc, pw = find_shift(y, first + 8 * NSYM, cfo)
    df = FS / NFFT
    best = None
    for sh in range(sh0 - 3, sh0 + 4):
        c2 = cfo + sh * df
        Fr = fft_symbols_raw(y, first + 8 * NSYM, 16, c2)
        if Fr.shape[0] < 8:
            continue
        P = 10 * np.log10(np.mean(np.abs(Fr) ** 2, 0) + 1e-30)
        on = np.flatnonzero(P > np.median(P[300:700]) - 10)
        err = abs(int(on[0]) - (NFFT // 2 - KMAX)) + abs(int(on[-1]) - (NFFT // 2 + KMAX))
        if best is None or err < best[0]:
            best = (err, sh, c2)
    err, sh, c2 = best
    X = fft_symbols(y, first, nsym, 0, c2)
    met = detect_pilots(X)
    ph, sc, det, exp = align_pattern(met)
    tau, phi, amp, mt = track_channel(X, exp)
    theta = class_offsets(phi, exp)
    Y, PM, SG, PEV, HI = equalise(X, exp, tau, phi)
    agree = float(np.mean(det[1:] == exp[1:]))
    return {"X": X, "Y": Y, "PM": PM, "SG": SG, "exp": exp, "det": det, "met": met, "tau": tau, "phi": phi,
            "theta": theta, "nsym": X.shape[0], "m0": m0, "s0": s0, "cfo_frac": cfo, "shift": sh,
            "occ_bins": nocc, "edge_err": err, "pev": PEV, "HI": HI, "cp_q": q, "pat_score": sc, "pat_phase": ph, "pat_agree": agree,
            "cfo_total": c2, "cfo_frac_hz": cfo, "tot_db": 10 * np.log10(tot[m0:m0 + X.shape[0]] + 1)}


def symbol_features(R, nfirst=8):
    X, Y, PM = R["X"], R["Y"], R["PM"]
    rows = []
    for m in range(min(nfirst, X.shape[0])):
        a = np.abs(X[m]) ** 2
        a = np.delete(a, KMAX)
        k = np.delete(np.arange(2 * KMAX + 1), KMAX)
        sh = [a[k % 3 == q].sum() / a.sum() for q in range(3)]
        y = Y[m][~PM[m] & ~np.isnan(Y[m])]
        yn = y / np.sqrt(np.mean(np.abs(y) ** 2))
        rows.append({"m": m, "tot_db": float(R["tot_db"][m]), "share_mod3": [round(float(s), 2) for s in sh],
                     "mod_cv": float(np.std(np.abs(yn)) / np.mean(np.abs(yn))),
                     "k4": float(np.mean(np.abs(yn) ** 4)), "pilot_met": [round(float(v), 2) for v in R["met"][m]]})
    return rows


def zc_test(Yrow):
    """Constant-modulus symbol: concentration of the 2nd phase difference (Zadoff-Chu -> constant)."""
    z = Yrow[~np.isnan(Yrow)]
    d2 = z[2:] * z[:-2] / (z[1:-1] ** 2 + 1e-30)
    return float(np.abs(np.mean(d2 / np.abs(d2)))), float(np.angle(np.mean(d2 / np.abs(d2))))


# ------------------------------------------------------------------ constellation / EVM
def grid(mod):
    if mod == "QPSK":
        a = np.array([-1, 1])
    elif mod == "16QAM":
        a = np.array([-3, -1, 1, 3])
    else:
        a = np.array([-7, -5, -3, -1, 1, 3, 5, 7])
    g = (a[:, None] + 1j * a[None, :]).ravel()
    return g / np.sqrt(np.mean(np.abs(g) ** 2))


def evm_best_rot(y, g, nrot=90):
    """Min over a constant rotation (class offsets leave a phase ambiguity) of nearest-point rms error."""
    best = 9.0
    for a in np.linspace(0, np.pi / 2, nrot, endpoint=False):
        z = y * np.exp(1j * a)
        d = np.abs(z[:, None] - g[None, :]).min(1)
        e = float(np.sqrt(np.mean(d ** 2)))
        best = min(best, e)
    return best


def constellation_report(R, tag, rng):
    Y, PM = R["Y"], R["PM"]
    pts = {}
    for m in range(1, Y.shape[0]):
        y = Y[m][~PM[m] & ~np.isnan(Y[m])]
        pts[m] = y / np.sqrt(np.mean(np.abs(y) ** 2))
    allp = np.concatenate([pts[m] for m in range(12, Y.shape[0] - 1)])
    k4 = float(np.mean(np.abs(allp) ** 4))
    m4 = float(abs(np.mean(allp ** 4)) / np.mean(np.abs(allp) ** 4))
    cv = float(np.std(np.abs(allp)) / np.mean(np.abs(allp)))
    # pilot EVM (BPSK), model residual
    pe = float(np.sqrt(np.mean(R['pev'][1:] ** 2)))
    # EVM per modulation on a 4000-point subsample + Gaussian null of equal size
    sub = allp[rng.choice(allp.size, min(4000, allp.size), replace=False)]
    null = (rng.standard_normal(sub.size) + 1j * rng.standard_normal(sub.size)) / np.sqrt(2)
    evm = {mod: evm_best_rot(sub, grid(mod)) for mod in ("QPSK", "16QAM", "64QAM")}
    evm_null = {mod: evm_best_rot(null, grid(mod)) for mod in ("QPSK", "16QAM", "64QAM")}
    # early vs late
    early = np.concatenate([pts[m] for m in range(3, 9) if m in pts])
    late = np.concatenate([pts[m] for m in range(60, min(90, Y.shape[0] - 1)) if m in pts])
    al = alamouti_scan(Y, PM)
    hi = R["HI"][1:]
    lv = {"hi_frac": float(hi.mean()), "ratio_hi_lo": float(np.median([np.median(np.abs(R["X"][m, np.flatnonzero(PM[m])])[hi[m - 1]]) / max(1e-9, np.median(np.abs(R["X"][m, np.flatnonzero(PM[m])])[~hi[m - 1]])) for m in range(1, Y.shape[0])]))}
    return {"alamouti": al, "pilot_levels": lv, "k4": k4, "m4": m4, "amp_cv": cv, "pilot_evm": pe, "evm": evm, "evm_gauss_null": evm_null,
            "k4_early": float(np.mean(np.abs(early) ** 4)), "k4_late": float(np.mean(np.abs(late) ** 4))}


def pair_stats(R):
    """Consecutive-symbol structure at a shared carrier (data in both): power correlation and pair-sum CV.
    Alamouti-like pairing -> negative power correlation / lower sum CV at the right pair alignment."""
    Y, PM = R["Y"], R["PM"]
    out = {}
    for name, first in (("odd_even(1,2)(3,4)", 1), ("even_odd(2,3)(4,5)", 2)):
        cc, cv = [], []
        for m in range(first + 4, Y.shape[0] - 2, 2):
            ok = ~PM[m] & ~PM[m + 1] & ~np.isnan(Y[m]) & ~np.isnan(Y[m + 1])
            a, b = np.abs(Y[m][ok]) ** 2, np.abs(Y[m + 1][ok]) ** 2
            cc.append(np.corrcoef(a, b)[0, 1])
            cv.append(np.std(a + b) / np.mean(a + b))
        out[name] = {"power_corr": float(np.mean(cc)), "pair_sum_cv": float(np.mean(cv))}
        # pilots: sign(r1) sign(r2) * (hi at first symbol ? +1 : -1) constant over the pair -> Alamouti pilot pair
        pc = []
        for m in range(first, Y.shape[0] - 1, 2):
            if not np.array_equal(np.flatnonzero(PM[m]), np.flatnonzero(PM[m + 1])):
                continue
            kp = np.flatnonzero(PM[m])
            a = R["SG"][m][kp] * R["SG"][m + 1][kp] * np.where(R["HI"][m], 1.0, -1.0)
            pc.append(abs(a.mean()))
        out[name]["pilot_pair_sign_hilo_consistency"] = float(np.mean(pc)) if pc else None
    return out


def k4_by_symbol(R):
    Y, PM = R["Y"], R["PM"]
    out = []
    for m in range(Y.shape[0]):
        y = Y[m][~PM[m] & ~np.isnan(Y[m])]
        yn = y / np.sqrt(np.mean(np.abs(y) ** 2))
        out.append(float(np.mean(np.abs(yn) ** 4)))
    return out


# ------------------------------------------------------------------ PRBS
def lfsr(taps, seed, n):
    """Fibonacci LFSR, stage 1 = feedback input, output = last stage. seed[0] = stage 1."""
    L = len(seed)
    s = list(seed)
    out = np.empty(n, np.uint8)
    for i in range(n):
        out[i] = s[-1]
        fb = 0
        for t in taps:
            fb ^= s[t - 1]
        s = [fb] + s[:-1]
    return out


def bits(sstr):
    return [int(c) for c in sstr]


SEEDS11 = {"ones": [1] * 11, "10110101110": bits("10110101110"), "00000101111": bits("00000101111")}
POLY11 = {"x11+x9+1": (11, 9), "x11+x2+1(recip)": (11, 2)}


def mseq_offsets_corr(sgn, P):
    """Correlation of +-1 vector sgn (len n) with every circular offset of +-1 sequence P (len L)."""
    L = P.size
    n = sgn.size
    a = np.zeros(L)
    a[:n] = sgn
    # c[o] = sum_j a[j] P[(o+j) % L]
    return np.fft.ifft(np.fft.fft(P) * np.conj(np.fft.fft(a))).real


def pilot_prbs_tests(R, tag, out):
    """Pilot BPSK sign vs PRBS11 candidates. Signs are known up to a constant per class (sym-invariant test)."""
    exp = R["exp"]
    SG, PM = R["SG"], R["PM"]
    M = SG.shape[0]
    vecs = {}
    for m in range(1, M):
        kp = np.flatnonzero(PM[m])
        vecs[m] = (SG[m][kp].astype(float), kp)
    out["pilot_n"] = M - 1
    # model-free: mean sign, correlation between symbols sharing a class/pair
    ms = np.array([abs(v[0].mean()) for v in vecs.values()])
    out["pilot_mean_sign_abs"] = float(ms.mean())
    for lag in (1, 6):
        cs = [abs(np.mean(vecs[m][0] * vecs[m + lag][0])) for m in range(1, M - lag)
              if exp[m] == exp[m + lag] and np.array_equal(vecs[m][1], vecs[m + lag][1])]
        out[f"pilot_corr_lag{lag}"] = (float(np.mean(cs)) if cs else None, len(cs))
    # all-offset search per symbol against PRBS11 (both polys), strides over k
    res = {}
    for pname, taps in POLY11.items():
        P = 1 - 2 * lfsr(taps, [1] * 11, 2047).astype(float)
        for mode, stride in (("consec", 1), ("abs_k", 9)):
            zs, offs = [], []
            for m, (v, kp) in vecs.items():
                if mode == "consec":
                    base = v
                    idx = np.arange(v.size)
                else:
                    base = v
                    idx = kp  # PRBS clocked per used subcarrier index
                best = (0.0, 0)
                for rev in (False, True):
                    vv = v[::-1] if rev else v
                    ii = (idx[::-1] if rev else idx)
                    # candidate bits P[(o + ii) mod L]; correlation over o via explicit loop in chunks
                    O = (np.arange(2047)[:, None] + ii[None, :]) % 2047
                    c = np.abs((P[O] * vv[None, :]).sum(1))
                    j = int(np.argmax(c))
                    if c[j] > best[0]:
                        best = (float(c[j]), j)
                zs.append(best[0] / np.sqrt(v.size))
                offs.append(best[1])
            zs = np.array(zs)
            res[f"{pname}/{mode}"] = {"mean_best_z": float(zs.mean()), "max_best_z": float(zs.max()),
                                      "n_sym_z_gt_5": int((zs > 5).sum()), "n": int(zs.size),
                                      "null_mean_best_z_approx": 3.4}
    out["pilot_prbs11"] = res
    # explicit seeds: restart-per-symbol / per-burst continuous, matches per symbol (sign-invariant)
    seedres = {}
    for sname, seed in SEEDS11.items():
        seq = lfsr((11, 9), seed, 2047 * 2)
        for mode in ("restart_sym_consec", "restart_sym_absk", "burst_consec", "burst_allk"):
            mm = []
            for m, (v, kp) in vecs.items():
                if mode == "restart_sym_consec":
                    ii = np.arange(v.size)
                elif mode == "restart_sym_absk":
                    ii = kp
                elif mode == "burst_consec":
                    ii = (m - 1) * 96 + np.arange(v.size)
                else:
                    ii = (m - 1) * 865 + kp
                b = 1 - 2 * seq[ii % 2047].astype(float)
                match = int(np.sum(b == v))
                mm.append(max(match, v.size - match))
            seedres[f"{sname}/{mode}"] = {"mean_match": float(np.mean(mm)), "max_match": int(np.max(mm)),
                                          "of": int(v.size)}
    out["pilot_seed_tests"] = seedres
    # best-offset-per-symbol difference histogram for continuous-clock detection
    return out


# ------------------------------------------------------------------ data bits / descramble search
def data_bit_streams(R):
    """QPSK-slicing hard bits (8 mapping variants: swap x 4 rotations); list per symbol per variant."""
    Y, PM = R["Y"], R["PM"]
    variants = []
    for swap in (0, 1):
        for rot in range(4):
            variants.append((swap, rot))
    streams = {v: [] for v in variants}
    for m in range(3, Y.shape[0] - 1):
        sel = ~PM[m] & ~np.isnan(Y[m])
        y = Y[m][sel]
        for (swap, rot) in variants:
            z = y * np.exp(1j * rot * np.pi / 2)
            bi = (z.real < 0).astype(np.uint8)
            bq = (z.imag < 0).astype(np.uint8)
            b = np.stack([bq, bi] if swap else [bi, bq], axis=1).ravel()
            streams[(swap, rot)].append(b)
    return streams


def words(b, n):
    """n-bit sliding words (MSB first) of 0/1 array b."""
    L = b.size - n + 1
    w = np.zeros(L, np.uint64)
    for j in range(n):
        w = (w << np.uint64(1)) | b[j:j + L].astype(np.uint64)
    return w


def bitrev_bytes(val, nbits):
    out = 0
    for i in range(nbits // 8):
        byte = (val >> (8 * (nbits // 8 - 1 - i))) & 0xFF
        r = int(f"{byte:08b}"[::-1], 2)
        out = (out << 8) | r
    return out


PATTERNS = {"00000001": (0x00000001, 32), "55CC": (0x55CC, 16)}


def descramble_search(streams, tag, out):
    """PRBS15 (x^15+x^14+1, seed 100101010000000, stage1=feedback input) keystream, every bit offset.

    Match test: data word ^ pattern == keystream word at offset n -> offset o = n - i.
    Modes: restart per symbol (offset shared by all symbols) and per burst (one stream).
    Reports hits and the largest same-offset recurrence vs chance. Also the alignment-free filter
    e[n] = r[n]^r[n-14]^r[n-15] (keystream cancels): fraction of zero bits and longest zero run.
    """
    L = 32767
    ks = lfsr((15, 14), bits("100101010000000"), L + 40)
    res = {}
    for var, syms in streams.items():
        vname = f"swap{var[0]}rot{var[1]}"
        r = {}
        # alignment-free filter on the burst stream
        burst = np.concatenate(syms)
        e = burst[15:] ^ burst[1:-14] ^ burst[:-15]
        zf = float(np.mean(e == 0))
        # longest zero run
        z = np.concatenate([[1], (e == 0).astype(np.int8), [1]])
        d = np.diff(z)
        st, en = np.flatnonzero(d == -1), np.flatnonzero(d == 1)
        longest = int((en - st).max()) if st.size else 0
        r["filter_zero_frac"] = zf
        r["filter_longest_zero_run"] = longest
        r["raw_zero_frac"] = float(np.mean(burst == 0))
        for pname, (pat, nb) in PATTERNS.items():
            for order in ("msb", "lsb"):
                pv = pat if order == "msb" else bitrev_bytes(pat, nb)
                W = words(ks, nb)[:L]
                srt = np.argsort(W, kind="stable")
                Ws = W[srt]
                for mode in ("symbol", "burst"):
                    offs = []
                    nhits = 0
                    streams_ = syms if mode == "symbol" else [burst]
                    for s in streams_:
                        D = words(s, nb) ^ np.uint64(pv)
                        lo = np.searchsorted(Ws, D, side="left")
                        hi = np.searchsorted(Ws, D, side="right")
                        for i in np.flatnonzero(hi > lo):
                            for n in srt[lo[i]:hi[i]]:
                                offs.append((int(n) - int(i)) % L)
                        nhits += int((hi - lo).sum())
                    nwin = sum(max(0, s.size - nb + 1) for s in streams_)
                    chance = nwin * (L / 2.0 ** nb)
                    top = 0
                    if offs:
                        _, cnt = np.unique(offs, return_counts=True)
                        top = int(cnt.max())
                    r[f"{pname}/{order}/{mode}"] = {"hits": nhits, "chance": round(chance, 1), "max_same_offset": top}
        res[vname] = r
    out["descramble"] = res
    return out


# ------------------------------------------------------------------ drivers
def psd_centre(x, fs):
    f, p = signal.welch(x, fs=fs, nperseg=2048, return_onesided=False)
    f = np.fft.fftshift(f)
    p = np.fft.fftshift(p)
    ps = np.convolve(p, np.ones(9) / 9, "same")
    db = 10 * np.log10(ps + 1e-30)
    on = np.flatnonzero(db > db.max() - 15)
    return float((f[on[0]] + f[on[-1]]) / 2)


def process(y, tag, dataset, rng, plots):
    R = demod_burst(y, tag)
    if R is None:
        return None
    out = {"tag": tag, "dataset": dataset, "nsym": R["nsym"], "cfo_total_hz": R["cfo_total"],
           "shift_bins": R["shift"], "occupied_bins": R["occ_bins"], "cp_corr": R["cp_q"],
           "pilot_pattern_phase": R["pat_phase"], "pilot_pattern_score": R["pat_score"],
           "pilot_class_agree": R["pat_agree"], "class_steps_deg": R["theta"], "edge_err": R["edge_err"],
           "tau_samples_median": float(np.median(R["tau"][1:])), "lead_symbols_before_ofdm": R["m0"]}
    out["features_first8"] = symbol_features(R)
    out["zc_sym1_2"] = [zc_test(R["Y"][m]) for m in (1, 2) if m < R["nsym"]]
    if R["nsym"] > 30:
        out["constellation"] = constellation_report(R, tag, rng)
        out["pair_stats"] = pair_stats(R)
        log("    pair stats " + json.dumps({k: {a: (None if b is None else round(b, 3)) for a, b in v.items()} for k, v in out["pair_stats"].items()}))
        out["k4_by_symbol"] = [round(v, 2) for v in k4_by_symbol(R)]
        pilot_prbs_tests(R, tag, out)
        descramble_search(data_bit_streams(R), tag, out)
    log(f"  [{tag}] nsym={R['nsym']} lead={R['m0']} cfo={R['cfo_total']:+.0f} Hz shift={R['shift']:+d} "
        f"edge_err={R['edge_err']} pilot-class agree={R['pat_agree']:.3f} (phase {R['pat_phase']}) "
        f"class steps deg {R['theta']}")
    if "constellation" in out:
        c = out["constellation"]
        log(f"    data k4={c['k4']:.3f} (QPSK 1.0, 16QAM 1.32, 64QAM 1.38, Gauss 2.0) |E y^4|/E|y|^4={c['m4']:.3f} "
            f"|y|CV={c['amp_cv']:.3f} pilot EVM={c['pilot_evm']:.3f}")
        log("    EVM data (best rot) " + " ".join(f"{k}={v:.3f}(gauss null {c['evm_gauss_null'][k]:.3f})" for k, v in c["evm"].items()))
        al = c["alamouti"]
        log(f"    pilot hi/lo level ratio={c['pilot_levels']['ratio_hi_lo']:.2f} hi_frac={c['pilot_levels']['hi_frac']:.2f}; "
            f"Alamouti-pair scan: k4={al['k4_pairs']:.3f} at theta={al['theta']:.2f} psi={al['psi']:.2f} vs control pairing {al['k4_control_pairs']:.3f}")
        log(f"    k4 early(sym3-8)={c['k4_early']:.2f} late(60-89)={c['k4_late']:.2f}")
    if plots:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        Y, PM = R["Y"], R["PM"]
        fig, ax = plt.subplots(1, 3, figsize=(15, 5))
        for a, m in zip(ax[:2], (1, min(20, R["nsym"] - 1))):
            z = Y[m][~np.isnan(Y[m])]
            z = z / np.sqrt(np.mean(np.abs(z) ** 2))
            a.plot(z.real, z.imag, ".", ms=2)
            a.set_xlim(-2.5, 2.5)
            a.set_ylim(-2.5, 2.5)
            a.set_aspect("equal")
            a.set_title(f"{tag} sym {m}")
        pts = np.concatenate([Y[m][~PM[m] & ~np.isnan(Y[m])] for m in range(12, R["nsym"] - 1)])
        pts = pts / np.sqrt(np.mean(np.abs(pts) ** 2))
        ax[2].hist2d(pts.real, pts.imag, bins=160, range=[[-2.5, 2.5], [-2.5, 2.5]], cmap="magma")
        ax[2].set_aspect("equal")
        ax[2].set_title("data, symbols 12..end")
        fig.tight_layout()
        fig.savefig(OUT / f"const_{dataset}_{tag}.png", dpi=80)
        plt.close(fig)
    return out


def run_zenodo(n, results, rng, name="DJI_matrice_100_2G.bin", first=0):
    fs = 120e6
    x = load_zenodo(name)
    bs = find_video_bursts(x, fs)
    log(f"zenodo {name}: {len(bs)} wide bursts in first 2^25 samples")
    # skip the first (truncated at capture start)
    for i, (t0, t1, fc) in enumerate(bs[1:1 + n], start=1):
        y, _ = to_11p2(x, fs, fc, t0, t1)
        r = process(y, f"zen_{Path(name).stem}_b{i}", "zenodo", rng, plots=(i <= 2))
        if r:
            r["fc_offset_mhz"] = fc / 1e6
            r["dur_ms"] = (t1 - t0) * 1e3
            results.append(r)


def run_genesys(n, results, rng):
    fs = 10e6
    with zipfile.ZipFile(GEN) as z:
        names = [i for i in z.infolist() if i.filename.endswith(".bin") and i.file_size >= 380000]
        picked, seen = [], {}
        for info in sorted(names, key=lambda i: i.filename):
            stem = Path(info.filename).stem
            uav = stem.split("_")[0]
            dist = stem.split("_")[1]
            key = (uav, dist)
            if seen.get(uav, 0) >= (1 if len(seen) < 7 else 2) or key in seen:
                continue
            seen[uav] = seen.get(uav, 0) + 1
            seen[key] = 1
            picked.append(info)
            if len(picked) >= n:
                break
        log(f"genesys: {len(picked)} full-length bursts picked: {[Path(i.filename).stem for i in picked]}")
        for j, info in enumerate(picked):
            x = load_genesys_member(z, info.filename)
            x = x - x.mean()
            fc = psd_centre(x, fs)
            y, _ = to_11p2(x, fs, fc, 0, x.size / fs, pad=0)
            r = process(y, "gen_" + Path(info.filename).stem, "genesys", rng, plots=(j < 2))
            if r:
                r["fc_offset_mhz"] = fc / 1e6
                results.append(r)


def run_kuleuven(n, results, rng, zipname="inspire2Vid.zip"):
    fs = 100e6
    with zipfile.ZipFile(KUL / zipname) as z:
        member = [i.filename for i in z.infolist() if i.filename.endswith(".mat")][0]
    x = load_kuleuven(zipname, member)
    log(f"kuleuven {zipname}:{member}: {x.size} samples ({x.size / fs * 1e3:.0f} ms)")
    x = x - x.mean()
    bs = find_video_bursts(x, fs, min_bw=5e6)
    log(f"  {len(bs)} wide bursts")
    for i, (t0, t1, fc) in enumerate(bs[1:1 + n], start=1):
        y, _ = to_11p2(x, fs, fc, t0, t1)
        r = process(y, f"ku_{Path(member).stem}_b{i}", "kuleuven", rng, plots=(i == 1))
        if r:
            r["fc_offset_mhz"] = fc / 1e6
            results.append(r)


def summarise(results):
    log("=== consistency summary ===")
    for ds in ("zenodo", "genesys", "kuleuven"):
        rs = [r for r in results if r["dataset"] == ds]
        if not rs:
            continue
        def stat(f):
            v = np.array([f(r) for r in rs if f(r) is not None], float)
            return f"{v.mean():.3f}+-{v.std():.3f} [{v.min():.3f},{v.max():.3f}]" if v.size else "n/a"
        log(f"{ds}: n={len(rs)} nsym {stat(lambda r: r['nsym'])}; pilot-class agree {stat(lambda r: r['pilot_class_agree'])}; "
            f"pattern phase set {sorted(set(r['pilot_pattern_phase'] for r in rs))}")
        log(f"  edge_err {stat(lambda r: r['edge_err'])}; k4 {stat(lambda r: r['constellation']['k4'] if 'constellation' in r else None)}; "
            f"pilot EVM {stat(lambda r: r['constellation']['pilot_evm'] if 'constellation' in r else None)}; "
            f"EVM QPSK/16/64 {stat(lambda r: r['constellation']['evm']['QPSK'] if 'constellation' in r else None)} / "
            f"{stat(lambda r: r['constellation']['evm']['16QAM'] if 'constellation' in r else None)} / "
            f"{stat(lambda r: r['constellation']['evm']['64QAM'] if 'constellation' in r else None)}")


def main():
    global LOGF
    ap = argparse.ArgumentParser()
    ap.add_argument("--zenodo", type=int, default=8)
    ap.add_argument("--genesys", type=int, default=10)
    ap.add_argument("--kuleuven", type=int, default=2)
    ap.add_argument("--zenodo-file", default="DJI_matrice_100_2G.bin")
    ap.add_argument("--ku-zip", default="inspire2Vid.zip")
    ap.add_argument("--tag", default="run")
    a = ap.parse_args()
    (ROOT / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    LOGF = open(ROOT / "tmp" / "logs" / "lightbridge_ofdm_demod.log", "a")
    from datetime import datetime
    log(f"=== lightbridge_ofdm_demod {datetime.now().astimezone().isoformat(timespec='seconds')} args={vars(a)}")
    rng = np.random.default_rng(1)
    results = []
    if a.zenodo:
        run_zenodo(a.zenodo, results, rng, a.zenodo_file)
    if a.genesys:
        run_genesys(a.genesys, results, rng)
    if a.kuleuven:
        run_kuleuven(a.kuleuven, results, rng, a.ku_zip)
    summarise(results)
    (OUT / f"results_{a.tag}.json").write_text(json.dumps(results, indent=1, default=float))
    log(f"json -> {OUT / f'results_{a.tag}.json'}")


if __name__ == "__main__":
    main()
