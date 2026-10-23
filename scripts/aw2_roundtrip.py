#!/usr/bin/env python3.15t
"""Structural round-trip of a lifted board design through Diamond (issue #84).

    bitstream --lift--> out/<label>.v --Diamond (LSE + map + PAR + bitgen)--> bitstream'
        --native decode--> config' --compare--> config (the original decode)

No source RTL exists for the board design, so the oracle is the vendor flow itself: if the
lift is complete, Diamond should rebuild an equivalent configuration.  The stages are
reported in order; the run stops at the first stage that fails and says which one.  Every
number is a raw count (missing / extra / wrong kept separate; see CLAUDE.md "Scoring faults").

    python3.15t scripts/aw2_roundtrip.py --board boards/aw2-2d82auto --label V07 \
        --config tmp/v7/FPGA_V07.bin.config [--prep-only]

Work dir tmp/rt/<label>/ ; log tmp/logs/aw2_roundtrip.log ; result tmp/rt/<label>/result.json.
Diamond is single-seat: heavy_guard lock + RAM gate.
"""
import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import efb_oracle as E  # noqa: E402
import heavy_guard  # noqa: E402
import native_config  # noqa: E402
import toolchain  # noqa: E402

LOG = REPO / "tmp" / "logs" / "aw2_roundtrip.log"
E.LOG = LOG
# First Diamond run on a 2636-LUT-expression netlist: no measurement yet.  STALL_S is the
# primary guard (no growth of diamond.log); OVERALL_S is replaced by 3x the measured
# worst case once one run completes (the run logs "took").
E.STALL_S = 120
E.OVERALL_S = 1800

_STUB_RE = re.compile(r"\(\*\s*blackbox\s*\*\)\s*\n\s*module\s+EFB\b.*?\n\s*endmodule\s*\n", re.S)
_TEMPLATE_RE = re.compile(r"module efb_spi_slave \(.*?\n\s*endmodule\s*\n", re.S)


def prep_verilog(src):
    """Make the lifted Verilog acceptable to Diamond: drop our EFB stub so the primitive is used."""
    s = _STUB_RE.sub("", src)
    s = _TEMPLATE_RE.sub("", s)
    return s


def ghosts_as_inputs(v, wires):
    """Make every undriven wire a top-level input so synthesis cannot prune its cone.

    EXPERIMENT ONLY (not a lift): measures how much of the recovered logic survives
    synthesis when the missing drivers are supplied from outside.
    """
    names = [w for w in wires if re.fullmatch(r"\w+", w)]
    for w in names:
        v, n = re.subn(rf"^    wire (\[[^\]]*\] )?{re.escape(w)};[^\n]*\n", "", v, count=1, flags=re.M)
        if n != 1:
            raise SystemExit(f"no plain 'wire {w};' declaration to promote")
    i = v.index("module aw2 (") + len("module aw2 (\n")
    v = v[:i] + "".join(f"    input wire {w},\n" for w in names) + v[i:]
    return v, len(names)


