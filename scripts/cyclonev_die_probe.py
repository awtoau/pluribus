#!/usr/bin/env python3
"""Compile a trivial Verilog design for each Cyclone V die family in Quartus,
to get real ground-truth .rbf sizes per die (both compressed and uncompressed).
Used to narrow an unknown Cyclone-V bitstream's die family by size, when the
bitstream itself carries no IDCODE (Mistral's IDCODE field is a default-value
slot, not extracted from the bitstream; Quartus's get_part_info Tcl API has no
IDCODE getter either).

A near-empty design's .rbf size is dominated by the device's own raw config-RAM
size, so uncompressed rbf_size works as a size proxy across die families
without needing a real design or IDCODE lookup. Cross-checked against the
Cyclone V datasheet's (683801) published uncompressed .rbf size table — matches
byte-for-byte. Only resolves to die-size-class granularity though: several
part numbers share one die's fabric size (the same limit Mistral's 7-die set
already has).

leading_ff_len is recorded but is NOT a die signature: it is a quartus_cpf
generation-option artifact (default options give the same value for every die).
Treat it as a raw observation per rbf_mode.

Usage:
    python3 scripts/cyclonev_die_probe.py --target-rbf /path/to/unknown.depack.bin
"""
import argparse
import datetime
import hashlib
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import db
import schema
import toolchain
from sqlalchemy import select, insert

# Resolved via the shared toolchain module (#90-style convention: env var,
# then conventional install globs, newest version wins) rather than a
# hardcoded path -- see scripts/toolchain.py:quartus_bin() and
# docs/cyclonev-verification.md for re-running against a different install.
QUARTUS_BIN = Path(toolchain.quartus_bin())


def _detect_toolchain_version(quartus_bin, logger=None):
    """Real version string ('25.1std.0.1129') read from quartus_map --version,
    not guessed from the install directory name -- so a re-run against a
    different/upgraded Quartus install always records what actually ran."""
    try:
        # Waits for: quartus_map --version to print and exit (a version
        # banner, not a compile). Observed: <1s. Timeout: 30s, a stall
        # bound for a hung/misinstalled binary, not a measured multiple --
        # on expiry falls through to the dir-name fallback below, logged.
        out = subprocess.run([str(quartus_bin / "quartus_map"), "--version"],
                              capture_output=True, text=True, timeout=30).stdout
        m = re.search(r"Version\s+(\S+)\s+Build\s+(\S+)", out)
        if m:
            return f"quartus-{m.group(1)}.{m.group(2)}"
    except Exception as exc:
        if logger:
            logger.warning("could not detect quartus version: %s", exc)
    return f"quartus-{quartus_bin.parent.parent.name}"  # fallback: dir name


TOOLCHAIN = _detect_toolchain_version(QUARTUS_BIN)

# One representative part per die family (same 7 Mistral ships data for, plus
# any others worth adding later — Quartus itself supports ~432 Cyclone V parts).
DIES = {
    "e50f": "5CEBA4U19C8",
    "gt75f": "5CEBA5U19C8",
    "gt150f": "5CEBA7U19C8",
    "gt300f": "5CEBA9U19C8",
    "gx25f": "5CGXFC3B6U19C7",
    "sx50f": "5CSEBA4U19C8",
    "sx120f": "5CSEBA6U19C7",
}

PROBE_VERILOG = """module probe(input clk, input rst, output reg q);
  always @(posedge clk or posedge rst)
    if (rst) q <= 1'b0;
    else q <= ~q;
endmodule
"""


def setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("cyclonev_die_probe")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh = logging.FileHandler(log_path)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def run(cmd, cwd, logger, timeout=180):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        logger.error(f"FAILED: {' '.join(cmd)}\n{result.stdout[-2000:]}\n{result.stderr[-1000:]}")
        return False
    return True


def header_signature(data: bytes, header_len=2048):
    import collections, math
    i = 0
    while i < len(data) and data[i] == 0xFF:
        i += 1
    chunk = data[i:i + header_len]
    if not chunk:
        return {"leading_ff": i, "header_entropy": None, "first_byte": None}
    c = collections.Counter(chunk)
    n = len(chunk)
    entropy = -sum((v / n) * math.log2(v / n) for v in c.values())
    return {"leading_ff": i, "header_entropy": round(entropy, 4),
            "first_byte": hex(data[i]) if i < len(data) else None}


