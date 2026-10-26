#!/usr/bin/env python3.15t
"""Simulate a recovered MachXO2 netlist with its hard IP replaced by behavioural models.

Hard IP in the lifted design and what replaces it:
  EFB  -> scripts/efb_open_model.v   (WISHBONE slave + SPI-slave registers; modelled, not recovered)
  PLL  -> scripts/pll_model.v        (dividers decoded from the bitstream, pll_decode.py)
  DCC  -> pass-through in the lift (no model needed); no OSC in this bitstream.
The primary clock inputs of the netlist are driven by the PLL model outputs, using the
board's PLL-output -> HPBX-track table (board.toml [sim.pll_tracks]).

    python3.15t scripts/sim_no_ip.py --board boards/aw2-2d82auto --label V07 \
        --config tmp/v7/FPGA_V07.bin.config [--run-us 60]

Needs PLURIBUS_SQLITE_PATH pointing at the DB holding <label>.
Outputs: tmp/sim/<label>/{rtl.v,tb.v,sim.vvp,sim.out,aw2_tb.vcd,summary[_tieN].json};
log tmp/logs/sim_no_ip.log.

READING A RESULT: register storage and PLL ratios are faithful; EFB register semantics are
modelled (TN1205), not recovered.  Nets with no recovered driver stay X (they are NOT tied
off), so X in the summary is a measure of the unrecovered part of the netlist.
"""
import argparse
import json
import logging
import re
import subprocess
import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
LOG_DIR = REPO / "tmp" / "logs"

_BLACKBOX_RE = re.compile(
    r"\(\*\s*blackbox\s*\*\)\s*\n\s*module\s+EFB\b.*?\n\s*endmodule\s*\n", re.S)
_TEMPLATE_RE = re.compile(r"module efb_spi_slave \(.*?\n\s*endmodule\s*\n", re.S)
_CLK_ALWAYS_RE = re.compile(r"^    always #[\d.]+ (\w+) = ~\1;.*\n", re.M)

# vvp wall-clock backstop: limit = max(VVP_FLOOR_S, VVP_S_PER_US * run_us).
# VVP_S_PER_US is re-measured and logged every run ("vvp finished in X s"); the value here
# is set from the first measured run.  Expiry: killed, logged with limit and elapsed time.
VVP_S_PER_US = 0.05      # measured 0.015 s per simulated us (1.0 s for ~70 us); 3x
VVP_FLOOR_S = 10


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("sim_no_ip")
    if not log.handlers:
        log.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        for h in (logging.StreamHandler(sys.stdout),
                  logging.FileHandler(LOG_DIR / "sim_no_ip.log")):
            h.setFormatter(fmt)
            log.addHandler(h)
    return log


def track_rates(board_dir):
    """{hpbx track: MHz} from the board's nets.tsv (modal rate per track)."""
    d = {}
    for ln in (Path(board_dir) / "nets.tsv").read_text().splitlines():
        if ln.startswith("#") or not ln.strip():
            continue
        p = ln.split("\t")
        if len(p) > 5 and p[4] and p[5]:
            d.setdefault(p[5], Counter())[float(p[4])] += 1
    return {t: c.most_common(1)[0][0] for t, c in d.items()}


def primary_clocks(label):
    """{hpbx track: tb clock port} for the unified primary clocks of `label`."""
    import clocks
    import db
    from sqlalchemy import text
    with db.engine().connect() as c:
        bs = c.execute(text("select id from bitstreams where label=:l"), {"l": label}).scalar()
        cds = c.execute(text("select clk_net, ff_count, hpbx_track from clock_domain_summary "
                             "where bitstream=:b"), {"b": bs}).fetchall()
        names = c.execute(text("select net, name, confidence from net_names where bitstream=:b"),
                          {"b": bs}).fetchall()
    unify = clocks.unify_clock_spines([tuple(r) for r in cds], [(n, nm) for n, nm, _c in names])
    nm = {n: (name, conf) for n, name, conf in names}
    out = {}
    for clk_net, _ff, track in cds:
        if track and clk_net not in unify:           # canonical member of its track
            name, conf = nm.get(clk_net, (clk_net, ""))
            out[track] = name if conf == "confirmed" else f"spec_{name}"
    return out


