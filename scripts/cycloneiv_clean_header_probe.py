#!/usr/bin/env python3
"""rbf header lane bits that change with quartus_cpf conversion options, same sof (#165, #169).

  python3.15t scripts/cycloneiv_clean_header_probe.py SOF [SOF...]     # log tmp/logs/header_probe.log, work dirs tmp/header_probe/

- Header = 40 bytes after the 0x6a sync; byte j bit k = lane k bit j (cycloneiv_decompress); CRC-16 at bytes 41..42 (j counted from the sync).
- Variants: compression off (corpus default) vs on, and -m configuration modes; prints lane bits that differ, CRC bytes excluded (they follow the content).
"""
import logging
import os
import subprocess
import sys

REPO = os.environ.get("PLURIBUS_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
import toolchain  # noqa: E402

LOG = os.path.join(REPO, "tmp", "logs", "header_probe.log")
WORK = os.path.join(REPO, "tmp", "header_probe")
# quartus_cpf on a 4.7 MB sof: ~2 s measured in the option pair builds (LIMITS in cycloneiv_clean_option_pairs.py = 8 s, 4x)
CPF_LIMIT_S = 8
VARIANTS = {"off": ["-o", "bitstream_compression=off"], "on": ["-o", "bitstream_compression=on"],
            **{f"m_{m}": ["-m", m, "-o", "bitstream_compression=off"] for m in ("PS", "FPP", "ASx1", "ASx4", "PPS", "PPA", "AP")}}


def header_bits(rbf):
    d = open(rbf, "rb").read(200)
    s = d.index(0x6A)
    return s, {(j, k): (d[s + j] >> k) & 1 for j in range(1, 43) for k in range(8)}


def main():
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    log = logging.getLogger("hp")
    log.setLevel(logging.INFO)
    log.addHandler(logging.FileHandler(LOG, "w"))
    log.addHandler(logging.StreamHandler(sys.stdout))
    qb = toolchain.quartus_bin()
    for sof in sys.argv[1:]:
        tag = os.path.basename(os.path.dirname(os.path.abspath(sof)))
        out = {}
        for name, opt in VARIANTS.items():
            rbf = os.path.join(WORK, f"{tag}_{name}.rbf")
            r = subprocess.run([f"{qb}/quartus_cpf", "-c", *opt, sof, rbf], capture_output=True, timeout=CPF_LIMIT_S)
            if r.returncode:
                log.info("%s %s: cpf rc=%d (%s)", tag, name, r.returncode, r.stdout[-120:].decode(errors="replace").strip())
                continue
            out[name] = header_bits(rbf)
        s0, a = out["off"]
        for name, (s1, b) in out.items():
            diff = sorted(k for k in a if a[k] != b[k] and k[0] < 41)
            log.info("%s %s vs off: sync %d/%d, differing header bits: %s", tag, name, s0, s1,
                     [(f"lane{k}", f"bit{j - 1}", f"{a[(j, k)]}->{b[(j, k)]}") for j, k in diff])
    return 0


if __name__ == "__main__":
    sys.exit(main())