def compile_die(die_name, part, work_dir: Path, logger):
    d = work_dir / die_name
    d.mkdir(parents=True, exist_ok=True)
    (d / "probe.v").write_text(PROBE_VERILOG)
    (d / "probe.qsf").write_text(
        f'set_global_assignment -name FAMILY "Cyclone V"\n'
        f'set_global_assignment -name DEVICE {part}\n'
        f'set_global_assignment -name TOP_LEVEL_ENTITY probe\n'
        f'set_global_assignment -name VERILOG_FILE probe.v\n'
    )
    logger.info(f"{die_name} ({part}): synthesizing")
    if not run([str(QUARTUS_BIN / "quartus_map"), "probe",
                f"--family=Cyclone V", f"--part={part}"], d, logger):
        return None
    logger.info(f"{die_name}: fitting")
    if not run([str(QUARTUS_BIN / "quartus_fit"), "probe"], d, logger):
        return None
    logger.info(f"{die_name}: assembling")
    if not run([str(QUARTUS_BIN / "quartus_asm"), "probe"], d, logger):
        return None
    sof = d / "probe.sof"
    sigs = []
    for mode, cpf_args in [("uncompressed", []), ("compressed", ["-o", "bitstream_compression=on"])]:
        rbf = d / f"probe_{mode}.rbf"
        logger.info(f"{die_name}: converting to {mode} rbf")
        if not run([str(QUARTUS_BIN / "quartus_cpf"), "-c", *cpf_args, str(sof), str(rbf)], d, logger):
            continue
        data = rbf.read_bytes()
        sig = header_signature(data)
        sig.update({"die": die_name, "part": part, "rbf_mode": mode, "rbf_size": len(data)})
        logger.info(f"{die_name} [{mode}]: rbf_size={len(data)} leading_ff={sig['leading_ff']} "
                    f"header_entropy={sig['header_entropy']} first_byte={sig['first_byte']}")
        sigs.append(sig)
    return sigs


def store_fingerprints(results, logger):
    """Upsert into device_fingerprints (SQLite: delete-then-insert per key)."""
    schema.init()
    eng = db.engine()
    probe_hash = hashlib.sha256(PROBE_VERILOG.encode()).hexdigest()[:16]
    now = datetime.datetime.now(datetime.timezone.utc)
    with eng.begin() as conn:
        for r in results:
            conn.execute(
                schema.device_fingerprints.delete().where(
                    (schema.device_fingerprints.c.vendor == "altera") &
                    (schema.device_fingerprints.c.part == r["part"]) &
                    (schema.device_fingerprints.c.toolchain == TOOLCHAIN) &
                    (schema.device_fingerprints.c.probe_design == probe_hash) &
                    (schema.device_fingerprints.c.rbf_mode == r["rbf_mode"])
                )
            )
            conn.execute(insert(schema.device_fingerprints).values(
                vendor="altera", family="Cyclone V", die=r["die"], part=r["part"],
                toolchain=TOOLCHAIN, probe_design=probe_hash, rbf_mode=r["rbf_mode"],
                rbf_size=r["rbf_size"], leading_ff_len=r["leading_ff"],
                header_entropy=r["header_entropy"], first_payload_byte=r["first_byte"],
                generated_at=now,
            ))
    logger.info(f"Stored {len(results)} fingerprints in device_fingerprints "
                f"(vendor=altera, toolchain={TOOLCHAIN}, probe_design={probe_hash})")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target-rbf", type=Path, default=None,
                     help="depacked unknown bitstream to compare against (optional; size comparison only)")
    ap.add_argument("--work-dir", type=Path,
                     default=Path("/mnt/2tb/git/pluribus/tmp/cyclonev_die_probe"))
    args = ap.parse_args()

    log_path = Path("/mnt/2tb/git/pluribus/tmp/logs/cyclonev_die_probe.log")
    logger = setup_logging(log_path)

    results = []
    for die_name, part in DIES.items():
        sigs = compile_die(die_name, part, args.work_dir, logger)
        results.extend(sigs)

    out_path = args.work_dir / "results.json"
    out_path.write_text(json.dumps(results, indent=2))
    logger.info(f"Done. {len(results)} fingerprints "
                f"({len(results) // 2 if results else 0}/{len(DIES)} dies x 2 modes). Results: {out_path}")

    if results:
        store_fingerprints(results, logger)

    for mode in ("uncompressed", "compressed"):
        print(f"\n=== Die rbf_size, {mode} ===")
        for r in sorted((r for r in results if r["rbf_mode"] == mode), key=lambda r: r["rbf_size"]):
            print(f"{r['die']:8s} {r['part']:16s} rbf_size={r['rbf_size']:>10}")

    if args.target_rbf:
        # target_rbf may be a depacked payload (leading/trailing-0xFF stripped), so
        # compare size only against the compressed-mode results. Size alone narrows
        # to a die-size class; it does not pick a single die.
        target = args.target_rbf.read_bytes()
        tsize = len(target)
        print(f"\n=== Target: {args.target_rbf.name} (size={tsize}) ===")
        print("Nearest by compressed rbf_size (informational only -- compressed size")
        print("depends on the real design's content, this is NOT a reliable die match):")
        for r in sorted((r for r in results if r["rbf_mode"] == "compressed"),
                         key=lambda r: abs(r["rbf_size"] - tsize)):
            print(f"  {r['die']:8s} rbf_size={r['rbf_size']:>10} (target={tsize}, "
                  f"diff={abs(r['rbf_size'] - tsize):>10})")


if __name__ == "__main__":
    main()
