#!/usr/bin/env python3
"""Run the full pluribus pipeline for one bitstream, or for every
bitstream a board declares.

Stages (see CLAUDE.md):
    [unpack]  scripts/trellis_unpack.py  BIN -> CONFIG        (python3)
    [iomap]   scripts/fpga_iomap.py      CONFIG -> .iomap.tsv (python3)
    [load]    load.py                                          (python3)
    [reach]   reach.py                          (python3.14t — NoGIL)
    [reach2]  reach2.py                                        (python3)
    [reach3]  reach3.py                                        (python3)
    [reach4]  reach4.py                                        (python3)
    [report]  report.py                                        (python3)

Only reach.py needs python3.14t.  Do NOT run load.py under it: sqlalchemy
forces the GIL back on and the later pytrellis import segfaults.

unpack+iomap run only when a raw bitstream is known AND its .config does
not exist yet; both generators refuse to overwrite, so an existing
.config can never be clobbered.  --skip-load starts at reach for a label
already in the DB.

Board-driven (preferred) — paths and device come from board.toml:
    python3 scripts/run_pipeline.py --board boards/<name> --label <LABEL>
    python3 scripts/run_pipeline.py --board boards/<name> --all

Explicit:
    python3 scripts/run_pipeline.py --label <LABEL> \
        --config path/to.bin.config --pins path/to/pins.tsv

Trellis paths come from TRELLIS_BUILD / TRELLIS_DBROOT.  A board may
declare them in its board.toml [trellis] table (they point into the RE
project that owns the board, as pins.tsv already does); an explicit
environment always wins.  This script hardcodes no paths of its own.

--package feeds the iomap stage (defaults to the board's package) — pin
it, because best-fit package detection can drift to a larger package
than the physical part.

Logs: tmp/pipeline_<label>_<stage>.log, one per stage.
"""

import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from load import load_board_config  # noqa: E402


def run(stage, label, cmd, extra_env=None):
    log = os.path.join(REPO, "tmp", f"pipeline_{label}_{stage}.log")
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    print(f"[{stage}] {' '.join(cmd)}  -> {log}", flush=True)
    with open(log, "w") as fh:
        rc = subprocess.run(cmd, cwd=REPO, env=env,
                            stdout=fh, stderr=subprocess.STDOUT).returncode
    if rc != 0:
        print(f"[{stage}] FAILED (exit {rc}) — see {log}", flush=True)
        with open(log) as fh:
            print(fh.read()[-2000:], flush=True)
        sys.exit(rc)
    print(f"[{stage}] ok", flush=True)


def run_one(label, config, pins, package, raw_bin, skip_load, workers):
    if raw_bin and not os.path.exists(config):
        os.makedirs(os.path.dirname(config) or ".", exist_ok=True)
        run("unpack", label,
            ["python3", "scripts/trellis_unpack.py", raw_bin, config])
        iomap_env = {"TRELLIS_PACKAGE": package} if package else None
        run("iomap", label,
            ["python3", "scripts/fpga_iomap.py", config], extra_env=iomap_env)

    if not skip_load:
        run("load", label,
            ["python3", "load.py", "--label", label,
             "--config", config, "--pins", pins])

    reach_cmd = ["python3.14t", "reach.py", "--bitstream", label]
    if workers:
        reach_cmd += ["--workers", str(workers)]
    run("reach", label, reach_cmd)
    for stage in ("reach2", "reach3", "reach4", "report"):
        run(stage, label, ["python3", f"{stage}.py", "--bitstream", label])
    print(f"pipeline complete for {label}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", help="board config dir containing board.toml")
    ap.add_argument("--label", help="bitstream label")
    ap.add_argument("--all", action="store_true",
                    help="run every bitstream declared in board.toml")
    ap.add_argument("--bin", help="raw bitstream; unpacked if config is absent")
    ap.add_argument("--config", help="named-cell .config path")
    ap.add_argument("--pins", help="pin annotation TSV")
    ap.add_argument("--package", help="TRELLIS_PACKAGE for the iomap stage")
    ap.add_argument("--skip-load", action="store_true",
                    help="label already loaded; start at reach")
    ap.add_argument("--workers", type=int, help="reach.py worker count")
    args = ap.parse_args()

    os.makedirs(os.path.join(REPO, "tmp"), exist_ok=True)

    board = load_board_config(args.board) if args.board else {}
    pins = args.pins or board.get("pins_tsv")
    package = args.package or board.get("package")

    # A board may declare where its RE project keeps prjtrellis.  An
    # explicit environment always wins — never override what the caller set.
    for env_key, path in (board.get("trellis") or {}).items():
        os.environ.setdefault(env_key, path)

    if args.all:
        if not board:
            sys.exit("--all requires --board")
        declared = board.get("bitstreams") or {}
        if not declared:
            sys.exit(f"{args.board}/board.toml declares no [bitstreams]")
        labels = [args.label] if args.label else list(declared)
    else:
        if not args.label:
            sys.exit("--label is required (or --all with --board)")
        labels = [args.label]

    for label in labels:
        spec = (board.get("bitstreams") or {}).get(label, {})
        config = args.config or spec.get("config")
        raw_bin = args.bin or spec.get("bin")
        if not config:
            sys.exit(f"no config for {label}: pass --config or declare "
                     f"[bitstreams.{label}] in board.toml")
        if not args.skip_load and not pins:
            sys.exit("load needs --pins (or --board with pins_tsv)")
        print(f"=== {label} ===", flush=True)
        run_one(label, config, pins, package, raw_bin,
                args.skip_load, args.workers)


if __name__ == "__main__":
    main()
