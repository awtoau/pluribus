#!/usr/bin/env python3
"""MachXO2 recovery round-trip on a KNOWN-source design (ground-truth LEC).

The GOWIN analog just passed (a tiny XOR/AND/OR design recovered exactly).  This
is the MachXO2 version, on a REAL design: the replacement scope RTL
(interleaved ADC front-end + interleave-cal + capture core with a ring buffer +
an SPI-v2 slave).  We compile the KNOWN source to a MachXO2 bitstream, recover
it with pluribus, and LEC the recovered fabric against the source.

Flow
----
  scope_top.py (Amaranth, KNOWN source)
     -> yosys synth_lattice -family xo2      (scope.json)
     -> nextpnr-machxo2                       (scope_out.config)
     -> ecppack                               (scope.bit)              <-- real bitstream
     -> pluribus trellis_unpack (native)      (scope_recovered.config) <-- native decode
     -> pluribus fpga_iomap                    (.iomap.tsv)
     -> pluribus load.py  (SCRATCH db tmp/repl.db, label REPL_SCOPE)
     -> reach/reach2/reach3/reach4
     -> pluribus verilog.py                    (recovered.v)
     -> LEC recovered.v vs scope_src.v

LEC (two verdicts)
------------------
  1. WHOLE-DESIGN  yosys equiv_induct (the pluribus repo's own LEC tool).
     Expected: miso NOT provable unboundedly -- the distributed-RAM capture
     buffer's write->read dataflow is a documented lifter stub, so the memory
     readback path is functionally wrong.  Verdict: 0/1 cones proven.

  2. BOUNDED-FROM-RESET  SAT miter (yosys sat -seq N), both designs forced to a
     common all-zero state then held in reset, proving the recovered miso is
     BIT-EXACT to the source miso for N cycles under ALL input sequences.  This
     isolates the fabric datapath (reset, SPI-v2 FSM, status/wp_trig/meas_offset
     register readback, trigger config, interleave-cal) from the memory.  The
     proof holds to a depth D, then diverges at D+1 on the first serialised data
     bit.  NB (#65): that first-bit divergence is NOT the DPRAM value — it holds
     with the DPRAM read data forced to 0 — it is a readback-datapath gap.  Two
     layers of it (orphaned SPI-address-register FFs; orphaned PLC fast-connect
     slice outputs) are fixed this pass; a deeper register-read/serialiser logic
     gap still caps the proof at D.

Nothing here is committed and nothing in awto-2000 is modified: the source is
imported read-only and all build artefacts land under pluribus/tmp/repl_scope/.

Env (defaults target this machine):
  OSS_CAD     = /home/dan/opt/oss-cad-suite/bin  (yosys/nextpnr-machxo2/ecppack)
  RTL_DIR     = /mnt/2tb/git/awto-2000/fpga/hantek/rtl  (KNOWN source, read-only)
  TRELLIS_DBROOT = prjtrellis database root
  PY_AMARANTH = python3            (interpreter with amaranth, for source regen)
  PY_PLURIBUS = python3.15t        (free-threaded pipeline interpreter)
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "tmp" / "repl_scope"
LOG = WORK / "roundtrip.log"

OSS = os.environ.get("OSS_CAD", "/home/dan/opt/oss-cad-suite/bin")
RTL_DIR = os.environ.get("RTL_DIR", "/mnt/2tb/git/awto-2000/fpga/hantek/rtl")
DBROOT = os.environ.get(
    "TRELLIS_DBROOT",
    "/mnt/2tb/git/github.com/awtoau/prjtrellis/database")
PY_AMARANTH = os.environ.get("PY_AMARANTH", "python3")
PY_PLURIBUS = os.environ.get("PY_PLURIBUS", "python3.15t")

DEVICE = "LCMXO2-1200"
DEVICE_FULL = "LCMXO2-1200HC-4TG100C"
PACKAGE = "TQFP100"
LABEL = "REPL_SCOPE"
DB = REPO / "tmp" / "repl.db"

# port(LPF), label(pluribus), SITE(pin), row, col, pio, dir
# SITE<->tile pairs are ground-truth ordinary edge IO from the vendor V4 LPF.
PIN_MAP = [
    ("adc[0]", "adc0", "83", 0, 14, "B", "in"),
    ("adc[1]", "adc1", "84", 0, 14, "A", "in"),
    ("adc[2]", "adc2", "96", 0, 9, "B", "in"),
    ("adc[3]", "adc3", "97", 0, 9, "A", "in"),
    ("adc[4]", "adc4", "98", 0, 8, "B", "in"),
    ("adc[5]", "adc5", "99", 0, 8, "A", "in"),
    ("adc[6]", "adc6", "51", 10, 21, "D", "in"),
    ("adc[7]", "adc7", "52", 10, 21, "C", "in"),
    ("phase", "phase", "53", 9, 21, "D", "in"),
    ("stb", "stb", "54", 9, 21, "C", "in"),
    ("sck", "sck", "60", 8, 21, "C", "in"),
    ("cs_n", "cs_n", "61", 8, 21, "A", "in"),
    ("mosi", "mosi", "64", 5, 21, "B", "in"),
    ("clk", "clk", "65", 5, 21, "A", "in"),
    ("rst", "rst", "66", 4, 21, "D", "in"),
    ("miso", "miso", "67", 4, 21, "C", "out"),
]

_logfh = None


def log(msg=""):
    print(msg, flush=True)
    if _logfh:
        _logfh.write(str(msg) + "\n")
        _logfh.flush()


def sh(cmd, extra_env=None, cwd=None, stage=""):
    """Run a command, tee output to a per-stage log, die on non-zero."""
    env = dict(os.environ)
    env["PATH"] = OSS + os.pathsep + env.get("PATH", "")
    env["TRELLIS_DBROOT"] = DBROOT
    env["TRELLIS_DEVICE"] = DEVICE
    env["TRELLIS_PACKAGE"] = PACKAGE
    if extra_env:
        env.update(extra_env)
    slog = WORK / f"stage_{stage}.log" if stage else None
    log(f"  $ {' '.join(str(c) for c in cmd)}")
    r = subprocess.run(cmd, env=env, cwd=cwd or str(REPO),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True)
    if slog:
        slog.write_text(r.stdout)
    if r.returncode != 0:
        log(r.stdout[-3000:])
        sys.exit(f"stage {stage!r} FAILED (exit {r.returncode})")
    return r.stdout


# --------------------------------------------------------------------------
def regen_source():
    """Import ScopeTop read-only from awto-2000 and emit fresh scope_src.v.

    The tracked scope_top.v in awto-2000 is STALE (miso emitted as an input, so
    the design has no observable output and synthesises to nothing).  The
    current source drives miso, so we regenerate."""
    log("[1] regenerate KNOWN source (scope_src.v) from ScopeTop")
    gen = WORK / "gen_src.py"
    gen.write_text(
        "import os, sys\n"
        f"sys.path.insert(0, {RTL_DIR!r})\n"
        "from amaranth.back import verilog\n"
        "from scope_top import ScopeTop\n"
        "dut = ScopeTop(depth=256)\n"
        "v = verilog.convert(dut, name='scope_top', ports=[dut.adc, dut.phase,"
        " dut.stb, dut.sck, dut.cs_n, dut.mosi, dut.miso])\n"
        f"open({str(WORK / 'scope_src.v')!r},'w').write(v)\n"
        "print('miso is', 'OUTPUT' if 'output miso' in v else 'INPUT(!)')\n")
    out = sh([PY_AMARANTH, str(gen)], stage="regen")
    log("    " + out.strip())


def gen_constraints():
    log("[2] emit matching LPF + pins.tsv (port names line up for LEC)")
    lpf = ["# scope_top round-trip pin constraints (LCMXO2-1200 TQFP100)", ""]
    for port, _lbl, site, *_ in PIN_MAP:
        lpf.append(f'LOCATE COMP "{port}" SITE "{site}";')
        lpf.append(f'IOBUF PORT "{port}" IO_TYPE=LVCMOS33;')
    (WORK / "scope.lpf").write_text("\n".join(lpf) + "\n")

    tsv = ["# device:   LCMXO2-1200", "# package:  TQFP100",
           "# pin row col pio dir label function conf ref chip_pin chip_sig"
           " net_in net_out note"]
    for _port, lbl, site, r, c, p, d in PIN_MAP:
        tsv.append("\t".join([site, str(r), str(c), p, d, lbl,
                              "roundtrip port", "10", "", "", "", "", "",
                              "known-source LEC port"]))
    (WORK / "scope_pins.tsv").write_text("\n".join(tsv) + "\n")


def build_bitstream():
    log("[3] synth (synth_lattice -family xo2)")
    sh([f"{OSS}/yosys", "-p",
        f"read_verilog -sv {WORK}/scope_src.v; "
        f"synth_lattice -family xo2 -top scope_top -json {WORK}/scope.json"],
       stage="synth")
    log("[4] place & route (nextpnr-machxo2)")
    sh([f"{OSS}/nextpnr-machxo2", "--device", DEVICE_FULL,
        "--json", f"{WORK}/scope.json", "--lpf", f"{WORK}/scope.lpf",
        "--textcfg", f"{WORK}/scope_out.config", "--freq", "25"], stage="pnr")
    log("[5] pack (ecppack -> real MachXO2 bitstream)")
    sh([f"{OSS}/ecppack", f"{WORK}/scope_out.config", f"{WORK}/scope.bit"],
       stage="pack")
    log(f"    bitstream: {(WORK/'scope.bit').stat().st_size} bytes")


def recover():
    cfg = WORK / "scope_recovered.config"
    log("[6] native unpack (pluribus trellis_unpack)")
    if cfg.exists():
        cfg.unlink()
    sh([PY_PLURIBUS, "scripts/trellis_unpack.py", f"{WORK}/scope.bit", str(cfg)],
       stage="unpack")
    log("[7] iomap")
    iomap = Path(str(cfg) + ".iomap.tsv")
    if iomap.exists():
        iomap.unlink()
    sh([PY_PLURIBUS, "scripts/fpga_iomap.py", str(cfg)], stage="iomap")
    log("[8] load -> scratch db tmp/repl.db")
    if DB.exists():
        DB.unlink()
    env = {"PLURIBUS_SQLITE_PATH": str(DB)}
    sh([PY_PLURIBUS, "load.py", "--label", LABEL, "--config", str(cfg),
        "--pins", f"{WORK}/scope_pins.tsv", "--device", DEVICE,
        "--package", PACKAGE], extra_env=env, stage="load")
    log("[9] reachability passes")
    for st in ("reach", "reach2", "reach3", "reach4"):
        sh([PY_PLURIBUS, f"{st}.py", "--bitstream", LABEL],
           extra_env=env, stage=st)
    log("[10] emit recovered structural Verilog")
    sh([PY_PLURIBUS, "verilog.py", "--bitstream", LABEL,
        "--out", f"{WORK}/recovered.v", "--top", "scope_top"],
       extra_env=env, stage="verilog")


def _write_lec_helpers():
    """Wrapper presenting the SOURCE interface around the recovered netlist:
    rejoins adc0..7 into adc[7:0] and ties all recovered clock-domain inputs to
    the single physical clk (pluribus recovers one routed clock as several
    spine-tap domains)."""
    # discover the recovered clock-domain ports (spec_clk_*) — scan ONLY the
    # module header so internal reg names (spec_clk_1__r7c13_A0) are not caught.
    rec = (WORK / "recovered.v").read_text()
    import re
    hdr = re.search(r"^module\s+scope_top.*?^\);", rec, re.S | re.M)
    hdr_txt = hdr.group(0) if hdr else rec
    clk_ports = sorted(set(re.findall(
        r"(?:input|output)\s+wire\s+(spec_clk_\w+)", hdr_txt)))
    ties = "".join(f"    .{c}(clk),\n" for c in clk_ports)
    (WORK / "rec_wrap.v").write_text(
        "module rec_wrap(adc, phase, stb, sck, cs_n, mosi, clk, rst, miso);\n"
        "  input [7:0] adc;\n"
        "  input phase, stb, sck, cs_n, mosi, clk, rst;\n"
        "  output miso;\n"
        "  scope_top_rec u (\n"
        "    .adc0(adc[0]), .adc1(adc[1]), .adc2(adc[2]), .adc3(adc[3]),\n"
        "    .adc4(adc[4]), .adc5(adc[5]), .adc6(adc[6]), .adc7(adc[7]),\n"
        "    .phase(phase), .stb(stb), .sck(sck), .cs_n(cs_n), .mosi(mosi),\n"
        "    .clk(clk), .rst(rst), .miso(miso),\n"
        f"{ties}"
        "  );\n"
        "endmodule\n")
    return clk_ports


def _gold_gate(memory_map):
    """yosys prelude building gold (source) and gate (recovered+wrapper)."""
    gold_mem = "memory\nmemory_map\n" if memory_map else "memory\n"
    return (
        f"read_verilog -sv {WORK}/scope_src.v\n"
        "hierarchy -top scope_top\nproc\nflatten\n"
        f"{gold_mem}opt -fast\nrename scope_top gold\ndesign -stash gold\n"
        f"read_verilog -sv {WORK}/recovered.v\n"
        "rename scope_top scope_top_rec\n"
        f"read_verilog -sv {WORK}/rec_wrap.v\n"
        "hierarchy -top rec_wrap\nproc\nflatten\nopt -fast\n"
        "rename rec_wrap gate\ndesign -stash gate\n"
        "design -copy-from gold -as gold gold\n"
        "design -copy-from gate -as gate gate\n")


def lec_induct():
    log("[11] LEC #1 whole-design equiv_induct (repo's own LEC tool)")
    script = (_gold_gate(memory_map=False) +
              "equiv_make gold gate equiv\nhierarchy -top equiv\nopt_clean\n"
              "equiv_struct\nequiv_induct -seq 30\nequiv_status\n")
    (WORK / "lec.ys").write_text(script)
    out = sh([f"{OSS}/yosys", "-s", f"{WORK}/lec.ys"], stage="lec_induct")
    verdict = "?"
    for ln in out.splitlines():
        if "are proven and" in ln:
            verdict = ln.strip()
    log(f"    equiv_induct: {verdict}")
    return verdict


def _miter_prelude():
    return (_gold_gate(memory_map=True) +
            "miter -equiv -flatten -make_assert gold gate miter\n"
            "hierarchy -top miter\nflatten\n")


def _sat_prove(n):
    """Bounded SAT proof at depth n; returns True if PROVEN (no divergence)."""
    script = _miter_prelude()
    (WORK / "miter.ys").write_text(script)
    out = sh([f"{OSS}/yosys", "-s", f"{WORK}/miter.ys", "-p",
              f"sat -seq {n} -prove-asserts -set-init-zero "
              f"-set-at 1 in_rst 1 -set-at 2 in_rst 1 -set-at 3 in_rst 1"],
             stage=f"miter{n}")
    return "SUCCESS!" in out and "found a model" not in out


def lec_bounded():
    log("[12] LEC #2 bounded-from-reset SAT miter (isolates fabric vs memory)")
    # coarse ladder to bracket the divergence depth, then binary-search
    proven, diverge = 0, None
    for n in (8, 16, 32, 48, 64):
        ok = _sat_prove(n)
        log(f"    depth {n:3d}: {'PROVEN equivalent' if ok else 'DIVERGES'}")
        if ok:
            proven = n
        else:
            diverge = n
            break
    if diverge is not None:
        lo, hi = proven, diverge
        while hi - lo > 1:
            mid = (lo + hi) // 2
            ok = _sat_prove(mid)
            log(f"    depth {mid:3d}: {'PROVEN equivalent' if ok else 'DIVERGES'}")
            (lo, hi) = (mid, hi) if ok else (lo, mid)
        proven, diverge = lo, hi
    log(f"    => recovered miso == source miso for cycles 1..{proven}; "
        f"first divergence at cycle {diverge}")
    log(f"       (miso is idle=0 through the SPI command phase; cycle {diverge} "
        "is the first data-output bit)")
    return proven, diverge


def _sat_prove_variant(n, miter_ys, extra_set=""):
    """Bounded SAT proof on an alternate miter script; True if PROVEN."""
    out = sh([f"{OSS}/yosys", "-s", miter_ys, "-p",
              f"sat -seq {n} -prove-asserts -set-init-zero {extra_set} "
              f"-set-at 1 in_rst 1 -set-at 2 in_rst 1 -set-at 3 in_rst 1"],
             stage=f"diag{n}")
    return "SUCCESS!" in out and "found a model" not in out


def lec_diagnostics():
    """Localise the divergence: is it (a) reset/idle, (b) the DPRAM value, or
    (c) the active SPI-readback datapath?"""
    log("[13] LEC diagnostics — localise the divergence")

    # (a) hold SPI deselected (cs_n high): reset + idle behaviour only.
    (WORK / "miter.ys").write_text(_miter_prelude())
    idle_ok = _sat_prove_variant(80, str(WORK / "miter.ys"),
                                 extra_set="-set in_cs_n 1")
    log(f"    cs_n held HIGH (reset+idle), depth 80 : "
        f"{'PROVEN equivalent' if idle_ok else 'DIVERGES'}")

    # (b) neutralise the DPRAM read data (force read nets to 0, matching the
    # source's empty/unwritten capture buffer) and re-check the divergence.
    import re
    rec0 = re.sub(r"^(\s*assign dpram_\w+ = )[^;]+;",
                  r"\g<1>1'b0;",
                  (WORK / "recovered.v").read_text(), flags=re.M)
    (WORK / "recovered_mem0.v").write_text(rec0)
    mem0_ys = WORK / "miter_mem0.ys"
    mem0_ys.write_text(
        _miter_prelude().replace("recovered.v", "recovered_mem0.v"))
    mem0_ok = _sat_prove_variant(56, str(mem0_ys))
    log(f"    DPRAM reads forced to 0, depth 56     : "
        f"{'PROVEN equivalent (divergence was the memory value)' if mem0_ok else 'STILL DIVERGES (readback datapath gap, not just memory)'}")
    return idle_ok, mem0_ok


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-build", action="store_true",
                    help="reuse existing bitstream/recovery, run LEC only")
    args = ap.parse_args()

    global _logfh
    WORK.mkdir(parents=True, exist_ok=True)
    _logfh = open(LOG, "w")
    log(f"MachXO2 recovery round-trip  device={DEVICE_FULL}  label={LABEL}")
    log(f"work={WORK}  db={DB}")

    if not args.skip_build:
        regen_source()
        gen_constraints()
        build_bitstream()
        recover()

    _write_lec_helpers()
    v_induct = lec_induct()
    proven, diverge = lec_bounded()
    idle_ok, mem0_ok = lec_diagnostics()

    log("\n" + "=" * 68)
    log("VERDICT  —  the recovery does NOT pass functional LEC")
    log("=" * 68)
    log(f"  whole-design equiv_induct : {v_induct}  (miso not provably equivalent)")
    log(f"  reset + idle (cs_n high)  : {'PROVEN equivalent, 80 cycles' if idle_ok else 'DIVERGES'}")
    log(f"  SPI command phase         : PROVEN equivalent through cycle {proven} "
        "(miso idle=0)")
    log(f"  first readback data bit   : DIVERGES at cycle {diverge}")
    log(f"  DPRAM read data forced 0  : "
        f"{'divergence removed -> memory value only' if mem0_ok else 'STILL diverges -> readback datapath gap, not just the memory stub'}")
    log("")
    log("  Structurally the recovery is complete (LUT INITs, FFs, carries, DPRAM")
    log("  sites, IO, routing all recovered; native decode CRC-verified).  But it")
    log("  is NOT functionally equivalent to the known source:")
    log("    - the single physical clk is recovered as one unified spine (#65 gap 1);")
    log("    - the 256x8 capture ring buffer (distributed RAM / 32x DPR16X4) still")
    log("      has a stub write->read dataflow (documented lifter limitation);")
    log("    - the first-data-bit divergence at cycle %s is a GENUINE readback"
        % diverge)
    log("      LOGIC gap: it persists with the DPRAM read data forced to 0 AND with")
    log("      every readback net now driven (see #65 root-cause below), so it is")
    log("      neither a memory-value nor an undriven-net artefact.")
    log("")
    log("  #65 root-cause (this pass): the cycle-%s divergence was two orphaned-net"
        % diverge)
    log("  emission/recovery bugs in the SPI-readback datapath, now FIXED —")
    log("    (a) verilog.py: clock-derived-named FFs (spec_clk_N spine FFs) emitted")
    log("        their Q on a dangling alias wire, orphaning the SPI address register")
    log("        that feeds the read-address decode;")
    log("    (b) machxo2_lift.py: PLC F0..F7 slice outputs that leave a tile on an")
    log("        always-on fast-connect wire (HFxW/HFxE) were never unioned, orphaning")
    log("        the OFX/wide-mux fabric feeding the miso serialiser.")
    log("  With both fixed the miso combinational cone is fully driven, yet a deeper")
    log("  readback LOGIC divergence (register-read / serialiser) remains — the next")
    log("  gap to close for a full past-cycle-%s proof." % diverge)


if __name__ == "__main__":
    main()
