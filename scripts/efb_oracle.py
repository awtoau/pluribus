#!/usr/bin/env python3.15t
"""Diamond oracle for the MachXO2 EFB: config-register payload + input-side routing (#100).

Builds small EFB designs with Diamond (one at a time), then:
  * decodes each bitstream natively and records the `.efb_block` payload, so every
    EFB attribute maps to payload bits by vendor evidence (single-attribute toggles);
  * for `wb_in` (every WISHBONE/SPI input driven by its own flop or pin) runs the
    ncdread/ncd2nmc routing oracle and compares each EFB INPUT pin's net against
    the lifted design (driver flop location).

    python3.15t scripts/efb_oracle.py build [--only NAME ...]
    python3.15t scripts/efb_oracle.py compare

Work dir tmp/efb_oracle/<variant>/ ; results tmp/efb_oracle/results.json ;
log tmp/logs/efb_oracle.log.  Diamond is single-seat: heavy_guard lock + RAM gate
before every build.
"""
import argparse
import json
import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import toolchain  # noqa: E402
import heavy_guard  # noqa: E402

WORK = REPO / "tmp" / "efb_oracle"
LOG = REPO / "tmp" / "logs" / "efb_oracle.log"
STY = REPO / "diamond-fuzz" / "aw21.sty"
DEVICE = "LCMXO2-1200"

# Diamond PAR + Bitgen on a ~25-cell design: measured <= 5 s (one poll tick), 2 builds.
# STALL_S: no growth of diamond.log (primary guard).  OVERALL_S: 6x measured (backstop).
# Expiry: process killed, variant marked failed with last log line + elapsed time.
STALL_S = 30
OVERALL_S = 30
POLL_S = 1     # log-size poll tick; resolves the measured 5 s build

BASE_ATTRS = {
    "EFB_I2C1": "DISABLED", "EFB_I2C2": "DISABLED", "EFB_SPI": "ENABLED",
    "EFB_TC": "DISABLED", "EFB_UFM": "DISABLED", "SPI_MODE": "SLAVE",
    "EFB_WB_CLK_FREQ": "100.0",
}
# one attribute changed per variant, SPI slave side
VARIANTS = {
    "spi_default": {},
    "spi_lsb": {"SPI_LSB_FIRST": "ENABLED"},
    "spi_clkinv": {"SPI_CLK_INV": "ENABLED"},
    "spi_phase": {"SPI_PHASE_ADJ": "ENABLED"},
    "spi_handshake": {"SPI_SLAVE_HANDSHAKE": "ENABLED"},
    "spi_intr_rxrdy": {"SPI_INTR_RXRDY": "ENABLED"},
    "spi_intr_txrdy": {"SPI_INTR_TXRDY": "ENABLED"},
    "spi_intr_rxovr": {"SPI_INTR_RXOVR": "ENABLED"},
    "spi_intr_txovr": {"SPI_INTR_TXOVR": "ENABLED"},
    "spi_wakeup": {"SPI_WAKEUP": "ENABLED"},
    "spi_master": {"SPI_MODE": "MASTER"},
    "spi_master_div": {"SPI_MODE": "MASTER", "SPI_CLK_DIVIDER": "8"},
    "wb_in": {},          # same attrs as spi_default, flop-driven inputs
}

EFB_PORTS_TIED = (
    "PLL0DATI7 PLL0DATI6 PLL0DATI5 PLL0DATI4 PLL0DATI3 PLL0DATI2 PLL0DATI1 PLL0DATI0 PLL0ACKI "
    "PLL1DATI7 PLL1DATI6 PLL1DATI5 PLL1DATI4 PLL1DATI3 PLL1DATI2 PLL1DATI1 PLL1DATI0 PLL1ACKI "
    "I2C1SCLI I2C1SDAI I2C2SCLI I2C2SDAI SPISCKI SPIMISOI SPIMOSII TCCLKI TCRSTN TCIC UFMSN"
).split()