def plan_clocks(board_cfg, board_dir, config_text, label, log):
    import pll_decode
    pll = pll_decode.parse_pll(config_text)
    if pll is None:
        log.warning("no PLL tile in config: clocks keep the generated testbench rates")
        return None
    rates = track_rates(board_dir)
    fin = pll_decode.solve_fin(pll, set(rates.values()))
    if fin is None:
        sys.exit("PLL config does not give a unique input frequency matching the board "
                 f"track rates {rates}; refusing to guess")
    freqs = pll_decode.output_freqs(pll, fin)
    tracks = board_cfg.get("sim", {}).get("pll_tracks", {})
    prim = primary_clocks(label)
    drive = {}                                   # tb clock port -> PLL output
    for out, track in tracks.items():
        if track not in prim:
            continue
        if abs(freqs[out] - rates[track]) > 1e-6:
            sys.exit(f"{out} decodes to {freqs[out]} MHz but track {track} is annotated "
                     f"{rates[track]} MHz")
        drive[prim[track]] = out
    log.info("PLL tile %s: I=%d FB=%d OP/OS/OS2/OS3 div = %s -> Fin %.3f MHz, outputs %s",
             pll["tile"], pll["i_div"], pll["fb_div"], list(pll["out_div"].values()), fin, freqs)
    log.info("clock port <- PLL output: %s", drive)
    return {"pll": pll, "fin": fin, "freqs": freqs, "drive": drive}


def spi_script(board_dir):
    """(label, bytes) SPI frames from spi_registers.tsv: board writes, then readbacks."""
    import efb_boot_gen as g
    rows = g.read_map(Path(board_dir) / "spi_registers.tsv")
    frames = []
    cmd = {"WRITE": 0xA8, "CTRL": 0xC8}
    for bank, addr, name, _d in rows:
        if bank in cmd and name in g.DEFAULTS:
            frames.append((f"{bank} {name}", [cmd[bank], addr, g.DEFAULTS[name]]))
    for bank, addr, name, _d in rows:
        if bank == "READ" and name in ("STATUS", "IDENT"):
            n = 8 if name == "IDENT" else 1
            frames.append((f"READ {name}", [0xA0, addr, 0xA0] + [0xFF] * n))
    return frames


def build_tb(tb, plan, frames, run_ns, ff_names, sck_half_ns, tie=None, undriven=()):
    tb, n = re.subn(r"reg FPGA_nCS = 1'b0;", "reg FPGA_nCS = 1'b1;", tb)
    if n != 1:
        sys.exit("testbench has no 'reg FPGA_nCS' line to idle")
    if plan:
        found = set(_CLK_ALWAYS_RE.findall(tb))
        missing = set(plan["drive"]) - found
        if missing:
            sys.exit(f"testbench has no free-running driver for {sorted(missing)}")
        tb = _CLK_ALWAYS_RE.sub(lambda m: "" if m.group(1) in plan["drive"] else m.group(0), tb)
        p = plan["pll"]
        pll_block = (
            "    // PLL model: outputs decoded from the bitstream (pll_decode.py).\n"
            "    reg pll_ref = 1'b0;\n"
            f"    always #{500.0 / plan['fin']:.4f} pll_ref = ~pll_ref;  // {plan['fin']:g} MHz\n"
            "    wire pll_op, pll_os, pll_os2, pll_os3, pll_lock;\n"
            f"    pll_model #({p['i_div']}, {p['fb_div']}, {p['out_div']['CLKOP']}, "
            f"{p['out_div']['CLKOS']}, {p['out_div']['CLKOS2']}, {p['out_div']['CLKOS3']}) "
            "u_pll (.CLKI(pll_ref), .CLKOP(pll_op), .CLKOS(pll_os), .CLKOS2(pll_os2), "
            ".CLKOS3(pll_os3), .LOCK(pll_lock));\n"
            + "".join(f"    always @* {port} = pll_{out.replace('CLK', '').lower()};\n"
                      for port, out in plan["drive"].items()) + "\n")
        if "    // ADC data:" not in tb:
            sys.exit("testbench has no '// ADC data:' anchor")
        tb = tb.replace("    // ADC data:", pll_block + "    // ADC data:", 1)
    helpers = f"""
    // --- SPI master (MCU side): mode 0, MSB first, {sck_half_ns} ns SCK half period ---
    reg [7:0] spi_rx;
    task spi_begin; begin FPGA_nCS = 1'b0; dut.efb_inst.spi_cs(1'b0); end endtask
    task spi_byte(input [7:0] b); begin dut.efb_inst.spi_xfer(b, spi_rx, {sck_half_ns}); end endtask
    task spi_end; begin dut.efb_inst.spi_cs(1'b1); FPGA_nCS = 1'b1; #200; end endtask
"""
    stim = []
    if tie is not None:
        stim.append(f"        // --- WHAT-IF: undriven wires tied to {tie} (NOT recovered behaviour) ---")
        stim += [f"        force dut.{w} = 1'b{tie};" for w in undriven]
    stim += ["        // --- stimulus (scripts/sim_no_ip.py) ---",
             "        #5000;   // fabric settle, 5 us"]
    for label, byts in frames:
        stim.append("        spi_begin; " + " ".join(f"spi_byte(8'h{b:02x});" for b in byts)
                    + f" spi_end;   // {label}")
    stim.append(f"        #{run_ns};   // run-out")
    census = ["        // --- end-of-run FF census ---"]
    for nme in ff_names:
        census.append(f'        $display("FF %b {nme}", dut.{nme});')
    census.append('        $display("EFB wb_reads=%0d wb_writes=%0d spi_bytes=%0d", '
                  'dut.efb_inst.wb_reads, dut.efb_inst.wb_writes, dut.efb_inst.spi_bytes);')
    tail = "\n".join(stim + census)
    tb, n = re.subn(r"\n        #\d+ \$finish;[^\n]*\n", "\n" + tail + "\n        $finish;\n", tb)
    if n != 1:
        sys.exit("testbench has no '#N $finish' line")
    return tb[:tb.rfind("endmodule")] + helpers + "endmodule\n"


