#!/usr/bin/env python3.15t
"""#188: build the 3 vetted real-design corpus candidates (sources/real-designs/, see its README for
provenance/license) for EP4CGX150DF31C7 with the CURRENT Quartus install, lift each, and run the
existing harness-stripped template library (reference/template_library.json, 90 templates) against
each design's clocked-FF cones -- same matcher already run once against the real DJI m2001 image
(2,963/35,873 = 8.3% matched).  This answers two things the DJI-only run could not: (a) sanity-checks
the matcher against designs whose structure is actually known (so a hit can be verified real, not
coincidental), and (b) whether the CURRENT compiler's LUT/carry-chain shapes are covered by a library
also built by the current compiler -- not yet a cross-TOOLCHAIN-VERSION test (both sides use the same
Quartus install), but a cross-DESIGN-TYPE one: SHA-1 round feedback vs. a CPU ALU/shifter/regfile vs.
a stream-handshake pipeline, three structurally distinct shapes.

Built SEQUENTIALLY, not with --jobs N: only 3 designs, and VexiiRiscv (520 KB / 7352 lines) is far
bigger than anything else this pipeline has built (the 107 template-library specimens were tiny,
few-LUT constructs) -- reusing a concurrency number from that workload without measuring this one
first already cost real time twice earlier on this same issue.  Logs memory high-water mark per build
so the next person has a real number instead of a guess.

  python3.15t scripts/cycloneiv_clean_real_design_match.py [--only sha1|picorv32|vexiiriscv]
Builds corpus/cycloneiv/real_<name>/ (gitignored like every other cycloneiv specimen, src/+design.toml
tracked).  Log tmp/logs/cycloneiv_clean_real_design_match.log.  Writes
tmp/logs/cycloneiv_clean_real_design_match_result.json.
"""
import argparse
import json
import logging
import os
import pickle
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
log = logging.getLogger("real_design_match")
DEVICE = "EP4CGX150DF31C7"
SRC = Path(REPO) / "sources" / "real-designs"
# Generous limits: these are real CPU/RISC-V cores, not tiny specimens -- fit in particular can run
# long on a design this size.  1800s fit is ~1.25x a conservative estimate for a few-thousand-LUT
# design at FAST FIT on this toolchain; raised if a real run needs it, logged either way.
LIMITS = {"quartus_map": 600, "quartus_fit": 1800, "quartus_asm": 180, "quartus_cpf": 30}