def verilog(name, attrs):
    a = dict(BASE_ATTRS, **attrs)
    params = ",".join(f'.{k}("{v}")' for k, v in a.items())
    tied = ",".join(f".{p}(g)" for p in EFB_PORTS_TIED)
    if name == "wb_in":
        # 19 shift-register stages -> one flop per WB input; csn is a pin.
        wb = ("WBCYCI", "WBSTBI", "WBWEI",
              *[f"WBADRI{i}" for i in range(7, -1, -1)],
              *[f"WBDATI{i}" for i in range(7, -1, -1)])
        conns = ",".join(f".{p}(s[{i}])" for i, p in enumerate(wb))
        return f"""module fuzz(input wire clk, input wire d, input wire csn, output wire out0);
 wire g=1'b0; wire [7:0] o; wire a;
 reg [18:0] s;
 always @(posedge clk) s <= {{s[17:0], d}};
 EFB #({params}) u0 (
  .WBCLKI(clk),.WBRSTI(g),{conns},
  {tied},.SPISCSN(csn),
  .WBDATO7(o[7]),.WBDATO6(o[6]),.WBDATO5(o[5]),.WBDATO4(o[4]),
  .WBDATO3(o[3]),.WBDATO2(o[2]),.WBDATO1(o[1]),.WBDATO0(o[0]),.WBACKO(a));
 reg r; always @(posedge clk) r<=a^(^o); assign out0=r;
endmodule
"""
    wb_g = ",".join(f".{p}(g)" for p in
                    ["WBRSTI", "WBCYCI", "WBSTBI", "WBWEI"]
                    + [f"WBADRI{i}" for i in range(8)]
                    + [f"WBDATI{i}" for i in range(8)])
    return f"""module fuzz(input wire clk, output wire out0);
 wire g=1'b0; wire [7:0] o; wire a;
 EFB #({params}) u0 (
  .WBCLKI(clk),{wb_g},{tied},.SPISCSN(g),
  .WBDATO7(o[7]),.WBDATO6(o[6]),.WBDATO5(o[5]),.WBDATO4(o[4]),
  .WBDATO3(o[3]),.WBDATO2(o[2]),.WBDATO1(o[1]),.WBDATO0(o[0]),.WBACKO(a));
 reg r; always @(posedge clk) r<=a^(^o); assign out0=r;
endmodule
"""


def lpf(name):
    pins = [("clk", 88), ("out0", 84)]
    if name == "wb_in":
        pins += [("d", 86), ("csn", 85)]
    body = "BLOCK RESETPATHS;\nBLOCK ASYNCPATHS;\n\n"
    for p, s in pins:
        body += f'LOCATE COMP "{p}" SITE "{s}";\nIOBUF PORT "{p}" IO_TYPE=LVCMOS33;\n\n'
    if VARIANTS.get(name, {}).get("SPI_MODE") == "MASTER":
        body += "SYSCONFIG MASTER_SPI_PORT=ENABLE;\n"
    return body + 'FREQUENCY PORT "clk" 100.000000 MHz;\n'


LDF = """<?xml version="1.0" encoding="UTF-8"?>
<BaliProject version="3.2" title="fuzz" device="LCMXO2-1200HC-5TG100C" default_implementation="impl1">
    <Options/>
    <Implementation title="impl1" dir="impl1" description="impl1" synthesis="lse" default_strategy="Strategy1">
        <Options/>
        <Source name="fuzz.v" type="Verilog" type_short="Verilog"><Options/></Source>
        <Source name="fuzz.lpf" type="Logic Preference" type_short="LPF"><Options/></Source>
    </Implementation>
    <Strategy name="Strategy1" file="%s"/>
</BaliProject>
"""
TCL = ('prj_project open "[file normalize [file join [file dirname [info script]] fuzz.ldf]]"\n'
       "prj_run PAR    -impl impl1\n"
       "prj_run Export -impl impl1 -task Bitgen\n"
       "prj_project close\n")


def setup_logging():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("efb_oracle")
    if not log.handlers:
        log.setLevel(logging.INFO)
        f = logging.Formatter("%(asctime)s %(message)s")
        for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(LOG)):
            h.setFormatter(f)
            log.addHandler(h)
    return log


def write_target(name):
    d = WORK / name
    d.mkdir(parents=True, exist_ok=True)
    attrs = VARIANTS[name]
    (d / "fuzz.v").write_text(verilog(name, attrs))
    (d / "fuzz.lpf").write_text(lpf(name))
    (d / "fuzz.ldf").write_text(LDF % STY)
    (d / "run.tcl").write_text(TCL)
    return d


def diamond_env():
    root = toolchain.diamond_root()
    env = dict(os.environ)
    env["LM_LICENSE_FILE"] = os.environ.get(
        "LM_LICENSE_FILE", os.path.join(root, "license", "license.dat"))
    return os.path.join(root, "bin", "lin64", "diamondc"), env