def undriven_wires(rtl_path, top):
    """Wires yosys `check` reports as used-but-undriven (the unrecovered part of the netlist)."""
    import heavy_guard
    r = heavy_guard.guarded(["yosys", "-p", f"read_verilog -sv {rtl_path}; hierarchy -check -top "
                             f"{top}; proc; check"], "yosys check")  # #122
    return sorted(set(re.findall(r"Wire \S*?\.\\?(\S+) is used but has no driver",
                                 r.stdout + r.stderr)))


def run_vvp(vvp, cwd, run_us, log):
    limit = max(VVP_FLOOR_S, VVP_S_PER_US * run_us)
    t0 = time.monotonic()
    import heavy_guard
    r = heavy_guard.guarded(["vvp", str(vvp), "+efb_trace"], "vvp", log, overall_s=limit, cwd=str(cwd))  # #122
    if r.timed_out:
        log.error("vvp exceeded %.0f s (limit = max(%d, %.1f s/us x %g us)) -- killed",
                  limit, VVP_FLOOR_S, VVP_S_PER_US, run_us)
        return None
    log.info("vvp finished in %.1f s (limit %.0f s)", time.monotonic() - t0, limit)
    return r.stdout + r.stderr


def vcd_activity(vcd, names):
    """({name: values seen}, {name: last value}) for the 1-bit dut-level regs in `names`."""
    ids, seen, last, scope = {}, {}, {}, []
    want = set(names)
    with open(vcd) as fh:
        for ln in fh:
            if ln.startswith("$scope"):
                scope.append(ln.split()[2])
            elif ln.startswith("$upscope"):
                scope.pop()
            elif ln.startswith("$var") and scope[-2:] == ["aw2_tb", "dut"]:
                p = ln.split()
                if p[4] in want and p[2] == "1":
                    ids.setdefault(p[3], []).append(p[4])
            elif ln.startswith("$enddefinitions"):
                break
        for ln in fh:
            ln = ln.strip()
            if ln and ln[0] in "01xXzZ" and len(ln) > 1:
                v, i = ln[0].lower(), ln[1:]
                for n in ids.get(i, ()):
                    seen.setdefault(n, set()).add(v)
                    last[n] = v
    return seen, last


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", required=True)
    ap.add_argument("--label", default="V07")
    ap.add_argument("--config", required=True, help="native-decoded .config of the label")
    ap.add_argument("--run-us", type=float, default=60.0, help="run-out after the SPI script")
    ap.add_argument("--tie-undriven", type=int, choices=(0, 1), default=None,
                    help="WHAT-IF experiment: force every undriven wire to this constant")
    ap.add_argument("--sck-half-ns", type=int, default=55,
                    help="SPI SCK half period: STM32 SPI1 72 MHz / 8 = 9 MHz")
    args = ap.parse_args()
    log = setup_logging()
    work = REPO / "tmp" / "sim" / args.label
    work.mkdir(parents=True, exist_ok=True)
    board_dir = Path(args.board)
    board_cfg = tomllib.loads((board_dir / "board.toml").read_text())

    tb_gen = work / "tb_gen.v"
    r = subprocess.run(["python3.15t", "verilog.py", "--bitstream", args.label, "--out",
                        str(work / "rtl_gen.v"), "--top", board_cfg["board"]["top"],
                        "--header-note", str(board_dir / "verilog_header.txt"),
                        "--tb-out", str(tb_gen)], cwd=str(REPO), capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"verilog.py failed:\n{r.stderr[-2000:]}")
    rtl = (work / "rtl_gen.v").read_text()
    rtl, n = _BLACKBOX_RE.subn("// EFB blackbox stub removed: scripts/efb_open_model.v\n", rtl)
    if n != 1:
        log.warning("expected 1 EFB blackbox stub, removed %d", n)
    rtl = _TEMPLATE_RE.sub("", rtl)
    (work / "rtl.v").write_text(rtl)

    plan = plan_clocks(board_cfg, board_dir, Path(args.config).read_text(), args.label, log)
    frames = spi_script(board_dir)
    ff_names = re.findall(r"^    reg (\w+) = 1'b[01];\s*//.*clk=", rtl, re.M)
    log.info("%d FFs, %d SPI frames", len(ff_names), len(frames))
    undriven = undriven_wires(work / "rtl_gen.v", board_cfg["board"]["top"])
    log.info("%d undriven wires (yosys check)", len(undriven))
    tb = build_tb(tb_gen.read_text(), plan, frames, int(args.run_us * 1000), ff_names,
                  args.sck_half_ns, args.tie_undriven,
                  [w for w in undriven if re.fullmatch(r"\w+", w)])
    (work / "tb.v").write_text(tb)

    vvp = work / "sim.vvp"
    cmd = ["iverilog", "-g2012", "-o", str(vvp), "-s", "aw2_tb", str(work / "rtl.v"),
           str(REPO / "scripts/efb_open_model.v"), str(REPO / "scripts/pll_model.v"),
           str(work / "tb.v")]
    import heavy_guard
    r = heavy_guard.guarded(cmd, "iverilog", log)  # #122
    if r.returncode != 0:
        log.error("COMPILE FAILED\n%s", (r.stderr or r.stdout)[-3000:])
        return 1
    total_us = 5 + 2 * 8 * args.sck_half_ns * sum(len(b) for _l, b in frames) / 1000 + args.run_us
    out = run_vvp(vvp, work, total_us, log)
    if out is None:
        return 1
    (work / "sim.out").write_text(out)

    ff_val = {m.group(2): m.group(1) for m in re.finditer(r"^FF (\S+) (\S+)$", out, re.M)}
    vcd = work / "aw2_tb.vcd"
    seen, _last = vcd_activity(vcd, ff_names) if vcd.exists() else ({}, {})
    wb = re.search(r"EFB wb_reads=(\d+) wb_writes=(\d+) spi_bytes=(\d+)", out)
    summary = {
        "label": args.label, "run_us": args.run_us,
        "ffs": len(ff_names), "undriven_wires": len(undriven),
        "tie_undriven": args.tie_undriven,
        "ffs_x_at_end": sum(1 for v in ff_val.values() if "x" in v or "z" in v),
        "ffs_toggled_0_and_1": sum(1 for s in seen.values() if {"0", "1"} <= s),
        "wb_reads": int(wb.group(1)) if wb else None,
        "wb_writes": int(wb.group(2)) if wb else None,
        "spi_bytes": int(wb.group(3)) if wb else None,
        "pll": {"fin_mhz": plan["fin"], "outputs_mhz": plan["freqs"],
                "drive": plan["drive"]} if plan else None,
    }
    (work / (f"summary_tie{args.tie_undriven}.json" if args.tie_undriven is not None else "summary.json")).write_text(json.dumps(summary, indent=1, sort_keys=True))
    for k, v in summary.items():
        log.info("%-22s %s", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