WRAPPERS = {
    "sha1": dict(
        src="sha_v2004.v", top="top", core_module="sha1",
        rtl='''module top(input clk, input rst, input [2:0] cmd_i, input cmd_w_i, output [3:0] cmd_o,
                   output [31:0] text_o);
  reg [31:0] text_i;
  always @(posedge clk) text_i <= text_i + 32'd1;   // free-running, not constant: keeps the datapath live
  sha1 u_core(.clk_i(clk), .rst_i(rst), .text_i(text_i), .text_o(text_o), .cmd_i(cmd_i), .cmd_w_i(cmd_w_i), .cmd_o(cmd_o));
endmodule
'''),
    "picorv32": dict(
        src="picorv32.v", top="top", core_module="picorv32",
        rtl='''module top(input clk, input resetn, output trap, output [7:0] mem_addr_lo, output [3:0] mem_wstrb);
  wire mem_valid, mem_instr, mem_la_read, mem_la_write;
  wire [31:0] mem_addr, mem_wdata, mem_la_addr, mem_la_wdata;
  wire [3:0] mem_la_wstrb;
  reg [31:0] mem_rdata;
  reg mem_ready;
  always @(posedge clk) begin
    mem_rdata <= mem_rdata + 32'd1;      // free-running "memory": keeps fetch/decode/execute live
    mem_ready <= mem_valid;              // always eventually acks, core never deadlocks waiting
  end
  wire [31:0] pcpi_rs1, pcpi_rs2;
  wire [31:0] irq = 32'd0;
  picorv32 #(.ENABLE_PCPI(0), .ENABLE_MUL(0), .ENABLE_DIV(0), .ENABLE_IRQ(0)) u_core(
    .clk(clk), .resetn(resetn), .trap(trap),
    .mem_valid(mem_valid), .mem_instr(mem_instr), .mem_ready(mem_ready),
    .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb),
    .mem_rdata(mem_rdata),
    .mem_la_read(mem_la_read), .mem_la_write(mem_la_write), .mem_la_addr(mem_la_addr),
    .mem_la_wdata(mem_la_wdata), .mem_la_wstrb(mem_la_wstrb),
    .pcpi_valid(), .pcpi_insn(), .pcpi_rs1(pcpi_rs1), .pcpi_rs2(pcpi_rs2),
    .pcpi_wr(1'b0), .pcpi_rd(32'd0), .pcpi_wait(1'b0), .pcpi_ready(1'b0),
    .irq(irq), .eoi());
  assign mem_addr_lo = mem_addr[7:0];
endmodule
'''),
    "vexiiriscv": dict(
        src="vexiiriscv_minimal.v", top="top", core_module="VexiiRiscv",
        rtl='''module top(input clk, input reset, output fetch_cmd_valid, output [31:0] fetch_cmd_addr,
                   output lsu_cmd_valid, output [31:0] lsu_cmd_addr);
  reg [31:0] fetch_word, lsu_data;
  reg fetch_rsp_valid, lsu_rsp_valid;
  always @(posedge clk) begin
    fetch_word <= fetch_word + 32'd1;      // free-running "instruction memory": keeps the pipeline live
    lsu_data <= lsu_data + 32'd1;
    fetch_rsp_valid <= fetch_cmd_valid;    // always eventually acks, never deadlocks waiting
    lsu_rsp_valid <= lsu_cmd_valid;
  end
  VexiiRiscv u_core(
    .PrivilegedPlugin_logic_rdtime(64'd0),
    .PrivilegedPlugin_logic_harts_0_int_m_timer(1'b0),
    .PrivilegedPlugin_logic_harts_0_int_m_software(1'b0),
    .PrivilegedPlugin_logic_harts_0_int_m_external(1'b0),
    .FetchCachelessPlugin_logic_bus_cmd_valid(fetch_cmd_valid),
    .FetchCachelessPlugin_logic_bus_cmd_ready(1'b1),
    .FetchCachelessPlugin_logic_bus_cmd_payload_id(),
    .FetchCachelessPlugin_logic_bus_cmd_payload_address(fetch_cmd_addr),
    .FetchCachelessPlugin_logic_bus_rsp_valid(fetch_rsp_valid),
    .FetchCachelessPlugin_logic_bus_rsp_payload_id(1'd0),
    .FetchCachelessPlugin_logic_bus_rsp_payload_error(1'b0),
    .FetchCachelessPlugin_logic_bus_rsp_payload_word(fetch_word),
    .LsuCachelessPlugin_logic_bus_cmd_valid(lsu_cmd_valid),
    .LsuCachelessPlugin_logic_bus_cmd_ready(1'b1),
    .LsuCachelessPlugin_logic_bus_cmd_payload_id(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_write(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_address(lsu_cmd_addr),
    .LsuCachelessPlugin_logic_bus_cmd_payload_data(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_size(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_mask(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_io(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_fromHart(),
    .LsuCachelessPlugin_logic_bus_cmd_payload_uopId(),
    .LsuCachelessPlugin_logic_bus_rsp_valid(lsu_rsp_valid),
    .LsuCachelessPlugin_logic_bus_rsp_payload_id(1'd0),
    .LsuCachelessPlugin_logic_bus_rsp_payload_error(1'b0),
    .LsuCachelessPlugin_logic_bus_rsp_payload_data(lsu_data),
    .clk(clk), .reset(reset));
endmodule
'''),
}