def lpf_for(label):
    """LOCATE/IOBUF per resolved pad from the DB (port names are the emitted ones).

    Bank VCCIO is board data, not in the bitstream: the decoded type OUTPUT_LVTTL33 is the
    LVCMOS/LVTTL class.  A bank holding any SSTL25 pad is 2.5 V, so its LVTTL33-class pads
    are emitted as LVCMOS25; Diamond rejects mixed voltages in a bank otherwise.
    """
    import db
    from sqlalchemy import text
    import verilog   # port-name sanitising lives with the emitter
    iodb = json.loads((REPO / "device-db/MachXO2/LCMXO2-1200/iodb.json").read_text())
    bank_of = {(m["row"], m["col"], m["pio"]): m["bank"] for m in iodb["pio_metadata"]}
    lines = ["BLOCK RESETPATHS;", "BLOCK ASYNCPATHS;", ""]
    seen = set()
    with db.engine().connect() as c:
        bs = c.execute(text("select id from bitstreams where label=:l"), {"l": label}).scalar()
        rows = c.execute(text("select pin, label, direction, iostd, drive, pull, row, col, pio "
                              "from pad_map where bitstream=:b and (net_in is not null or "
                              "net_out is not null) order by pin"), {"b": bs}).fetchall()
    v25_banks = {bank_of.get((r, cc, p)) for _pin, _l, _d, std, _dr, _pu, r, cc, p in rows
                 if std and "SSTL25" in std}
    for pin, lbl, direction, iostd, drive, pull, r, cc, p in rows:
        base = verilog._sanitise(lbl)
        port = f"pin{pin}" if (base == "_" or base in seen) else base
        seen.add(port)
        io = (iostd or "").split("_", 1)[-1] if iostd else "LVTTL33"
        io = "LVCMOS33" if io == "LVTTL33" else io
        if io == "LVCMOS33" and bank_of.get((r, cc, p)) in v25_banks:
            io = "LVCMOS25"
        attrs = f"IO_TYPE={io}"
        if drive and direction != "in":
            attrs += f" DRIVE={drive}"
        if pull and pull not in ("NONE", "FAILSAFE"):
            attrs += f" PULLMODE={pull}"
        lines.append(f'LOCATE COMP "{port}" SITE "{pin}";')
        lines.append(f'IOBUF PORT "{port}" {attrs};')
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", required=True)
    ap.add_argument("--label", default="V07")
    ap.add_argument("--config", required=True)
    ap.add_argument("--prep-only", action="store_true")
    ap.add_argument("--ghosts-as-inputs", action="store_true",
                    help="EXPERIMENT: undriven wires become input ports; synthesis + map only")
    a = ap.parse_args()
    log = E.setup_logging()
    work = REPO / "tmp" / "rt" / a.label
    work.mkdir(parents=True, exist_ok=True)
    cfg = tomllib.loads((Path(a.board) / "board.toml").read_text())
    result = {"label": a.label, "stages": {}}

    def done(stage, **kw):
        result["stages"][stage] = kw
        (work / "result.json").write_text(json.dumps(result, indent=1, sort_keys=True, default=str))
        log.info("[%s] %s", stage, kw)

    v = (REPO / "out" / f"{a.label}.v").read_text()
    pv = prep_verilog(v)
    if a.ghosts_as_inputs:
        import subprocess
        (work / "yosys_in.v").write_text(v)       # with the EFB stub: yosys needs its port directions
        r = subprocess.run(["yosys", "-p", f"read_verilog -sv {work/'yosys_in.v'}; hierarchy -top "
                            f"{cfg['board']['top']}; proc; check"], capture_output=True, text=True)
        wires = sorted(set(re.findall(r"Wire \S*?\.\\?(\S+) is used but has no driver",
                                      r.stdout + r.stderr)))
        ports = set(re.findall(r"^\s+(?:input|output|inout)\s+wire\s+(\w+)", pv, re.M))
        pv, nghost = ghosts_as_inputs(pv, [w for w in wires if w not in ports])
        work = work.parent / (a.label + "_ghost")
        work.mkdir(parents=True, exist_ok=True)
        log.info("%d undriven internal wires promoted to inputs", nghost)
    (work / "fuzz.v").write_text(pv)
    (work / "fuzz.lpf").write_text((lpf_for(a.label) if not a.ghosts_as_inputs else
                                    "BLOCK RESETPATHS;\nBLOCK ASYNCPATHS;\n") + "\n")
    (work / "fuzz.ldf").write_text(E.LDF % E.STY)
    (work / "run.tcl").write_text(E.TCL if not a.ghosts_as_inputs else E.TCL_MAP_ONLY)
    done("prep", verilog_bytes=(work / "fuzz.v").stat().st_size,
         ports_located=(work / "fuzz.lpf").read_text().count("LOCATE"), top=cfg["board"]["top"])
    if a.prep_only:
        return 0

    heavy_guard.wait_available(log, "diamond aw2 round-trip")
    with heavy_guard.heavy_lock(f"aw2_roundtrip {a.label}", log):
        ok, el, detail = E.run_diamond(work, log, need_bit=not a.ghosts_as_inputs)
    done("diamond", ok=ok, seconds=round(el, 1), detail=detail)
    # Which Diamond stage stopped, from its logs
    syn = work / "impl1" / "synthesis.log"
    if syn.exists():
        t = syn.read_text(errors="replace")
        done("synthesis_log", lines=len(t.splitlines()),
             errors=re.findall(r"^ERROR.*$", t, re.M)[:10],
             warnings=len(re.findall(r"^WARNING", t, re.M)))
    mrp = next(iter((work / "impl1").glob("*.mrp")), None)
    if mrp and mrp.exists():
        t = mrp.read_text(errors="replace")
        done("map_report", **{k: v for k, v in
                              re.findall(r"^\s*(Number of .*?):\s+(\d+ out of \d+)", t, re.M)[:12]})
    if not ok or a.ghosts_as_inputs:
        return 0 if ok else 1

    new_cfg = work / "new.config"
    text, _pb, _b = native_config.config_from_file(
        str(work / "impl1" / "fuzz_impl1.bit"), device=E.DEVICE,
        db_root=toolchain.trellis_dbroot())
    new_cfg.write_text(text)
    import diamond_roundtrip as D
    cmp = D.compare_configs(a.config, new_cfg)
    done("compare", **{k: v for k, v in cmp.items() if k not in ("orig_luts", "new_luts")},
         orig_lut_count=sum(cmp["orig_luts"].values()), new_lut_count=sum(cmp["new_luts"].values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
