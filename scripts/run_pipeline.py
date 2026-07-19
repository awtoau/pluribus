#!/usr/bin/env python3
"""Run the full pluribus pipeline for one bitstream, or for every
bitstream a board declares.

THIS IS THE canonical pipeline entry point.  One command, bitstream -> report.
(tools/build.py is an older orchestrator kept for its `init`/`annotate` helpers; its
full-pipeline path is superseded by this script.)

Stages — ALL run under python3.15t (free-threaded NoGIL):
    [unpack]  scripts/trellis_unpack.py  BIN -> CONFIG   (native decoder)
    [iomap]   scripts/fpga_iomap.py      CONFIG -> .iomap.tsv
    [load]    load.py                    CONFIG -> DB netlist
    [reach]   reach.py                   all-net BFS (raw-driver NoGIL parallel)
    [reach2]  reach2.py
    [reach3]  reach3.py
    [reach4]  reach4.py
    [report]  report.py                  top-down config summary + detail -> out/<label>-report.txt
    [verilog] verilog.py                 recovered structural Verilog -> out/<label>.v
    [verify]  scripts/check_verilog.py   yosys lint (gate) + regression LEC vs
                                         the prior emission (equiv_induct)

The whole stack runs GIL-free under python3.15t: pytrellis is rebuilt for
free-threading (pybind11 mod_gil_not_used) and sqlalchemy>=2.1.0b3 keeps the
GIL disabled, so a single interpreter serves every stage.

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

Regression gate (#60) — rebuild into a fresh DB and diff vs the working DB
to catch silent data loss from a schema/lifter change:
    PLURIBUS_SQLITE_PATH=tmp/fresh.db python3 scripts/run_pipeline.py \
        --board boards/<name> --all --regression-ref ./pluribus.db

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
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from load import load_board_config  # noqa: E402

# One interpreter for every stage — the whole stack is GIL-free under 3.15t.
PY = os.environ.get("PLURIBUS_PYTHON", "python3.15t")


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


def run_one(label, config, pins, package, raw_bin, skip_load, workers,
            top="top", emit_verilog=True, nets=None, header_note=None,
            verify=True, strict_lec=False, board=None,
            lifter="machxo2", device=None):
    # GOWIN first slice: pad/EFB/EBR recovery and the recovered-Verilog emitter
    # are not modelled yet, so stop after the generic netlist + reachability +
    # report.  chains.py/verilog.py assume the MachXO2 pad/hard-IP layers.
    is_gowin = (lifter == "gowin")
    if is_gowin:
        emit_verilog = False
        verify = False

    if raw_bin and not os.path.exists(config):
        os.makedirs(os.path.dirname(config) or ".", exist_ok=True)
        if is_gowin:
            # GOWIN decode runs under the oss-cad-suite interpreter (apycula),
            # emitting a .gwconfig the free-threaded 3.15t lifter reads back.
            # No iomap stage — gowin pad mapping is deferred.
            gowin_py = os.environ.get(
                "PLURIBUS_GOWIN_PYTHON",
                "/home/dan/opt/oss-cad-suite/py3bin/python3")
            run("unpack", label,
                [gowin_py, "scripts/gowin_unpack.py", raw_bin, config,
                 "--device", device or "GW1N-1"])
        else:
            run("unpack", label,
                [PY, "scripts/trellis_unpack.py", raw_bin, config])
            iomap_env = {"TRELLIS_PACKAGE": package} if package else None
            run("iomap", label,
                [PY, "scripts/fpga_iomap.py", config], extra_env=iomap_env)

    if not skip_load:
        load_cmd = [PY, "load.py", "--label", label,
                    "--config", config, "--pins", pins]
        # Board net annotations (clock names, frequencies, functions,
        # descriptions) — without this the recovered clocks stay as
        # auto-numbered clk_N placeholders instead of their semantic names.
        if nets:
            load_cmd += ["--nets", nets]
        if is_gowin:
            # GW1N designs are small (few LUTs) and pad/EFB/EBR checks don't
            # apply — --fuzz skips the MachXO2-scale count sanity asserts.
            # Forward device+package too: load.py otherwise defaults to the
            # MachXO2 LCMXO2-1200/TQFP100 and rejects the gowin pins metadata.
            load_cmd += ["--lifter", lifter, "--device", device or "GW1N-1",
                         "--fuzz"]
            if package:
                load_cmd += ["--package", package]
        run("load", label, load_cmd)

    # Board annotation layers (#12): SPI register map / cell names / open
    # questions. Optional — runs only for the layers the board actually ships.
    if board and any(os.path.exists(os.path.join(board, f))
                     for f in ("spi_registers.tsv", "cell_names.tsv",
                               "open_questions.tsv")):
        run("annotate", label,
            [PY, "annotate.py", "--bitstream", label, "--board", board])

    reach_cmd = [PY, "reach.py", "--bitstream", label]
    if workers:
        reach_cmd += ["--workers", str(workers)]
    run("reach", label, reach_cmd)

    # Analysis + naming.  reach2/3/4 build reachability and the 9-pass
    # auto-naming; auto_name adds LUT INIT/expression-derived net names on top
    # (additive, not redundant), and patterns fills the structural-pattern
    # table the report consumes.  These were dropped when the pipeline moved
    # off the old tools/build.py orchestrator — without them the recovered
    # names and the report's pattern section are incomplete.  All run before
    # report/deliverables so those carry the full naming.
    # reach2/3/4 build reachability; auto_name/patterns add MachXO2 net-name
    # and structural-pattern layers the report consumes.  For gowin the naming
    # heuristics and the chains report lean on the pad/hard-IP layers that are
    # not modelled yet, so run only the generic reachability passes.
    analysis = (("reach2", "reach3", "reach4") if is_gowin
                else ("reach2", "reach3", "reach4", "auto_name", "patterns"))
    for stage in analysis:
        run(stage, label, [PY, f"{stage}.py", "--bitstream", label])

    # Deliverables (NOT scratch): the report (led by the top-down Device
    # Configuration summary), recovered Verilog, and signal-chain report all go
    # to out/ so they survive a tmp cleanup.
    out_dir = os.path.join(REPO, "out")
    os.makedirs(out_dir, exist_ok=True)
    run("report", label,
        [PY, "report.py", "--bitstream", label,
         "--out", os.path.join(out_dir, f"{label}-report.txt")])
    if not is_gowin:
        run("chains", label,
            [PY, "chains.py", "--bitstream", label,
             "--out", os.path.join(out_dir, f"{label}-chains.txt")])
    if emit_verilog:
        out_v = os.path.join(out_dir, f"{label}.v")
        # Snapshot the prior emission before overwriting, so the verify stage
        # can prove the new netlist is equivalent to it (regression LEC).
        prev_v = os.path.join(REPO, "tmp", f"{label}.v.prev")
        if os.path.exists(out_v):
            shutil.copyfile(out_v, prev_v)
        elif os.path.exists(prev_v):
            os.remove(prev_v)

        vcmd = [PY, "verilog.py", "--bitstream", label,
                "--out", out_v, "--top", top]
        if header_note and os.path.exists(header_note):
            vcmd += ["--header-note", header_note]
        run("verilog", label, vcmd)

        # Verify stage: yosys lint (hard gate) + sequential-equivalence vs the
        # prior emission (regression LEC — report-only unless --strict-lec).
        # The recovered bitstream has no source RTL, so the baseline is the
        # last emission of this same label; a declaration/comment-only emitter
        # change proves equivalent, a real logic change proves diverged.
        if verify and shutil.which("yosys"):
            vcheck = [PY, "scripts/check_verilog.py", out_v, "--top", top]
            if os.path.exists(prev_v):
                vcheck += ["--lec", prev_v]
                if strict_lec:
                    vcheck += ["--strict-lec"]
            run("verify", label, vcheck)
        elif verify:
            print("[verify] SKIPPED — yosys not on PATH", flush=True)

    print(f"pipeline complete for {label} -> out/{label}.v", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", help="board config dir containing board.toml")
    ap.add_argument("--label", help="bitstream label")
    ap.add_argument("--all", action="store_true",
                    help="run every bitstream declared in board.toml")
    ap.add_argument("--bin", help="raw bitstream; unpacked if config is absent")
    ap.add_argument("--config", help="named-cell .config path")
    ap.add_argument("--pins", help="pin annotation TSV")
    ap.add_argument("--nets", help="net annotation TSV (clock names, freqs, "
                    "functions); defaults to the board's nets_tsv")
    ap.add_argument("--package", help="TRELLIS_PACKAGE for the iomap stage")
    ap.add_argument("--skip-load", action="store_true",
                    help="label already loaded; start at reach")
    ap.add_argument("--workers", type=int, help="reach.py worker count")
    ap.add_argument("--top", help="recovered-Verilog top module name "
                    "(default: board [board] top, else 'top')")
    ap.add_argument("--no-verilog", action="store_true",
                    help="skip the recovered-Verilog emission stage")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the yosys verify stage (lint + regression LEC)")
    ap.add_argument("--strict-lec", action="store_true",
                    help="fail the pipeline if the new netlist diverges from the "
                         "prior emission (default: report divergence, non-fatal)")
    ap.add_argument("--regression-ref", metavar="REF_DB",
                    help="after the run, diff the freshly-rebuilt DB "
                         "(PLURIBUS_SQLITE_PATH) against REF_DB per label via "
                         "scripts/rebuild_regression.py; exit non-zero on data loss")
    args = ap.parse_args()

    os.makedirs(os.path.join(REPO, "tmp"), exist_ok=True)

    board = load_board_config(args.board) if args.board else {}
    pins = args.pins or board.get("pins_tsv")
    nets = args.nets or board.get("nets_tsv")
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
        top = args.top or board.get("top") or "top"
        # Optional board-provided Verilog header note (board-specific context).
        header_note = (os.path.join(args.board, "verilog_header.txt")
                       if args.board else None)
        print(f"=== {label} ===", flush=True)
        run_one(label, config, pins, package, raw_bin,
                args.skip_load, args.workers,
                top=top, emit_verilog=not args.no_verilog, nets=nets,
                header_note=header_note,
                verify=not args.no_verify, strict_lec=args.strict_lec,
                board=args.board,
                lifter=board.get("lifter", "machxo2"),
                device=board.get("device"))

    # Regression gate (#60): diff the freshly-rebuilt DB against a reference,
    # per label, to catch silent data loss from a schema/lifter change.  The
    # fresh DB is whatever PLURIBUS_SQLITE_PATH points at for this run.
    if args.regression_ref:
        fresh_db = os.environ.get("PLURIBUS_SQLITE_PATH",
                                  os.path.join(REPO, "pluribus.db"))
        print("=== regression diff (fresh rebuild vs reference) ===", flush=True)
        losses = 0
        for label in labels:
            rc = subprocess.run(
                [PY, os.path.join("scripts", "rebuild_regression.py"),
                 "--fresh", fresh_db, "--ref", args.regression_ref,
                 "--label", label],
                cwd=REPO).returncode
            if rc != 0:
                losses += 1
        if losses:
            sys.exit(f"regression: {losses}/{len(labels)} label(s) lost rows "
                     f"vs {args.regression_ref}")
        print("regression: no data loss vs reference for any label", flush=True)


if __name__ == "__main__":
    main()
