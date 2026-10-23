#!/usr/bin/env python3.15t
"""Cyclone V unpack stage: flash image / .rbf -> `.bt` decompile (the file the cyclonev lifter reads).

Steps (log: tmp/logs/cyclonev_unpack.log):
  - strip leading/trailing 0xFF flash padding -> plain .rbf (skipped if the input has none)
  - --decoder native (default): scripts/cyclonev_decode.py (Bluebird, no mistral-cv)
    --decoder mistral        : mistral-cv decomp <device> <rbf> <bt>
  - --crosscheck: also run mistral-cv and log the line-set diff against the chosen decoder's output
Refuses to overwrite an existing output (same contract as trellis_unpack.py).

  python3.15t scripts/cyclonev_unpack.py IN.bin OUT.bt [--device 5CEBA4U19C8] [--rbf KEEP.rbf]
                                          [--decoder native|mistral] [--crosscheck]
"""
import argparse
import logging
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import toolchain  # noqa: E402
from db import die  # noqa: E402

# mistral-cv decomp of a 2 MB rbf: 2.7 s wall measured 2026-10-24; limit ~5x (cold cache).
# Expiry: subprocess killed, die() names the limit.
DECOMP_LIMIT_S = 15


def strip_ff(raw: bytes) -> bytes:
    a = len(raw) - len(raw.lstrip(b"\xff"))
    b = len(raw.rstrip(b"\xff"))
    return raw[a:b]


def mistral_decomp(device, rbf, bt):
    try:
        r = subprocess.run([toolchain.mistral_cv(), "decomp", device, rbf, bt],
                           capture_output=True, text=True, timeout=DECOMP_LIMIT_S)
    except subprocess.TimeoutExpired:
        die(f"mistral-cv decomp exceeded {DECOMP_LIMIT_S}s")
    if r.returncode != 0:
        die(f"mistral-cv decomp failed rc={r.returncode}: {r.stderr[-300:]}")
    return r.stdout[-1500:] + r.stderr[-1500:]


def native_decomp(device, body, bt):
    import cyclonev_decode as cd
    import cyclonev_native_tables as nt
    try:
        m = cd.decode(body, device)
    except nt.TableError as e:
        die(f"native decoder: {e} (use --decoder mistral)")
    lines = m.bt_lines()
    with open(bt, "w") as f:
        f.write("\n".join(lines) + "\n")
    return f"{len(lines)} lines, {len(m.route_unknown)} unresolved route values"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bin")
    ap.add_argument("bt")
    ap.add_argument("--device", default="5CEBA4U19C8")
    ap.add_argument("--rbf", help="where to keep the stripped .rbf (default: <bt>.rbf)")
    ap.add_argument("--decoder", choices=("native", "mistral"), default="native")
    ap.add_argument("--crosscheck", action="store_true", help="also run mistral-cv; log the line-set diff")
    a = ap.parse_args()

    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_unpack.log"))])
    log = logging.getLogger("cyclonev_unpack")

    if os.path.exists(a.bt):
        die(f"refusing to overwrite {a.bt}")
    rbf = a.rbf or a.bt + ".rbf"
    raw = open(a.bin, "rb").read()
    body = strip_ff(raw)
    log.info("%s: %d bytes -> %d after 0xFF strip; first bytes %s", a.bin, len(raw),
             len(body), body[:8].hex())
    if not body:
        die("empty image after stripping 0xFF")
    os.makedirs(os.path.dirname(os.path.abspath(rbf)), exist_ok=True)
    open(rbf, "wb").write(body)
    os.makedirs(os.path.dirname(os.path.abspath(a.bt)), exist_ok=True)

    if a.decoder == "native":
        log.info("native decode: %s", native_decomp(a.device, body, a.bt))
    else:
        log.info("mistral-cv:\n%s", mistral_decomp(a.device, rbf, a.bt))
    if a.crosscheck:
        import cyclonev_bt_diff as bd
        other = a.bt + ".mistral" if a.decoder == "native" else a.bt + ".native"
        if a.decoder == "native":
            mistral_decomp(a.device, rbf, other)
        else:
            native_decomp(a.device, body, other)
        d = bd.diff(bd.read(a.bt), bd.read(other))
        for k, (oa, ob, na, nb) in d.items():
            log.info("crosscheck [%s] chosen=%d other=%d only_chosen=%d only_other=%d", k, na, nb, len(oa), len(ob))
    log.info("wrote %s (%d bytes)", a.bt, os.path.getsize(a.bt))


if __name__ == "__main__":
    main()
