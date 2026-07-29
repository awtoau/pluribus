#!/usr/bin/env python3.15t
"""Run the ECP5 decoder + lifter over the third-party corpus.

THREE DISTINCT CLAIMS, REPORTED SEPARATELY
------------------------------------------
It is easy to conflate these, and conflating them is how a decoder gets
believed more than it deserves.  This script keeps them apart:

  1. DECODED     — native_bitstream/native_config parsed the file to a
                   `.config` without raising, with the CRC verified and every
                   frame consumed.
  2. ORACLE      — that `.config` is line-identical to `ecpunpack`'s.  This is
                   the strongest oracle available when there is no source
                   netlist, because ecpunpack works on any ECP5 bitstream and
                   was written by someone else.
  3. LIFTED      — the lifter turned the `.config` into a netlist that passes
                   structural consistency checks.  Without source we cannot
                   check EXACTNESS, only self-consistency, so this is the
                   weakest of the three and is labelled as such.

DEVICE AUTO-DETECTION
---------------------
A third-party `.bit` arrives with no device label — the filename lies as often
as not.  But the bitstream itself carries a VERIFY_ID record with the IDCODE,
and devices.json maps IDCODE to part.  We decode the IDCODE FIRST, with a
device-independent header scan, then pick geometry from it.  Trusting a
filename here would mean decoding an 85F as a 12F, which does not fail loudly:
it produces a plausible, wrong fabric.

CONSISTENCY CHECKS (claim 3)
----------------------------
Applied to the recovered netlist:
  * float_in     — LUT/FF inputs that resolved to no net AND no constant.
  * undriven     — nets with loads but no driver.  Some are expected (pads,
                   and the known clock-global gap); reported, not asserted.
  * no_load      — nets with a driver and no load.
  * lut_init     — INIT strings that are not 16 binary characters.
  * ff_clk_const — flip-flops whose clock resolved to a constant.  This is the
                   fingerprint of the known clock-global gap, so its RATE is
                   the interesting number.
  * census       — cell counts vs the `.config` tile census.  A LUT in the
                   config that produced no cell is a lifter drop.

Usage:
    python3.15t scripts/ecp5_corpus_test.py [--workers N] [--only SUBSTR]

Logs to ./tmp/logs/ecp5_corpus_test.log; results JSON to tmp/ecp5_corpus_results.json.
"""
import argparse
import concurrent.futures
import difflib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

DBROOT = os.environ.get("TRELLIS_DBROOT",
                        "/home/dan/opt/oss-cad-suite/share/trellis/database")
ECPUNPACK = "/home/dan/opt/oss-cad-suite/bin/ecpunpack"
MANIFEST = os.path.join(REPO, "corpus", "manifest.json")
OUTDIR = os.path.join(REPO, "tmp", "corpus-decode")

_lock = threading.Lock()


def setup_logging(name):
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(os.path.join(REPO, "tmp", "logs",
                                               f"{name}.log"))):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


# ---------------------------------------------------------------------------
# device identification
# ---------------------------------------------------------------------------

def idcode_table(db_root=DBROOT):
    """IDCODE -> [device names].  Several parts share an IDCODE only across
    families; within ECP5 they are unique, but we keep the list so a collision
    is visible rather than silently resolved."""
    dj = json.load(open(os.path.join(db_root, "devices.json")))
    tbl = {}
    for family, fi in dj["families"].items():
        for dev, dd in fi["devices"].items():
            idc = dd.get("idcode")
            if idc is None:
                continue
            k = int(idc, 16) if isinstance(idc, str) else int(idc)
            tbl.setdefault(k, []).append((family, dev))
    return tbl


def materialise(path):
    """Return a path to the raw bitstream, decompressing if needed.

    Diamond writes a gzip-compressed `.bit` by default, and several projects
    ship that form.  Both our decoder and ecpunpack want the raw stream, so
    decompress once into tmp/ and point everything at that — otherwise a
    perfectly good bitstream is scored as a decode failure for a reason that
    has nothing to do with the decoder.
    """
    with open(path, "rb") as fh:
        magic = fh.read(2)
    if magic != b"\x1f\x8b":
        return path, False
    import gzip
    os.makedirs(os.path.join(REPO, "tmp", "corpus-gunzip"), exist_ok=True)
    out = os.path.join(REPO, "tmp", "corpus-gunzip",
                       os.path.basename(path) + ".raw")
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(path):
        with gzip.open(path, "rb") as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return out, True


