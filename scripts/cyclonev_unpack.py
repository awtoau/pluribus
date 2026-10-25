#!/usr/bin/env python3.15t
"""Cyclone V unpack stage: flash image / .rbf -> Mistral `.bt` decompile.

Steps (log: tmp/logs/cyclonev_unpack.log):
  - locate the `jjjj` sync (bit-shifted `a6a6a6a6` form realigned); keep the 0x80-byte 0xFF
    preamble + sync (Mistral reads the option RAM at absolute 0x84), drop only padding before it
  - validate via cyclonev_decompress: sync, option-RAM CRC16, PRAM/CRAM frame CRC16s, postamble;
    die() naming the failing check (no garbage to the lifter).  Compressed input is expanded.
  - --decoder native (default): scripts/cyclonev_decode.py; --decoder mistral: mistral-cv decomp <device> <rbf> <bt>
    (the `.bt` is what the cyclonev lifter reads); --crosscheck runs the other one and logs the diff
Refuses to overwrite an existing output (same contract as trellis_unpack.py).
Decision: #114.

  python3.15t scripts/cyclonev_unpack.py IN.bin OUT.bt [--device 5CEBA4U19C8] [--rbf KEEP.rbf]
"""
import argparse
import logging
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cyclonev_decompress as cd  # noqa: E402
import toolchain  # noqa: E402
from db import die  # noqa: E402

# mistral-cv decomp of a 2 MB rbf: 2.7 s wall measured 2026-10-24; limit ~5x (cold cache).
# Expiry: subprocess killed, die() names the limit.
DECOMP_LIMIT_S = 15


PREAMBLE = 0x80  # 0xFF bytes before the sync in every quartus_cpf .rbf (sync at 0x80, option RAM 0x84)


def normalise(raw: bytes) -> bytes:
    """Validated, uncompressed .rbf starting at the preamble.  die() on any failed check."""
    try:
        n, sh = cd.find_sync(raw)
        if sh:
            raw = cd.realign(raw, sh)
        if n < PREAMBLE:
            die(f"preamble too short: sync at byte {n}, need {PREAMBLE:#x} 0xFF bytes before it "
                "(stripped leading 0xFF? Mistral would misread the option RAM, #114)")
        return cd.decompress(raw[n - PREAMBLE:])
    except cd.FormatError as e:
        die(f"not a valid Cyclone V .rbf: {e}")


def bypass_body(raw: bytes) -> bytes:
    """Realigned stream from the preamble on, no validation (--allow-invalid)."""
    n, sh = cd.find_sync(raw)
    if sh:
        raw = cd.realign(raw, sh)
    return raw[n - PREAMBLE:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bin")
    ap.add_argument("bt")
    ap.add_argument("--device", default="5CEBA4U19C8")
    ap.add_argument("--rbf", help="where to keep the stripped .rbf (default: <bt>.rbf)")
    ap.add_argument("--decoder", choices=("native", "mistral"), default="native",
                    help="native: scripts/cyclonev_decode.py (docs/cyclonev-native-decoder.md); mistral: mistral-cv")
    ap.add_argument("--allow-invalid", action="store_true",
                    help="DIAGNOSTIC ONLY: decode even if sync/CRC/frame checks fail (e.g. opaque CRAM); "
                         "statistics only, the result is not a netlist of a real design")
    ap.add_argument("--crosscheck", action="store_true", help="also run the other decoder; log the .bt line-set diff")
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
    if a.allow_invalid:
        log.warning("!!! --allow-invalid: container/CRC validation BYPASSED; output is NOT trustworthy logic !!!")
        try:
            body = normalise(raw)
        except SystemExit:
            body = bypass_body(raw)
            log.warning("!!! validation FAILED for %s; using realigned unvalidated stream (%d bytes) !!!", a.bin, len(body))
    else:
        body = normalise(raw)
    log.info("%s: %d bytes -> %d validated (preamble kept); first bytes %s", a.bin, len(raw),
             len(body), body[:4].hex())
    os.makedirs(os.path.dirname(os.path.abspath(rbf)), exist_ok=True)
    open(rbf, "wb").write(body)
    os.makedirs(os.path.dirname(os.path.abspath(a.bt)), exist_ok=True)
    def run_mistral(out):
        try:
            r = subprocess.run([toolchain.mistral_cv(), "decomp", a.device, rbf, out],
                               capture_output=True, text=True, timeout=DECOMP_LIMIT_S)
        except subprocess.TimeoutExpired:
            die(f"mistral-cv decomp exceeded {DECOMP_LIMIT_S}s")
        log.info("mistral-cv rc=%d\n%s%s", r.returncode, r.stdout[-1500:], r.stderr[-1500:])
        if r.returncode != 0:
            die(f"mistral-cv decomp failed rc={r.returncode}")

    def run_native(out):
        import cyclonev_decode as nd
        import cyclonev_native_tables as nt
        try:
            m = nd.decode(body, a.device, strict=not a.allow_invalid)
        except (nt.TableError, nd.ContainerError) as e:
            die(f"native decoder: {e} (use --decoder mistral)")
        lines = m.bt_lines()
        open(out, "w").write("\n".join(lines) + "\n")
        log.info("native decode: %d lines, %d unresolved route values", len(lines), len(m.route_unknown))

    (run_native if a.decoder == "native" else run_mistral)(a.bt)
    if a.crosscheck:
        import cyclonev_bt_diff as bd
        other = a.bt + (".mistral" if a.decoder == "native" else ".native")
        (run_mistral if a.decoder == "native" else run_native)(other)
        for k, (oa, ob, na, nb) in bd.diff(bd.read(a.bt), bd.read(other)).items():
            log.info("crosscheck [%s] chosen=%d other=%d only_chosen=%d only_other=%d", k, na, nb, len(oa), len(ob))
    log.info("wrote %s (%d bytes)", a.bt, os.path.getsize(a.bt))


if __name__ == "__main__":
    main()
