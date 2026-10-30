#!/usr/bin/env python3
"""Two last constellation hypotheses for the Lightbridge OFDM data carriers (#165).

Variant 1: per-carrier channel taken from training symbols 1-2 (assumed constant modulus) instead of / in
  addition to the pilot model; kurtosis, 4th-power coherence, modulus CV and EVM per equaliser.
Variant 2: pair combining z = y1 + sigma*a(k)*conj(y2) with per-carrier complex a(k) found by a blind
  4th-power coherence search (per-pair sign sigma refined iteratively); control pairing (m, m+3), Gaussian
  null and a simulated Alamouti 16QAM positive control run through the identical pipeline.
Input: tmp/ofdm_pop/X/<tag>.npz from lightbridge_ofdm_population.py. Output: tmp/ofdm_pop/precoder_<tag>.json.
Usage: python3 -I scripts/lightbridge_ofdm_precoder_test.py TAG [TAG ...] | --control
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lightbridge_ofdm_demod as D  # noqa: E402

POP = D.ROOT / "tmp" / "ofdm_pop"
RNG = np.random.default_rng(3)
KC = np.arange(865) - 432
AGRID = (np.logspace(np.log10(0.2), np.log10(5), 15)[:, None] * np.exp(1j * np.linspace(0, 2 * np.pi, 40, endpoint=False))[None, :]).ravel()


def stats(z, nrot=45):
    """Normalised kurtosis, 4th-power coherence, modulus CV, EVM best rotation (QPSK/16/64)."""
    z = z[np.isfinite(z)]
    z = z / np.sqrt(np.mean(np.abs(z) ** 2))
    sub = z[RNG.choice(z.size, min(4000, z.size), replace=False)]
    return {"n": int(z.size), "k4": float(np.mean(np.abs(z) ** 4)), "m4": float(abs(np.mean(z ** 4)) / np.mean(np.abs(z) ** 4)),
            "cv": float(np.std(np.abs(z)) / np.mean(np.abs(z))),
            "evm": {m: round(D.evm_best_rot(sub, D.grid(m), nrot), 3) for m in ("QPSK", "16QAM", "64QAM")}}


def common_phase_fix(Yc, PM, m):
    """Remove per-symbol common phase (mod 90 deg ambiguity kept) from pilots of symbol m."""
    p = Yc[m][PM[m]]
    p = p[np.isfinite(p)]
    return np.exp(-0.5j * np.angle(np.mean(p ** 2))) if p.size else 1.0


def variant1(X, exp, PM, m0=5):
    tau, phi, amp, met = D.track_channel(X, exp)
    Y_A, PM, SG, PEV, HI = D.equalise(X, exp, tau, phi)
    nsym = X.shape[0]
    dm = list(range(m0, nsym - 1))
    ok = np.ones(865, bool)
    ok[432] = False
    g1, g2 = np.abs(X[1]), np.abs(X[2])
    gT = {"sym1": g1, "sym2": g2, "sym12": np.sqrt(0.5 * (g1 ** 2 + g2 ** 2))}
    # pilot-static gain: mean |X|^2 over the symbols of each pilot class at its pilot carriers, interpolated
    ps = D.pilot_sets()
    kk, vv = [], []
    for c, ks in ps.items():
        ms = [m for m in range(3, nsym - 1) if exp[m] == c]
        if ms:
            kk.append(ks)
            vv.append(np.sqrt(np.mean(np.abs(X[ms][:, ks]) ** 2, 0)))
    kk, vv = np.concatenate(kk), np.concatenate(vv)
    o = np.argsort(kk)
    gP = np.interp(np.arange(865), kk[o], vv[o])
    res = {}

    def collect(name, Yf):
        pts = []
        for m in dm:
            msk = ~PM[m] & ok & np.isfinite(Yf[m])
            y = Yf[m][msk] * common_phase_fix(Yf, PM, m)
            pts.append(y / np.sqrt(np.mean(np.abs(y) ** 2)))
        res[name] = stats(np.concatenate(pts))

    collect("pilot_model(existing)", Y_A)
    base_phase = np.exp(1j * (phi[:, None] - 2 * np.pi * KC[None, :] * tau[:, None] / 1024))
    for nm, g in gT.items():
        collect(f"train_mag[{nm}]+pilot_phase", X / (g[None, :] * base_phase + 1e-30))
        collect(f"train_mag+phase[{nm}]", X / (g[None, :] * np.exp(1j * np.angle(X[int(nm[-1]) if nm != "sym12" else 1]))[None, :] + 1e-30))
    collect("pilot_static_gain+pilot_phase", X / (gP[None, :] * base_phase + 1e-30))
    # modulus-only (phase-free) equalisers
    for nm, g in (("train_sym12", gT["sym12"]), ("pilot_static", gP)):
        a = np.concatenate([np.abs(X[m][~PM[m] & ok]) / g[~PM[m] & ok] for m in dm])
        a = a / np.sqrt(np.mean(a ** 2))
        res[f"modulus_only[{nm}]"] = {"k4": float(np.mean(a ** 4)), "cv": float(np.std(a) / np.mean(a))}
    # per-carrier 4th-power coherence across symbols (phase-rotation-per-carrier hypothesis), pilot-equalised Y_A
    coh = []
    for k in range(865):
        if k == 432:
            continue
        ys = np.array([Y_A[m, k] for m in dm if not PM[m, k] and np.isfinite(Y_A[m, k])])
        if ys.size >= 20:
            ys = ys / np.sqrt(np.mean(np.abs(ys) ** 2))
            coh.append(abs(np.mean(ys ** 4)) / np.mean(np.abs(ys) ** 4))
    g = (RNG.standard_normal((len(dm), 200)) + 1j * RNG.standard_normal((len(dm), 200)))
    gn = np.abs(np.mean(g ** 4, 0)) / np.mean(np.abs(g) ** 4, 0)
    res["per_carrier_m4_over_time"] = {"median": float(np.median(coh)), "p95": float(np.percentile(coh, 95)),
                                       "gauss_null_median": float(np.median(gn)), "gauss_null_p95": float(np.percentile(gn, 95)), "ncar": len(coh)}
    return res


def pair_arrays(Y, PM, first, step):
    """Pairs (m, m+step) for m = first, first+2, ...; invalid -> NaN."""
    y1, y2 = [], []
    for m in range(first, Y.shape[0] - step - 1, 2):
        bad = PM[m] | PM[m + step]
        a, b = Y[m].copy(), Y[m + step].copy()
        a[bad] = np.nan
        b[bad] = np.nan
        a[432] = b[432] = np.nan
        y1.append(a)
        y2.append(b)
    return np.array(y1), np.array(y2)


def combine(y1, y2, iters=4, inits=3):
    """Blind search: per carrier complex a(k) maximising 4th-power coherence of z = y1 + s_p a conj(y2)."""
    npair, K = y1.shape
    best = None
    for init in range(inits):
        s = np.ones(npair) if init == 0 else RNG.choice([-1.0, 1.0], npair)
        for _ in range(iters):
            a_best = np.zeros(K, complex)
            C = np.zeros(K)
            for k in range(K):
                v = np.isfinite(y1[:, k])
                if v.sum() < 12:
                    continue
                z = y1[v, k][:, None] + s[v, None] * AGRID[None, :] * np.conj(y2[v, k])[:, None]
                c = np.abs(np.sum(z ** 4, 0)) / np.sum(np.abs(z) ** 4, 0)
                j = int(np.argmax(c))
                a_best[k], C[k] = AGRID[j], c[j]
            M = np.zeros(K, complex)
            for k in range(K):
                v = np.isfinite(y1[:, k])
                if C[k] > 0:
                    z = y1[v, k] + s[v] * a_best[k] * np.conj(y2[v, k])
                    M[k] = np.sum(z ** 4) / np.sum(np.abs(z) ** 4)
            ok = C > 0
            sc = np.zeros((npair, 2))
            for p in range(npair):
                v = ok & np.isfinite(y1[p])
                for j, sg in enumerate((1.0, -1.0)):
                    z = y1[p, v] + sg * a_best[v] * np.conj(y2[p, v])
                    sc[p, j] = np.real(np.sum(z ** 4 / (np.abs(z) ** 4 + 1e-30) * np.conj(M[v] / (np.abs(M[v]) + 1e-30))))
            s = np.where(sc[:, 0] >= sc[:, 1], 1.0, -1.0)
        score = float(np.mean(C[C > 0]))
        if best is None or score > best[0]:
            best = (score, a_best.copy(), s.copy(), C.copy())
    score, a_best, s, C = best
    out = []
    for k in range(K):
        v = np.isfinite(y1[:, k])
        if C[k] <= 0:
            continue
        z = y1[v, k] + s[v] * a_best[k] * np.conj(y2[v, k])
        z = z / np.sqrt(np.mean(np.abs(z) ** 2))
        z = z * np.exp(-0.25j * np.angle(np.sum(z ** 4)))
        out.append(z)
    return float(score), np.concatenate(out)


def variant2(Y, PM, nsym):
    res = {}
    for name, first, step in (("pairs(1,2)(3,4)", 1, 1), ("pairs(2,3)(4,5)", 2, 1), ("control(m,m+3)", 5, 3)):
        y1, y2 = pair_arrays(Y, PM, first + 4 if step == 1 else first, step)
        y1, y2 = y1[:40], y2[:40]
        sc, z = combine(y1, y2)
        st = stats(z)
        st["mean_best_coh"] = sc
        st["npair"] = int(y1.shape[0])
        res[name] = st
    return res


def gauss_and_positive_control():
    """Same pipeline on (a) pure Gaussian and (b) simulated Alamouti 16QAM with random 2-path channels."""
    K, npair = 865, 40
    nm = lambda *s: (RNG.standard_normal(s) + 1j * RNG.standard_normal(s)) / np.sqrt(2)  # noqa: E731
    PM = np.zeros((2 * npair + 8, K), bool)
    out = {}
    Yg = nm(2 * npair + 8, K)
    y1, y2 = pair_arrays(Yg, PM, 1, 1)
    sc, z = combine(y1[:npair], y2[:npair])
    out["gauss_null"] = dict(stats(z), mean_best_coh=sc)
    a = RNG.choice([-3, -1, 1, 3], (2, npair, K)) + 1j * RNG.choice([-3, -1, 1, 3], (2, npair, K))
    s1, s2 = a[0], a[1]
    h1, h2 = nm(K) * 1.0, nm(K) * 0.5
    Y = np.zeros((2 * npair + 8, K), complex)
    sg = RNG.choice([-1.0, 1.0], (npair, 2))
    for p in range(npair):
        r1 = h1 * s1[p] + h2 * s2[p]
        r2 = -h1 * np.conj(s2[p]) + h2 * np.conj(s1[p])
        Y[1 + 2 * p] = sg[p, 0] * (r1 + 0.03 * nm(K))
        Y[2 + 2 * p] = sg[p, 1] * (r2 + 0.03 * nm(K))
    y1, y2 = pair_arrays(Y, PM, 1, 1)
    sc, z = combine(y1[:npair], y2[:npair])
    out["positive_control_alamouti16qam_snr30"] = dict(stats(z), mean_best_coh=sc)
    return out


def ramp_scan(X, exp, m0=5):
    """Residual per-carrier phase ramp of the data vs the pilot channel model (found on M210: constant, 4-fold).

    Adjacent-carrier product z = y(k) conj(y(k-1)); 4th-power mean over a symbol gives the ramp step mod 90 deg and
    its coherence c4. Then removes the ramp (per symbol) and reports k4, m4 (QPSK 1.0) and EVM after a global
    4th-power derotation.
    """
    tau, phi, amp, met = D.track_channel(X, exp)
    Y, PM, SG, PEV, HI = D.equalise(X, exp, tau, phi)
    steps, c4s, out = [], [], []
    for m in range(m0, X.shape[0] - 1):
        y = Y[m].copy()
        y[PM[m]] = np.nan
        y[432] = np.nan
        z = y[1:] * np.conj(y[:-1])
        z = z[np.isfinite(z)]
        z = z / np.abs(z)
        sm = np.mean(z ** 4)
        steps.append(np.angle(sm) / 4)
        c4s.append(abs(sm))
        yy = Y[m] * np.exp(-1j * steps[-1] * (KC))
        yy = yy[~PM[m] & np.isfinite(yy)]
        yy = yy / np.sqrt(np.mean(np.abs(yy) ** 2))
        out.append(yy * np.exp(-0.25j * np.angle(np.mean(yy ** 4))))
    o = np.concatenate(out)
    st = stats(o)
    st["ramp_step_deg_mod90"] = float(np.degrees(np.angle(np.mean(np.exp(4j * np.array(steps)))) / 4))
    st["ramp_step_sym_coherence"] = float(abs(np.mean(np.exp(4j * np.array(steps)))))
    st["c4_adjacent_median"] = float(np.median(c4s))
    return st


def main():
    args = sys.argv[1:]
    if args and args[0] == "--ramp":
        with open(POP / "ramp.jsonl", "w") as f:
            for fn in sorted((POP / "X").glob("*.npz")):
                d = np.load(fn)
                try:
                    r = ramp_scan(d["X"], d["exp"], 5)
                except Exception as e:  # noqa: BLE001
                    r = {"err": str(e)[:60]}
                r["tag"] = fn.stem
                f.write(json.dumps(r, default=float) + "\n")
        return
    if args == ["--control"]:
        r = gauss_and_positive_control()
        (POP / "precoder_controls.json").write_text(json.dumps(r, indent=1))
        print(json.dumps(r, indent=1))
        return
    for tag in args:
        d = np.load(POP / "X" / f"{tag}.npz")
        X, exp, PM = d["X"], d["exp"], d["PM"]
        r1 = variant1(X, exp, PM)
        tau, phi, amp, met = D.track_channel(X, exp)
        Y, PM2, SG, PEV, HI = D.equalise(X, exp, tau, phi)
        r2 = variant2(Y, PM2, X.shape[0])
        out = {"tag": tag, "nsym": int(X.shape[0]), "variant1": r1, "variant2": r2}
        (POP / f"precoder_{tag}.json").write_text(json.dumps(out, indent=1, default=float))
        print(tag, "v1 k4:", {k: round(v["k4"], 3) for k, v in r1.items() if "k4" in v}, flush=True)
        print(tag, "v2:", {k: (round(v["k4"], 3), round(v["m4"], 3), v["evm"]) for k, v in r2.items()}, flush=True)


if __name__ == "__main__":
    main()