def scan_idcode(path):
    """Read the VERIFY_ID record without knowing the geometry.

    The bitstream preamble (0xFF 0xFF 0xBD 0xB3 sync, then commands) is parsed
    identically regardless of device; only the FRAME section needs geometry.
    So we can pull the IDCODE out before committing to a part.  Returns
    (idcode, offset) or (None, None).
    """
    data = open(path, "rb").read()
    # Sync word.  Vendor .bit files carry an ASCII comment header first.
    sync = data.find(b"\xff\xff\xbd\xb3")
    if sync < 0:
        return None, None
    i = sync + 4
    # Walk commands until VERIFY_ID (0xE2).  Every command is 1 opcode + 3
    # operand bytes; VERIFY_ID is then followed by a 4-byte IDCODE.
    end = min(len(data) - 8, i + 4096)
    while i < end:
        cmd = data[i]
        if cmd == 0xE2:                       # VERIFY_ID
            idc = int.from_bytes(data[i + 4:i + 8], "big")
            return idc, i
        if cmd == 0xFF:                       # DUMMY padding
            i += 1
            continue
        i += 4
    return None, None


def identify(path, db_root=DBROOT):
    """(device, family, idcode, how) for a bitstream, or (None, ...) if unknown."""
    idc, _off = scan_idcode(path)
    if idc is None:
        return None, None, None, "no-sync-or-no-verify-id"
    tbl = idcode_table(db_root)
    hits = tbl.get(idc)
    if not hits:
        return None, None, idc, f"idcode 0x{idc:08x} not in devices.json"
    if len(hits) > 1:
        # Prefer ECP5 when an IDCODE is ambiguous across families.
        ecp5 = [h for h in hits if h[0] == "ECP5"]
        if ecp5:
            hits = ecp5
    family, dev = hits[0]
    return dev, family, idc, "idcode"


# ---------------------------------------------------------------------------
# claim 1 + 2: decode, and decode vs ecpunpack
# ---------------------------------------------------------------------------

def meaningful(lines):
    """Drop `.comment` — package metadata the reference takes from argv, not
    from the bitstream, so it is not recovered content."""
    return [ln.rstrip("\n") for ln in lines if not ln.startswith(".comment")]