def run_diamond(d, log):
    """diamondc run.tcl in d.  Returns (ok, elapsed_s, detail)."""
    import time
    exe, env = diamond_env()
    dlog = d / "diamond.log"
    t0 = time.monotonic()
    with open(dlog, "w") as fh:
        p = subprocess.Popen([exe, "run.tcl"], cwd=str(d), env=env,
                             stdout=fh, stderr=subprocess.STDOUT)
        last_size, last_change = -1, t0
        while p.poll() is None:
            threading.Event().wait(POLL_S)
            now = time.monotonic()
            size = dlog.stat().st_size
            if size != last_size:
                last_size, last_change = size, now
            if now - last_change > STALL_S or now - t0 > OVERALL_S:
                p.kill()
                p.wait()
                tail = dlog.read_text(errors="replace").strip().splitlines()[-1:]
                why = "stall" if now - last_change > STALL_S else "overall limit"
                return False, now - t0, f"killed ({why}); last line: {tail}"
    el = time.monotonic() - t0
    bit = d / "impl1" / "fuzz_impl1.bit"
    if p.returncode != 0 or not bit.exists():
        errs = [ln for ln in dlog.read_text(errors="replace").splitlines()
                if re.search(r"error|ERROR", ln)][:4]
        return False, el, f"rc={p.returncode} errors={errs}"
    return True, el, "ok"


def efb_payloads(bit):
    import native_config
    text, _pb, _b = native_config.config_from_file(
        str(bit), device=DEVICE, db_root=toolchain.trellis_dbroot())
    blocks = {}
    for m in re.finditer(r"\.efb_block sel 0x([0-9a-f]+) flags 0x[0-9a-f]+ len (\d+)\ndata: ([0-9a-f ]+)",
                         text):
        blocks[int(m.group(1), 16)] = m.group(3).split()
    return text, blocks


def cmd_build(args, log):
    results_p = WORK / "results.json"
    results = json.loads(results_p.read_text()) if results_p.exists() else {}
    for name in (args.only or VARIANTS):
        d = write_target(name)
        if not args.force and (d / "impl1" / "fuzz_impl1.bit").exists() and name in results:
            log.info("%s: already built", name)
            continue
        heavy_guard.wait_available(log, f"diamond {name}")
        with heavy_guard.heavy_lock(f"efb_oracle {name}", log):
            ok, el, detail = run_diamond(d, log)
        log.info("build %s: ok=%s took %.1fs %s", name, ok, el, detail)
        rec = {"ok": ok, "seconds": round(el, 1), "detail": detail}
        if ok:
            text, blocks = efb_payloads(d / "impl1" / "fuzz_impl1.bit")
            (d / "decoded.config").write_text(text)
            rec["efb_blocks"] = {hex(k): v for k, v in blocks.items()}
            rec["efb_enable"] = "EFB.ENABLE ENABLED" in text
            log.info("  payload %s", rec["efb_blocks"])
        results[name] = rec
        results_p.write_text(json.dumps(results, indent=1, sort_keys=True))
    return 0


def cmd_report(args, log):
    results = json.loads((WORK / "results.json").read_text())
    base = results.get("spi_default", {}).get("efb_blocks", {}).get("0x54")
    log.info("base payload (spi_default): %s", base)
    for name, rec in sorted(results.items()):
        if not rec["ok"]:
            log.info("%-16s BUILD FAILED  %s", name, rec["detail"][:160])
            continue
        p = rec["efb_blocks"].get("0x54")
        if base and p:
            diff = [(i, base[i], p[i]) for i in range(len(p)) if p[i] != base[i]]
        else:
            diff = None
        log.info("%-16s payload %s  vs base: %s", name, p, diff)
    return 0