def build(name, spec):
    import cycloneiv_fuzz as fz
    import toolchain
    d = Path(REPO) / "corpus" / "cycloneiv" / f"real_{name}"
    shutil.rmtree(d, ignore_errors=True)
    (d / "src").mkdir(parents=True)
    q = d / "quartus"
    q.mkdir()
    shutil.copyfile(SRC / spec["src"], d / "src" / spec["src"])
    (d / "src" / "top.v").write_text(spec["rtl"])
    io_pins = {"sha1": ["clk", "rst", "cmd_i[0]", "cmd_i[1]", "cmd_i[2]", "cmd_w_i", "cmd_o[0]", "cmd_o[1]", "cmd_o[2]", "cmd_o[3]"]
                        + [f"text_o[{i}]" for i in range(32)],
               "picorv32": ["clk", "resetn", "trap", "mem_wstrb[0]", "mem_wstrb[1]", "mem_wstrb[2]", "mem_wstrb[3]"]
                           + [f"mem_addr_lo[{i}]" for i in range(8)],
               "vexiiriscv": ["clk", "reset", "fetch_cmd_valid", "lsu_cmd_valid"]
                             + [f"fetch_cmd_addr[{i}]" for i in range(8)] + [f"lsu_cmd_addr[{i}]" for i in range(8)]}[name]
    qsf = ["set_global_assignment -name AUTO_GLOBAL_CLOCK OFF", "set_global_assignment -name SEED 1"]
    (d / "design.toml").write_text(
        f'top = "top"\npurpose = "#188 real-design template match: {spec["core_module"]} ({spec["src"]}), '
        f'current Quartus install, EP4CGX150DF31C7"\nexercises = ["real_design_match"]\n'
        f'qsf = {json.dumps(qsf)}\ndevice = "{DEVICE}"\nio_pins_used = {len(io_pins)}\n')
    full = ['set_global_assignment -name FAMILY "Cyclone IV GX"', f"set_global_assignment -name DEVICE {DEVICE}",
            "set_global_assignment -name TOP_LEVEL_ENTITY top",
            f"set_global_assignment -name VERILOG_FILE ../src/{spec['src']}",
            "set_global_assignment -name VERILOG_FILE ../src/top.v",
            'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "AS INPUT TRI-STATED"',
            "set_global_assignment -name NUM_PARALLEL_PROCESSORS 1"] + qsf
    (q / "build.qsf").write_text("\n".join(full) + "\n")
    (q / "build.qpf").write_text('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    qb = toolchain.quartus_bin()
    t0 = time.time()
    steps = [("quartus_map", [f"{qb}/quartus_map", "build"]), ("quartus_fit", [f"{qb}/quartus_fit", "build"]),
             ("quartus_asm", [f"{qb}/quartus_asm", "build"]),
             ("quartus_cpf", [f"{qb}/quartus_cpf", "-c", "-o", "bitstream_compression=off", "build.sof", "build.rbf"])]
    for step, cmd in steps:
        tS = time.time()
        if not fz.run(step, cmd, q, d / "logs", LIMITS):
            raise SystemExit(f"{name}: {step} failed -- see {d / 'logs' / (step + '.log')}")
        log.info("%s: %s ok %.1fs", name, step, time.time() - tS)
    shutil.copyfile(q / "build.rbf", d / "bitstream.rbf")
    # post-fit sanity check: parse quartus_fit.summary for LUT/FF counts so a wrapper that let Quartus
    # optimize the whole core away to near-zero logic is caught here, not trusted silently downstream.
    fit_rpt = q / "build.fit.summary"
    luts = ffs = None
    if fit_rpt.exists():
        for line in fit_rpt.read_text(errors="replace").splitlines():
            if "Logic cells" in line or "Total logic elements" in line:
                luts = line
            if "Total registers" in line or "Dedicated logic registers" in line:
                ffs = line
    json.dump({"status": "ok", "elapsed_s": round(time.time() - t0, 1), "fit_summary_luts": luts, "fit_summary_ffs": ffs},
               open(d / "rebuild.json", "w"))
    shutil.rmtree(q)
    log.info("%s build ok %.0fs (luts=%s ffs=%s)", name, time.time() - t0, luts, ffs)
    return d / "bitstream.rbf", d


def lift(rbf, name):
    from lifters.cycloneiv_clean import emit
    import heavy_guard
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # NOT heavy_guard.JOB_GB["cyc4_clean_gate_base"]+4*["cyc4_clean_gate_worker"] (5.2 GB): that figure
    # was diagnosed as wrong for small lifts earlier on this same issue (borrowed from the full
    # 89,282-LUT DJI-image-scale gate sizing, never measured for a small design -- commit c2419f679,
    # cycloneiv_clean_template_library_build.py's PER_STRIP_GB fix).  These real-design lifts are
    # bigger than that fix's tiny template specimens (SHA-1 alone: 1,496 LUTs vs a handful) but far
    # smaller than the full DJI image (89,282 LUTs) -- no existing measured figure fits this size
    # class, so this is a first estimate, corrected by the RSS-delta logged below on every run.
    PER_LIFT_GB = 2.5
    t0 = time.time()
    with heavy_guard.lease(PER_LIFT_GB, f"cyc4_real_design_lift_{name}", log):
        cx = emit.Ctx()
        nl = emit.Builder(cx, str(rbf), None).run()
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    log.info("%s: lifted %.1fs, %d LUTs, %d FFs, RSS delta %.0f MB", name, time.time() - t0, len(nl.luts), len(nl.ffs),
              (rss_after - rss_before) / 1024)
    return nl


def run_match(nl, name, d):
    pkl = d / "nl.pkl"
    pickle.dump(nl, open(pkl, "wb"))
    out = d / "match_result.json"
    cmd = [sys.executable, str(Path(REPO) / "scripts" / "cycloneiv_clean_template_match.py"), "--nl", str(pkl)]
    log.info("%s: running matcher: %s", name, " ".join(cmd))
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=600)
    log.info("%s: matcher rc=%d", name, r.returncode)
    if r.returncode != 0:
        log.error("%s: matcher stderr tail:\n%s", name, r.stderr[-4000:])
        return None
    default_out = Path(REPO) / "tmp" / "logs" / "cycloneiv_clean_template_match_result.json"
    shutil.copyfile(default_out, out)
    return json.load(open(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(WRAPPERS), default=None)
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                         handlers=[logging.StreamHandler(),
                                   logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_real_design_match.log"))])
    names = [a.only] if a.only else list(WRAPPERS)
    results = {}
    for name in names:
        spec = WRAPPERS[name]
        if not (SRC / spec["src"]).exists():
            log.error("%s: source %s not found, skipping", name, SRC / spec["src"])
            results[name] = {"error": f"source not found: {spec['src']}"}
            continue
        log.info("=== %s (%s) ===", name, spec["src"])
        rbf, d = build(name, spec)
        nl = lift(rbf, name)
        if len(nl.luts) < 50:
            log.error("%s: only %d LUTs post-lift -- Quartus likely optimized the core away; wrapper needs fixing, NOT trusting this result", name, len(nl.luts))
            results[name] = {"error": f"suspiciously small lift: {len(nl.luts)} LUTs, {len(nl.ffs)} FFs -- wrapper let Quartus strip the core"}
            continue
        match = run_match(nl, name, d)
        results[name] = dict(luts=len(nl.luts), ffs=len(nl.ffs), match=match)
    out = Path(REPO) / "tmp" / "logs" / "cycloneiv_clean_real_design_match_result.json"
    json.dump(results, open(out, "w"), indent=1, default=str)
    log.info("DONE -> %s", out)
    print(json.dumps({k: ({**v, "match": {kk: vv for kk, vv in (v.get("match") or {}).items() if kk != "matched_detail"}} if "match" in v else v)
                       for k, v in results.items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
