#!/usr/bin/env python3
"""Run the full pluribus pipeline for one bitstream label.

Stages (see CLAUDE.md):
    [unpack]  scripts/trellis_unpack.py  BIN -> CONFIG      (python3)
    [iomap]   scripts/fpga_iomap.py      CONFIG -> .iomap.tsv (python3)
    [load]    load.py                                        (python3)
    [reach]   reach.py                                       (python3.14t)
    [reach2]  reach2.py                                      (python3)
    [reach3]  reach3.py                                      (python3)
    [reach4]  reach4.py                                      (python3)
    [report]  report.py                                      (python3)

unpack/iomap run only when --bin is given (fresh bitstream with no
.config yet); both refuse to overwrite existing outputs.  --skip-load
starts at reach for a label already loaded.

Every stage logs to tmp/pipeline_<label>_<stage>.log and the driver
stops on the first nonzero exit.

Example (new bitstream):
    python3 scripts/run_pipeline.py --label V02 \
        --bin "/path/to/DS1302_impl1(8)_V02.bin" \
        --config tmp/v2/DS1302_V02.bin.config \
        --pins /mnt/2tb/git/awto-2000/fpga/aw2/aw2-pins.tsv

Example (already loaded, reach onward):
    python3 scripts/run_pipeline.py --label V02 --skip-load
"""

import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TRELLIS_ENV = {
    "TRELLIS_BUILD":
        "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/libtrellis/build",
    "TRELLIS_DBROOT":
        "/mnt/2tb/git/awto-2000/debris/tmp/prjtrellis/database",
}


def run(stage, label, cmd, extra_env=None):
    log = os.path.join(REPO, "tmp", f"pipeline_{label}_{stage}.log")
    env = dict(os.environ)
    for k, v in TRELLIS_ENV.items():
        env.setdefault(k, v)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--bin", help="raw bitstream; triggers unpack+iomap")
    ap.add_argument("--config", help=".config path (required with --bin or for load)")
    ap.add_argument("--pins", help="pin annotation TSV (required for load)")
    ap.add_argument("--package", default="TQFP100",
                    help="TRELLIS_PACKAGE for iomap (default TQFP100)")
    ap.add_argument("--skip-load", action="store_true",
                    help="label already loaded; start at reach")
    ap.add_argument("--workers", default=None, help="reach.py workers")
    args = ap.parse_args()

    os.makedirs(os.path.join(REPO, "tmp"), exist_ok=True)

    if args.bin:
        if not args.config:
            sys.exit("--bin requires --config (output path for the unpack)")
        run("unpack", args.label,
            ["python3", "scripts/trellis_unpack.py", args.bin, args.config])
        run("iomap", args.label,
            ["python3", "scripts/fpga_iomap.py", args.config],
            extra_env={"TRELLIS_PACKAGE": args.package})

    if not args.skip_load:
        if not (args.config and args.pins):
            sys.exit("load needs --config and --pins (or use --skip-load)")
        run("load", args.label,
            ["python3", "load.py", "--label", args.label,
             "--config", args.config, "--pins", args.pins])

    reach_cmd = ["python3.14t", "reach.py", "--bitstream", args.label]
    if args.workers:
        reach_cmd += ["--workers", args.workers]
    run("reach", args.label, reach_cmd)
    run("reach2", args.label, ["python3", "reach2.py", "--bitstream", args.label])
    run("reach3", args.label, ["python3", "reach3.py", "--bitstream", args.label])
    run("reach4", args.label, ["python3", "reach4.py", "--bitstream", args.label])
    run("report", args.label, ["python3", "report.py", "--bitstream", args.label])
    print(f"pipeline complete for {args.label}", flush=True)


if __name__ == "__main__":
    main()