def run_oracle(bitpath, out, device):
    """ecpunpack the file.  Returns (ok, note, lines)."""
    cmd = [ECPUNPACK, bitpath, out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        # ecpunpack needs --idcode for parts whose header it cannot place.
        r = subprocess.run(cmd + ["--idcode", device], capture_output=True,
                           text=True)
        if r.returncode != 0:
            return False, f"ecpunpack rc={r.returncode}: {r.stderr.strip()[-200:]}", None
    return True, "", meaningful(open(out).readlines())


# ---------------------------------------------------------------------------
# claim 3: lift, and check the netlist for self-consistency
# ---------------------------------------------------------------------------

CONST_RE = re.compile(r"^\d+'b[01]$")


def is_const(v):
    return v is not None and CONST_RE.match(str(v)) is not None


def census_config(text):
    """Count what the .config SAYS is there, independent of the lifter."""
    luts = set()
    slices = set()
    pios = set()
    arcs = 0
    tiles = 0
    cur = None
    for ln in text.splitlines():
        if ln.startswith(".tile"):
            tiles += 1
            m = re.match(r"^\.tile\s+(\S+)", ln)
            cur = m.group(1) if m else None
        elif ln.startswith("arc:"):
            arcs += 1
        elif ln.startswith("word:"):
            m = re.match(r"^word:\s+SLICE([A-D])\.K([01])\.INIT\s+([01]+)", ln)
            if m:
                # A LUT whose INIT is all-zero is a real cell in the config but
                # is constant-folded by the lifter; count both so the census
                # comparison does not report folding as a drop.
                luts.add((cur, m.group(1), m.group(2), m.group(3)))
        elif ln.startswith("enum:"):
            m = re.match(r"^enum:\s+SLICE([A-D])\.", ln)
            if m:
                slices.add((cur, m.group(1)))
            m = re.match(r"^enum:\s+PIO([A-D])\.", ln)
            if m:
                pios.add((cur, m.group(1)))
    nonzero = sum(1 for t in luts if set(t[3]) != {"0"})
    return dict(tiles=tiles, arcs=arcs, config_luts=len(luts),
                config_luts_nonzero=nonzero, config_slices=len(slices),
                config_pios=len(pios))


# Wide muxes reach the slice on dedicated F5x/FXx bel pins rather than as a
# named primitive, so the way to tell whether a design uses them is to count
# arcs INTO those pins.  `unknown:` lines naming F5/FX bits are the decoder
# saying it saw a set bit it has no model for — the same gap seen from the
# bitstream side rather than the netlist side.
WIDEMUX_SINK_RE = re.compile(r"^arc:\s+\S+\s+(F5[A-D]|FX[A-D])_SLICE\s*$")
WIDEMUX_UNKNOWN_RE = re.compile(r"^unknown:\s+(F5|FX)\w*")


def census_widemux(text):
    """How hard does this design lean on the wide-mux path the lifter skips?"""
    arcs_in = 0
    unknown_bits = 0
    for ln in text.splitlines():
        if WIDEMUX_SINK_RE.match(ln):
            arcs_in += 1
        elif WIDEMUX_UNKNOWN_RE.match(ln):
            unknown_bits += 1
    return dict(widemux_arcs=arcs_in, widemux_unknown_bits=unknown_bits)


def check_netlist(design, cens):
    """Structural self-consistency of a recovered netlist.

    Returns (metrics, findings).  Findings are DESCRIPTIVE — several of these
    conditions are expected consequences of the known modelling gaps, so this
    function reports rates rather than pronouncing pass/fail.  Interpretation
    is the caller's job.
    """
    m = {}
    findings = []

    luts, ffs = design.luts, design.ffs
    m["luts"] = len(luts)
    m["ffs"] = len(ffs)
    m["nets"] = len(design.all_nets)
    m["arcs"] = getattr(design, "n_arcs", None)
    m["skipped_arcs"] = getattr(design, "skipped_arcs", None)

    # --- LUT INIT sanity.  Anything not 16 binary chars is impossible for a
    # LUT4 and would mean the decode produced a malformed word.
    bad_init = [l for l in luts
                if not (isinstance(l.get("init"), str)
                        and len(l["init"]) == 16
                        and set(l["init"]) <= {"0", "1"})]
    m["lut_init_malformed"] = len(bad_init)
    if bad_init:
        findings.append(f"{len(bad_init)} LUT INIT not 16 binary chars "
                        f"(e.g. {bad_init[0].get('name')}="
                        f"{bad_init[0].get('init')!r})")

    # --- floating inputs.  A LUT input that is neither a net nor a constant
    # is an under-connection: the lifter could not resolve where it came from.
    float_lut = 0
    used_pin = 0
    for l in luts:
        for pin in "abcd":
            v = l.get(pin)
            if v is None:
                continue
            used_pin += 1
            if not is_const(v) and not str(v).startswith("n"):
                float_lut += 1
    m["lut_input_pins"] = used_pin
    m["lut_inputs_unresolved"] = float_lut

    # --- census: every LUT site that COMPUTES something should become a cell.
    #
    # Compare against the NONZERO-INIT site count, not the raw site count.  A
    # slice used only for its flip-flops still emits a `K0.INIT 000...0` word,
    # and the lifter constant-folds those to 1'b0 rather than emitting a dead
    # cell.  That folding is correct, so counting all sites reports it as a
    # drop — dm_multiclk looked like it lost 21 of 30 LUTs when in fact all 9
    # of its real LUTs were recovered and 21 empty ones were folded.
    #
    # A shortfall against the nonzero count IS a genuine lifter drop.  A
    # surplus is the DPRAM/RAMW read-port expansion, which is expected.
    cfg_nz = cens.get("config_luts_nonzero")
    if cfg_nz is not None:
        m["config_lut_sites"] = cens.get("config_luts")
        m["config_lut_sites_nonzero"] = cfg_nz
        live = [l for l in luts if set(str(l.get("init", "0"))) != {"0"}]
        m["lut_cells_nonzero"] = len(live)
        m["lut_sites_missing"] = max(0, cfg_nz - len(live))
        if m["lut_sites_missing"]:
            findings.append(f"{m['lut_sites_missing']} nonzero-INIT LUT sites "
                            f"in the .config produced no cell (lifter drop)")

    # --- which slice MODEs appear.  The lifter's known gaps are mode-specific
    # (CCU2 = carry path, DPRAM/RAMW = distributed RAM), so recording the mode
    # mix says WHICH gaps a given design actually exercises.
    modes = {}
    for l in luts:
        modes[l.get("mode") or "?"] = modes.get(l.get("mode") or "?", 0) + 1
    m["lut_modes"] = modes
    if modes.get("CCU2"):
        findings.append(f"{modes['CCU2']} LUTs in CCU2 mode — carry-chain gap "
                        f"exercised (FCI/FCO not modelled)")

    wm = cens.get("widemux_arcs") or 0
    if wm:
        findings.append(f"{wm} arcs into F5x/FXx wide-mux pins — wide-mux gap "
                        f"exercised (mux cell not emitted)")

    # --- flip-flop clocks.  A constant clock is the fingerprint of the known
    # clock-global gap (prjtrellis parks non-TAP/SPINE globals at (0,0), so the
    # lifter drops them rather than fusing every register onto one net).  The
    # RATE is the number that matters: it says how hard a real design hits it.
    clk_const = sum(1 for f in ffs if is_const(f.get("clk")))
    m["ff_clk_const"] = clk_const
    m["ff_clk_const_pct"] = round(100.0 * clk_const / len(ffs), 1) if ffs else 0.0
    if clk_const:
        findings.append(f"{clk_const}/{len(ffs)} FFs ({m['ff_clk_const_pct']}%) "
                        f"have a constant clock — clock-global gap")

    d_const = sum(1 for f in ffs if is_const(f.get("d")))
    m["ff_d_const"] = d_const

    # --- net degree.  Build driver/load counts from the cells we recovered.
    drivers = {}
    loads = {}
    # Distributed RAM emits TWO cells for one physical output: the slice in
    # MODE=DPRAM and the synthetic `dpram_*` read port that models it.  They
    # legitimately share a net, so counting both as drivers reports every
    # DPRAM bit as a fused net.  Attribute the net to the DPRAM group once.
    dpram_nets = {l.get("z") for l in luts
                  if l.get("name", "").startswith("dpram_")}
    for l in luts:
        z = l.get("z")
        if z and str(z).startswith("n"):
            if z in dpram_nets and not l.get("name", "").startswith("dpram_"):
                pass          # the slice half of a DPRAM pair; not a 2nd driver
            else:
                drivers[z] = drivers.get(z, 0) + 1
        for pin in "abcd":
            v = l.get(pin)
            if v and str(v).startswith("n"):
                loads[v] = loads.get(v, 0) + 1
    for f in ffs:
        q = f.get("q")
        if q and str(q).startswith("n"):
            drivers[q] = drivers.get(q, 0) + 1
        for pin in ("d", "clk", "ce", "lsr"):
            v = f.get(pin)
            if v and str(v).startswith("n"):
                loads[v] = loads.get(v, 0) + 1

    m["nets_multi_driver"] = sum(1 for v in drivers.values() if v > 1)
    # A net with two drivers is the ONLY finding here that indicates a
    # MIS-connection rather than an under-connection: it means the union-find
    # fused two nets that should be separate.  That is the dangerous direction.
    if m["nets_multi_driver"]:
        findings.append(f"{m['nets_multi_driver']} nets have >1 driver — "
                        f"possible net FUSION (mis-connect, not under-connect)")

    undriven = [n for n in loads if n not in drivers]
    no_load = [n for n in drivers if n not in loads]
    m["nets_undriven"] = len(undriven)
    m["nets_no_load"] = len(no_load)

    return m, findings


# ---------------------------------------------------------------------------
# per-file pipeline
# ---------------------------------------------------------------------------

def test_one(rec, log, do_lift=True):
    path = os.path.join(REPO, rec["local"]) if "local" in rec else rec["path"]
    label = rec.get("label") or os.path.basename(path)
    out = dict(label=label, source=rec.get("url", "local"),
               project=rec.get("project"), license=rec.get("license"),
               bytes=rec.get("bytes") or (os.path.getsize(path)
                                          if os.path.exists(path) else None),
               sha256=rec.get("sha256"))

    if not os.path.exists(path):
        out["decode"] = "missing"
        return out

    path, was_gz = materialise(path)
    out["gzipped"] = was_gz

    # ---- identify the part from the bitstream, not the filename
    dev, family, idc, how = identify(path)
    out["idcode"] = f"0x{idc:08x}" if idc else None
    out["device"] = dev
    out["family"] = family
    out["identify"] = how
    if dev is None:
        out["decode"] = f"unidentified ({how})"
        with _lock:
            log.warning("%-46s UNIDENTIFIED  %s", label, how)
        return out
    if family != "ECP5":
        out["decode"] = f"not-ecp5 ({family})"
        with _lock:
            log.info("%-46s SKIP not ECP5 (%s %s)", label, family, dev)
        return out

    os.makedirs(OUTDIR, exist_ok=True)
    # Output paths must be unique PER FILE, not per label.  Two corpus entries
    # can share a basename (many projects ship `top.bit`), and when two workers
    # then write the same .config concurrently each reads a half-written file
    # and reports a spurious ORACLE-DIFF.  This produced exactly one such false
    # failure -- a 12641-line "difference" that vanished on a serial re-run --
    # so the label alone is not a safe key.  Disambiguate with the content hash.
    uniq = (rec.get("sha256") or "")[:12]
    if not uniq:
        import hashlib as _h
        uniq = _h.sha256(os.path.abspath(path).encode()).hexdigest()[:12]
    stem = f"{label}.{uniq}"
    native_p = os.path.join(OUTDIR, f"{stem}.native.config")
    oracle_p = os.path.join(OUTDIR, f"{stem}.oracle.config")

    # ---- CLAIM 1: does it decode at all?
    import native_config
    try:
        text, pb, _bram = native_config.config_from_file(
            path, device=dev, db_root=DBROOT)
    except Exception as e:                                        # noqa: BLE001
        out["decode"] = f"raised {type(e).__name__}: {e}"
        out["traceback"] = traceback.format_exc()[-1200:]
        with _lock:
            log.error("%-46s DECODE-FAIL  %s: %s", label, type(e).__name__, e)
        return out

    with open(native_p, "w") as fh:
        fh.write(text)
    out["decode"] = "ok"
    out["crc_verified"] = bool(pb.crc_verified)
    out["frames"] = f"{pb.frames_read}/{pb.num_frames}"
    out["frames_complete"] = pb.frames_read == pb.num_frames
    out.update(census_config(text))
    out.update(census_widemux(text))
    # `unknown:` lines are the decoder's own admission of an unmodelled set
    # bit.  Total count is a blunt but toolchain-independent measure of how
    # much of a third-party bitstream the tile database does not explain.
    out["unknown_lines"] = sum(1 for ln in text.splitlines()
                               if ln.startswith("unknown:"))

    # ---- CLAIM 2: identical to ecpunpack?
    ok, note, oracle_lines = run_oracle(path, oracle_p, dev)
    if not ok:
        out["oracle"] = f"unavailable: {note}"
    else:
        native_lines = meaningful(text.splitlines(keepends=True))
        if native_lines == oracle_lines:
            out["oracle"] = "identical"
        else:
            diff = list(difflib.unified_diff(oracle_lines, native_lines,
                                             "oracle", "native", lineterm="",
                                             n=0))
            out["oracle"] = "DIFFERS"
            out["oracle_diff_lines"] = len(diff)
            out["oracle_diff_sample"] = diff[:20]
            with _lock:
                log.error("%-46s ORACLE-DIFF  %d lines", label, len(diff))
                for d in diff[:12]:
                    log.error("      %s", d)

    # ---- CLAIM 3: lift to a netlist and check consistency
    if do_lift:
        try:
            from lifters.ecp5_lift import ECP5Lift
            lift = ECP5Lift(dev, dbroot=DBROOT)
            pc = lift.parse_config(native_p)
            design = lift.recover_netlist(pc)
            metrics, findings = check_netlist(design, out)
            out["lift"] = "ok"
            out["metrics"] = metrics
            out["findings"] = findings
        except Exception as e:                                    # noqa: BLE001
            out["lift"] = f"raised {type(e).__name__}: {e}"
            out["lift_traceback"] = traceback.format_exc()[-1500:]
            with _lock:
                log.error("%-46s LIFT-FAIL  %s: %s", label, type(e).__name__, e)
    else:
        out["lift"] = "skipped"

    with _lock:
        log.info("%-46s %-10s dev=%-13s decode=%s oracle=%-10s lift=%s",
                 label[:46], "", dev, out["decode"], out["oracle"],
                 out.get("lift"))
        if out.get("findings"):
            for f in out["findings"]:
                log.info("      · %s", f)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", default=MANIFEST)
    # Lifting is the memory-hungry stage, not decoding: an LFE5U-85F lift holds
    # the full routing graph plus the union-find, and eight concurrent 85F
    # lifts were measured at ~27 GB RSS combined.  Decode-only runs are cheap
    # and can use many more workers, so --no-lift pairs well with a high count.
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel workers (memory scales with this on 85F "
                         "lifts; 4 needs roughly 16 GB, 8 roughly 30 GB)")
    ap.add_argument("--only", help="substring filter on label")
    ap.add_argument("--no-lift", action="store_true")
    ap.add_argument("--extra", action="append", default=[],
                    help="additional bitstream path to test (repeatable)")
    ap.add_argument("--scan", action="append", default=[],
                    help="directory to search recursively for .bit files")
    ap.add_argument("--out", default=os.path.join(REPO, "tmp",
                                                  "ecp5_corpus_results.json"))
    ap.add_argument("--resume", metavar="JSON",
                    help="merge in a previous results file and skip entries "
                         "it already covers.  Lifting an 85F design is "
                         "expensive, so a run interrupted by memory pressure "
                         "should not repeat the work it already finished.")
    args = ap.parse_args()
    log = setup_logging("ecp5_corpus_test")

    entries = []
    if os.path.exists(args.manifest):
        entries = json.load(open(args.manifest))["entries"]
    extra = list(args.extra)
    for d in args.scan:
        for root, _dirs, files in os.walk(d):
            extra.extend(os.path.join(root, f) for f in sorted(files)
                         if f.endswith(".bit"))
    for p in sorted(set(extra)):
        # Label by the design directory, not the basename: Diamond names every
        # output <project>_impl1.bit, so basenames alone collide in the report.
        rel = os.path.relpath(p, REPO)
        label = os.path.basename(p)
        parts = rel.split(os.sep)
        if len(parts) >= 3 and parts[-2] == "impl1":
            label = parts[-3]
        entries.append({"local": rel, "url": "local (our Diamond build)",
                        "project": "pluribus diamond build", "license": "n/a",
                        "label": label})
    if args.only:
        entries = [e for e in entries
                   if args.only in (e.get("label") or e.get("local", ""))]
    done = {}
    if args.resume and os.path.exists(args.resume):
        for r in json.load(open(args.resume)):
            # Only carry forward entries that actually completed the stage we
            # are about to run; a partial record would silently understate the
            # work still outstanding.
            if r.get("decode") == "ok" and (args.no_lift
                                            or r.get("lift") not in (None, "skipped")):
                done[r.get("sha256") or r.get("label")] = r
        entries = [e for e in entries
                   if (e.get("sha256") or e.get("label")) not in done]
        log.info("resume: %d already complete, %d to do", len(done), len(entries))

    log.info("testing %d bitstreams, %d workers", len(entries), args.workers)

    results = list(done.values())
    def flush():
        """Write results after every completion.

        An 85F lift is minutes of work, and a run that only writes at the end
        loses all of it to one interruption -- which is exactly what happened
        when eight concurrent 85F lifts exhausted memory and the run had to be
        killed at 104/228 with nothing on disk.  Writing as we go makes
        --resume actually usable.
        """
        tmp = args.out + ".partial"
        with open(tmp, "w") as fh:
            json.dump(sorted(results, key=lambda r: r.get("label", "")), fh,
                      indent=2, sort_keys=True)
        os.replace(tmp, args.out)

    with concurrent.futures.ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(test_one, e, log, not args.no_lift) for e in entries]
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())
            with _lock:
                flush()

    results.sort(key=lambda r: r["label"])
    flush()

    # ---- the three claims, counted separately
    dec = sum(1 for r in results if r.get("decode") == "ok")
    orc = sum(1 for r in results if r.get("oracle") == "identical")
    orc_d = sum(1 for r in results if r.get("oracle") == "DIFFERS")
    lif = sum(1 for r in results if r.get("lift") == "ok")
    fused = sum(1 for r in results
                if r.get("metrics", {}).get("nets_multi_driver"))
    log.info("---- summary over %d files ----", len(results))
    log.info("  decoded                      : %d", dec)
    log.info("  identical to ecpunpack       : %d", orc)
    log.info("  DIFFER from ecpunpack        : %d", orc_d)
    log.info("  lifted to a netlist          : %d", lif)
    log.info("  netlists with a fused net    : %d", fused)
    devs = {}
    for r in results:
        if r.get("device"):
            devs[r["device"]] = devs.get(r["device"], 0) + 1
    log.info("  device spread                : %s", dict(sorted(devs.items())))
    log.info("results -> %s", args.out)
    return 1 if orc_d else 0


if __name__ == "__main__":
    sys.exit(main())