def lifted_inputs(log):
    """Lift wb_in's decoded config into a scratch DB; return {oracle pin: driver}.

    driver = ("ff", site, regidx) | ("pad",) | ("none",), from the lifted netlist.
    """
    from sqlalchemy import text
    dbp = WORK / "efbin.db"
    if dbp.exists():
        dbp.unlink()      # derived artifact: rebuild, never migrate
    env = dict(os.environ, PLURIBUS_SQLITE_PATH=str(dbp))
    cfg = WORK / "wb_in" / "decoded.config"
    pins = WORK / "pins.tsv"
    iodb = json.loads((REPO / "device-db/MachXO2/LCMXO2-1200/iodb.json").read_text())
    pk = iodb["packages"]["TQFP100"]
    rows = "".join(f"{s}\t{pk[s]['row']}\t{pk[s]['col']}\t{pk[s]['pio']}\t{d}\t{lbl}\tefb oracle\t10\t\t\t\t\t\t\n"
                   for s, d, lbl in (("88", "in", "clk"), ("86", "in", "d"),
                                     ("85", "in", "csn"), ("84", "out", "out0")))
    pins.write_text("# device:   LCMXO2-1200\n# package:  TQFP100\n"
                    "# pin row col pio dir label function conf ref chip_pin chip_sig net_in net_out note\n" + rows)
    iom = Path(str(cfg) + ".iomap.tsv")
    if iom.exists():
        iom.unlink()      # fpga_iomap refuses to overwrite
    subprocess.run(["python3.15t", "scripts/fpga_iomap.py", str(cfg)],
                   cwd=str(REPO), env=dict(env, TRELLIS_PACKAGE="TQFP100"), capture_output=True, text=True)
    r = subprocess.run(["python3.15t", "load.py", "--label", "EFBIN", "--config", str(cfg),
                        "--pins", str(pins),
                        "--device", DEVICE, "--package", "TQFP100", "--fuzz"],
                       cwd=str(REPO), env=env, capture_output=True, text=True)
    (WORK / "load.log").write_text(r.stdout + r.stderr)
    if r.returncode != 0:
        raise SystemExit(f"load failed rc={r.returncode}; see {WORK/'load.log'}")
    os.environ["PLURIBUS_SQLITE_PATH"] = str(dbp)
    import db
    out = {}
    with db.engine().connect() as c:
        b = c.execute(text("select id from bitstreams where label='EFBIN'")).scalar()
        for port, net, d in c.execute(text(
                "select port_name, net, direction from efb_ports where bitstream=:b"), {"b": b}):
            if d != "in":
                continue
            ff = c.execute(text("select cell from ffs where bitstream=:b and q=:n"),
                           {"b": b, "n": net}).fetchall()
            pad = c.execute(text("select pin from pad_map where bitstream=:b and net_in=:n"),
                            {"b": b, "n": net}).fetchall()
            if pad:
                out[port[1:]] = ("pad",)
                continue
            m = re.fullmatch(r"ff_r(\d+)c(\d+)_([A-D])(\d)", ff[0][0]) if ff else None
            out[port[1:]] = (("ff", f"R{m.group(1)}C{m.group(2)}{m.group(3)}", int(m.group(4)))
                             if m else ("none",) if not ff else ("ff?", ff[0][0]))
    return out


def cmd_compare(args, log):
    oj = json.loads((WORK / "oracle" / "wb_in" / "oracle.json").read_text())
    sites = {c["name"]: c["site"] for c in oj["comps"] if c["type"] == "SLICE"}
    want = {}
    for n in oj["nets"]:
        u0 = [p["pin"] for p in n["pins"] if p["comp"] == "u0"]
        for pin in u0:
            drv = [p for p in n["pins"] if p["comp"] != "u0"]
            q = [p for p in drv if p["comp"] in sites and p["pin"] in ("Q0", "Q1")]
            if q:
                want[pin] = ("ff", sites[q[0]["comp"]], int(q[0]["pin"][1]))
            elif any(p["pin"] == "PADDI" for p in drv):
                want[pin] = ("pad",)
            elif any(p["pin"] == "CLK" for p in drv):
                want[pin] = ("clk",)
    got = lifted_inputs(log)
    ins = sorted(k for k in want if k not in ("WBDATO0",))
    ins = [k for k in ins if k in got or re.match(r"WB(ADR|DAT)I|WB(CYC|STB|WE|CLK)I|SPISCSN", k)]
    # Diamond slice sites are one column right of the tile coordinate the lifter uses;
    # require that offset to be the SAME for every flop, else it is not an offset.
    offs = {int(re.match(r"R\d+C(\d+)", want[k][1]).group(1))
            - int(re.match(r"R\d+C(\d+)", got[k][1]).group(1))
            for k in ins if want[k][0] == "ff" and got.get(k, ("",))[0] == "ff"}
    log.info("slice-site column offset oracle - lifter over all flop-driven pins: %s", sorted(offs))
    off = offs.pop() if len(offs) == 1 else 0

    def norm(w):
        if w[0] != "ff":
            return w
        m = re.match(r"R(\d+)C(\d+)(\w)", w[1])
        return ("ff", f"R{m.group(1)}C{int(m.group(2)) - off}{m.group(3)}", w[2])
    ok = miss = wrong = 0
    for k in ins:
        w, g = norm(want[k]), got.get(k)
        if g == w:
            ok += 1
            log.info("MATCH   %-9s %s", k, w)
        elif g is None:
            miss += 1
            log.info("MISSING %-9s oracle %s, lifter has no port", k, w)
        else:
            wrong += 1
            log.info("WRONG   %-9s oracle %s lifter %s", k, w, g)
    extra = sorted(set(got) - set(ins))
    log.info("EFB input pins: matched %d / (matched %d + missing %d + wrong %d + extra %d) ; extra=%s",
             ok, ok, miss, wrong, len(extra), extra)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--only", nargs="*")
    b.add_argument("--force", action="store_true")
    sub.add_parser("report")
    sub.add_parser("compare")
    args = ap.parse_args()
    log = setup_logging()
    WORK.mkdir(parents=True, exist_ok=True)
    return {"build": cmd_build, "report": cmd_report, "compare": cmd_compare}[args.cmd](args, log)


if __name__ == "__main__":
    sys.exit(main())
