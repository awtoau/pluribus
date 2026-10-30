#!/usr/bin/env python3.15t
"""IO single-setting pair builds on EP4CGX150: which CFF bits does each IO setting change?  Black box: quartus_map/fit/asm/cpf only (#168).

Method (docs/recovery-process.md, exact labels = pair diffs, one feature per diff):
  per sampled pin site, one tiny design per direction kind (in / out / tri / bidir / registered in, out, OE); a pair = base build and the
  same build plus ONE QSF assignment (standard, drive, slew, pull-up, bus-hold, OCT, open-drain, registered in/out/OE).  Direction pairs
  differ in the Verilog of the pin (direction cannot be set by an assignment).  Pin-location pairs = the `out` base at two sites.
  Diffs: sof tag 21 (CFF bit index = sof bit index), tag 18 (option register), tag 17 (CRAM, counted); rbf frames 0..36 cross-check via Cff.
Sampling (recovery-process.md): per IO bank the two ends (farthest pair) + SAMPLE_CENTRE seeded interior sites.
Aux pins (clock, data, enable, observe) sit in a fixed other bank and never change between base and spec.

  python3.15t scripts/cycloneiv_clean_io_pairs.py pins                 # pin -> site, bank table from the corpus postfit.vo / build.pin
  python3.15t scripts/cycloneiv_clean_io_pairs.py build [--jobs 12] [--banks 3,4] [--limit-sites N] [--kinds out,in]
  python3.15t scripts/cycloneiv_clean_io_pairs.py analyse              # -> databases/cycloneiv/io_pairs.json, tmp/.../io_pairs.md
Log: tmp/logs/cycloneiv_clean_io_pairs.log
"""
import argparse
import collections
import gzip
import json
import logging
import os
import re
import shutil
import struct
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from lifters.cycloneiv_clean import cycloneiv_io as IO  # noqa: E402
from lifters.cycloneiv_clean import plane as P  # noqa: E402

OUT = os.path.join(REPO, "tmp", "cycloneiv_clean", "io_pairs")
CORPUS = os.path.join(REPO, "corpus", "cycloneiv")
PAIRS_DB = os.path.join(REPO, "databases", "cycloneiv", "io_pairs.json")
DEVICE = "EP4CGX150DF31C7"
SEED = 168
SAMPLE_CENTRE = 2              # interior sites per bank beside the two ends (recovery-process.md: ~10 %, at least 3 tiles per area)
AUX_BANKS = (3, 7)             # aux pins live in the first of these that is not the test bank
AUX_NAMES = ("a", "c", "e", "y")
PIN_DESIGNS = 700              # corpus designs scanned for the pin -> site table
PERIPHERY_BYTES = P.RBF_HEADER + P.RBF_PRE_FRAMES * P.RBF_FRAME_BYTES
CFF_BITS = 31060               # source: ASMDB_DIE m_num_cff_bits (cycloneiv_io.die_head)
# Quartus step backstops = 3x worst of the 50-build pilot (12 parallel jobs, load ~45): map 20.8 s, fit 24.9 s, asm 9.9 s, cpf 2.6 s.
# fz.run also kills a step silent (no output, no CPU) for 60 s; on expiry it logs step, elapsed and loadavg and the build is recorded FAILED.
LIMITS = {"quartus_map": 63, "quartus_fit": 75, "quartus_asm": 30, "quartus_cpf": 8}
JOB_GB_NAME = "quartus_chain_cyc4"
log = logging.getLogger("io_pairs")

# ---- design kinds: pin `p`, aux pins a (data) c (clock) e (enable) y (observe) used identically in every kind ----
KINDS = {
    "in": "input p, input a, input c, input e, output y",
    "out": "output p, input a, input c, input e, output y",
    "tri": "inout p, input a, input c, input e, output y",
    "bidir": "inout p, input a, input c, input e, output y",
    "regout": "output p, input a, input c, input e, output y",
    "regoe": "inout p, input a, input c, input e, output y",
    "regin": "input p, input a, input c, input e, output y",
}
BODY = {
    "in": "assign y = p ^ a ^ c ^ e;",
    "out": "assign p = a & c; assign y = a ^ c ^ e;",
    "tri": "assign p = e ? (a & c) : 1'bz; assign y = a ^ c ^ e;",
    "bidir": "assign p = e ? (a & c) : 1'bz; assign y = p ^ a ^ c ^ e;",
    "regout": "reg r; always @(posedge c) r <= a ^ e; assign p = r; assign y = a ^ c ^ e;",
    "regoe": "reg r; always @(posedge c) r <= e; assign p = r ? a : 1'bz; assign y = a ^ c ^ e;",
    "regin": "reg r; always @(posedge c) r <= p; assign y = r ^ a ^ e;",
}
QSF_KEY = {   # key -> QSF instance assignment name, quoted value?
    "STD": ("IO_STANDARD", True), "DRIVE": ("CURRENT_STRENGTH_NEW", True), "SLEW": ("SLEW_RATE", False),
    "PULLUP": ("WEAK_PULL_UP_RESISTOR", False), "BUSHOLD": ("ENABLE_BUS_HOLD_CIRCUITRY", False),
    "OCT": ("OUTPUT_TERMINATION", True), "OD": ("AUTO_OPEN_DRAIN_PINS", False),
    "FOR": ("FAST_OUTPUT_REGISTER", False), "FOE": ("FAST_OUTPUT_ENABLE_REGISTER", False), "FIR": ("FAST_INPUT_REGISTER", False),
}
STANDARDS = ["3.3-V LVTTL", "3.3-V LVCMOS", "3.0-V LVTTL", "3.0-V LVCMOS", "3.0-V PCI", "1.8 V", "1.5 V", "1.2 V",
             "SSTL-2 Class I", "SSTL-18 Class I", "1.8-V HSTL Class I", "1.5-V HSTL Class I"]
BASE_STD = "2.5 V"          # Cyclone IV default standard; named explicitly in every build
DRIVES = ["4MA", "8MA", "12MA", "16MA", "MAXIMUM CURRENT", "MINIMUM CURRENT"]


def tag(assigns):
    return "+".join(f"{k}={v}" for k, v in assigns).replace(" ", "_").replace('"', "") or "default"


def bid(kind, assigns):
    return f"{kind}.{tag(assigns)}"


def pair_list():
    """[(setting, value, base build, spec build)]; a build = (kind, ((KEY, value), ...)).  One extra assignment per spec."""
    out = []

    def add(setting, value, kind, base, extra):
        # every build names its standard (a drive / slew assignment alone is a fitter error: pin missing I/O standard)
        b = tuple(base) if any(k == "STD" for k, _ in base) else (("STD", BASE_STD),) + tuple(base)
        out.append((setting, value, (kind, b), (kind, tuple(x for x in b if x[0] != extra[0]) + (extra,))))
    for s in STANDARDS:
        add("standard", s, "out", [], ("STD", s))
    for d in DRIVES:
        add("drive", d, "out", [], ("DRIVE", d))
    for v in (0, 1, 2):
        add("slew", str(v), "out", [], ("SLEW", v))
    for k, name in (("PULLUP", "pull-up"), ("BUSHOLD", "bus-hold"), ("OD", "open-drain")):
        add(name, "ON", "out", [], (k, "ON"))
    for v in ("SERIES 50 OHM WITHOUT CALIBRATION", "SERIES 25 OHM WITHOUT CALIBRATION"):
        add("termination", v, "out", [], ("OCT", v))
    for s in ("3.3-V LVTTL", "1.8 V", "SSTL-2 Class I"):
        add("standard", s, "in", [], ("STD", s))
    for k, name in (("PULLUP", "pull-up"), ("BUSHOLD", "bus-hold")):
        add(name, "ON", "in", [], (k, "ON"))
    add("standard", "3.3-V LVTTL", "bidir", [], ("STD", "3.3-V LVTTL"))
    for d in ("4MA", "16MA"):
        add("drive", d, "bidir", [], ("DRIVE", d))
    add("slew", "0", "bidir", [], ("SLEW", 0))
    for k, name in (("PULLUP", "pull-up"), ("BUSHOLD", "bus-hold"), ("OD", "open-drain")):
        add(name, "ON", "bidir", [], (k, "ON"))
    add("open-drain", "ON", "tri", [], ("OD", "ON"))
    add("registered-output", "ON", "regout", [("FOR", "OFF")], ("FOR", "ON"))
    add("registered-oe", "ON", "regoe", [("FOE", "OFF")], ("FOE", "ON"))
    add("registered-input", "ON", "regin", [("FIR", "OFF")], ("FIR", "ON"))
    add("open-drain", "ON", "regoe", [("FOE", "ON")], ("OD", "ON"))
    # direction: Verilog differs, assignments identical (empty)
    for a, b in (("in", "out"), ("in", "tri"), ("in", "bidir"), ("out", "tri"), ("tri", "bidir")):
        out.append(("direction", f"{a}->{b}", (a, (("STD", BASE_STD),)), (b, (("STD", BASE_STD),))))
    return out


def builds_needed(pairs):
    seen = {}
    for _, _, b, s in pairs:
        seen[bid(*b)] = b
        seen[bid(*s)] = s
    return seen


# ---- pin / site table ----
def cmd_pins(a):
    import tomllib
    pat_loc = re.compile(r"// Location: (IO[IO]BUF)_X(\d+)_Y(\d+)_N(\d+)\ncycloneiv_io_[io]buf \\(\S+?)~(?:input|output)")
    pat_pin = re.compile(r"^// (\S+)\t=>  Location: PIN_(\w+),", re.M)
    sites, banks = {}, {}
    dirs = sorted(d for d in os.listdir(CORPUS) if d.startswith("gx") and os.path.exists(os.path.join(CORPUS, d, "postfit.vo")))
    n = 0
    for d in dirs:
        p = os.path.join(CORPUS, d)
        if tomllib.load(open(os.path.join(p, "design.toml"), "rb")).get("device") != DEVICE:
            continue
        n += 1
        text = open(os.path.join(p, "postfit.vo")).read()
        loc = {m[5]: (m[1], int(m[2]), int(m[3]), int(m[4])) for m in pat_loc.finditer(text)}
        for m in pat_pin.finditer(text):
            if m[1] in loc:
                sites.setdefault(m[2], set()).add(loc[m[1]])
        if not banks:
            for ln in open(os.path.join(p, "build.pin")):
                f = [x.strip() for x in ln.split(":")]
                if len(f) >= 7 and re.fullmatch(r"\d+", f[5] or "x"):
                    banks[f[1]] = int(f[5])
        if n >= PIN_DESIGNS:
            break
    out, bad = {}, []
    for pin, s in sites.items():
        xy = {(x, y) for _, x, y, _ in s}
        ns = {t: sorted({n for t2, _, _, n in s if t2 == t}) for t in ("IOIBUF", "IOOBUF")}
        if len(xy) != 1 or any(len(v) > 1 for v in ns.values()):
            bad.append(pin)       # one pin, two pad coordinates or two N per buffer type = parse error; dropped and reported
            continue
        x, y = next(iter(xy))
        out[pin] = dict(site=f"X{x}_Y{y}", x=x, y=y, n_in=(ns["IOIBUF"] or [None])[0], n_out=(ns["IOOBUF"] or [None])[0], bank=banks.get(pin))
    os.makedirs(OUT, exist_ok=True)
    json.dump(out, open(os.path.join(OUT, "pins.json"), "w"), indent=0, sort_keys=True)
    log.info("designs scanned %d, pins with a site %d (ambiguous dropped %d), banks %s", n, len(out), len(bad),
             sorted(collections.Counter(v["bank"] for v in out.values()).items(), key=str))


def load_pins():
    return json.load(open(os.path.join(OUT, "pins.json")))


def side(x, y, xmax, ymax):
    return "left" if x == 0 else "right" if x == xmax else "bottom" if y == 0 else "top" if y == ymax else "?"


def sample_sites():
    """{pin: dict(bank, side, role)}: per bank the two farthest-apart sites + SAMPLE_CENTRE seeded interior ones."""
    pins = load_pins()
    xmax = max(v["x"] for v in pins.values())
    ymax = max(v["y"] for v in pins.values())
    rng = np.random.default_rng(SEED)
    out, per = {}, collections.defaultdict(list)
    for pin, v in sorted(pins.items()):
        if v["bank"] is not None:
            per[v["bank"]].append(pin)
    for bank, ps in sorted(per.items()):
        xy = np.array([[pins[p]["x"], pins[p]["y"]] for p in ps], float)
        d = ((xy[:, None] - xy[None]) ** 2).sum(-1)
        i, j = np.unravel_index(np.argmax(d), d.shape)
        rest = [k for k in range(len(ps)) if k not in (i, j)]
        mid = sorted(rng.choice(rest, min(SAMPLE_CENTRE, len(rest)), replace=False).tolist()) if rest else []
        for k, role in [(i, "end"), (j, "end")] + [(m, "centre") for m in mid]:
            v = pins[ps[k]]
            out[ps[k]] = dict(bank=bank, role=role, side=side(v["x"], v["y"], xmax, ymax), **{q: v[q] for q in ("site", "x", "y", "n_in", "n_out")})
    return out


def aux_pins(bank, sample):
    """4 aux pins in AUX_BANKS' first bank != `bank`, never a sampled site."""
    pins = load_pins()
    ab = next(b for b in AUX_BANKS if b != bank)
    cand = sorted(p for p, v in pins.items() if v["bank"] == ab and p not in sample)
    return dict(zip(AUX_NAMES, cand[:4])), ab


# ---- one build ----
def verilog(kind):
    return f"module top({KINDS[kind]});\n  {BODY[kind]}\nendmodule\n"


def qsf_for(pin, aux, assigns):
    q = [f"set_location_assignment PIN_{pin} -to p"] + [f"set_location_assignment PIN_{v} -to {k}" for k, v in aux.items()]
    for k, v in assigns:
        name, quoted = QSF_KEY[k]
        q.append(f'set_instance_assignment -name {name} {f"{chr(34)}{v}{chr(34)}" if quoted else v} -to p')
    return q


def read_sof_sections(path):
    d = open(path, "rb").read()
    if d[:2] == b"\x1f\x8b":
        d = gzip.decompress(d)          # programmer sofs are gzip; quartus_asm output is raw
    p, sec = 12, {}
    while p < len(d):
        t, ln = struct.unpack_from("<HI", d, p)
        sec[t] = (p + 6, ln)
        p += 6 + ln
    return d, sec


def extract(sof, rbf, dest, pin_line):
    d, sec = read_sof_sections(sof)
    o, ln = sec[IO.SOF_TAG_CFF]
    cff = np.unpackbits(np.frombuffer(d[o + IO.SOF_SECTION_HEADER:o + ln], np.uint8), bitorder="little")[:CFF_BITS]
    o, ln = sec[IO.SOF_TAG_OPTION]
    opt = np.unpackbits(np.frombuffer(d[o:o + ln], np.uint8), bitorder="little")
    o, ln = sec[IO.SOF_TAG_CRAM]
    cram = np.frombuffer(d[o + IO.SOF_SECTION_HEADER:o + ln], np.uint8)
    peri = np.fromfile(rbf, np.uint8)[:PERIPHERY_BYTES]
    np.savez_compressed(dest, cff=cff, opt=opt, cram=cram, peri=peri, pin_line=np.array(pin_line))


def build_one(d, kind, pin, aux, assigns, limits, reserve="AS INPUT TRI-STATED"):
    import cycloneiv_fuzz as fz
    import heavy_guard
    import toolchain
    res = os.path.join(d, "result.npz")
    if os.path.exists(res):
        return "cached"
    shutil.rmtree(d, ignore_errors=True)
    q = os.path.join(d, "quartus")
    os.makedirs(os.path.join(d, "src"))
    os.makedirs(q)
    open(os.path.join(d, "src", "top.v"), "w").write(verilog(kind))
    qsf = ['set_global_assignment -name FAMILY "Cyclone IV GX"', f"set_global_assignment -name DEVICE {DEVICE}",
           "set_global_assignment -name TOP_LEVEL_ENTITY top", "set_global_assignment -name VERILOG_FILE ../src/top.v",
           f'set_global_assignment -name RESERVE_ALL_UNUSED_PINS_WEAK_PULLUP "{reserve}"',
           "set_global_assignment -name NUM_PARALLEL_PROCESSORS 1"] + qsf_for(pin, aux, assigns)
    open(os.path.join(q, "build.qsf"), "w").write("\n".join(qsf) + "\n")
    open(os.path.join(q, "build.qpf"), "w").write('QUARTUS_VERSION = "25.1"\nPROJECT_REVISION = "build"\n')
    qb = toolchain.quartus_bin()
    steps = [("quartus_map", [f"{qb}/quartus_map", "build"]), ("quartus_fit", [f"{qb}/quartus_fit", "build"]),
             ("quartus_asm", [f"{qb}/quartus_asm", "build"]),
             ("quartus_cpf", [f"{qb}/quartus_cpf", "-c", "-o", "bitstream_compression=off", "build.sof", "build.rbf"])]
    with heavy_guard.lease(heavy_guard.JOB_GB[JOB_GB_NAME], "io_pairs_build", log):
        for step, cmd in steps:
            if not fz.run(step, cmd, Path(q), Path(d) / "logs", limits):
                # the refusal text (fit error) is kept in logs/; the build is recorded failed, not retried
                shutil.rmtree(q, ignore_errors=True)
                open(os.path.join(d, "FAILED"), "w").write(step)
                return f"FAILED {step}"
    pl = ""
    for ln in open(os.path.join(q, "build.pin")):
        if re.match(r"p\s*:", ln):
            pl = re.sub(r"\s+", " ", ln.strip())
    extract(os.path.join(q, "build.sof"), os.path.join(q, "build.rbf"), res, pl)
    shutil.rmtree(q, ignore_errors=True)
    return "ok"


def cmd_build(a):
    sample = sample_sites()
    banks = {int(b) for b in a.banks.split(",")} if a.banks else None
    sel = [(p, v) for p, v in sample.items() if banks is None or v["bank"] in banks]
    if a.limit_sites:
        sel = sel[:a.limit_sites]
    pairs = pair_list()
    allb = builds_needed(pairs)
    if a.kinds:
        ks = set(a.kinds.split(","))
        allb = {k: b for k, b in allb.items() if b[0] in ks}
    jobs = []
    for pin, v in sel:
        aux, ab = aux_pins(v["bank"], sample)
        for name, (kind, assigns) in allb.items():
            jobs.append((os.path.join(OUT, "builds", f"{pin}_{v['site']}", name), kind, pin, aux, assigns))
    log.info("sites %d, builds per site %d, total %d, jobs %d, limits %s", len(sel), len(allb), len(jobs), a.jobs, LIMITS)
    done = collections.Counter()

    def run(j):
        try:
            r = build_one(j[0], j[1], j[2], j[3], j[4], LIMITS)
        except Exception as e:        # one broken build must not stop the batch; recorded failed
            r = f"FAILED exception {e!r}"
        done[r.split()[0]] += 1
        log.info("%s %s: %s  [%s]", os.path.basename(os.path.dirname(j[0])), os.path.basename(j[0]), r, dict(done))
        return r
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(run, jobs))
    log.info("done: %s", dict(collections.Counter(r.split()[0] + (" " + r.split()[1] if r.startswith("FAILED") else "") for r in res)))


# ---- analysis ----
def load_build(site_dir, name):
    f = os.path.join(site_dir, name, "result.npz")
    if not os.path.exists(f):
        return None
    z = np.load(f)
    return dict(cff=z["cff"], opt=z["opt"], cram=z["cram"], peri=z["peri"], pin=str(z["pin_line"]))


def diff(cff_tab, b, s):
    dc = np.nonzero(b["cff"] != s["cff"])[0]
    do = np.nonzero(b["opt"] != s["opt"])[0]
    nc = int(np.unpackbits(b["cram"] ^ s["cram"]).sum())
    vb, mb = cff_tab.read(b["peri"].tobytes())
    vs, ms = cff_tab.read(s["peri"].tobytes())
    rbf_dc = np.nonzero(vb != vs)[0]
    # sof diff must be a subset of the rbf diff; rbf-only bits (CRC / replica-group cells) are listed, not hidden
    return dict(cff=dc.tolist(), opt=do.tolist(), cram=nc, rbf_agree=bool(set(dc.tolist()) <= set(rbf_dc.tolist())),
                rbf_extra=sorted(set(rbf_dc.tolist()) - set(dc.tolist())), replica_bad=mb + ms)


def corpus_signatures(cff_tab, n=150):
    """Oracle (never an input): per used site, CFF bits set in >= 95 % of corpus designs using it and <= 3 % of the others (as test_io_cff)."""
    import glob
    loc = re.compile(r"// Location: (IO[OI]BUF)_X(\d+)_Y(\d+)_N(\d+)")
    cache = os.path.join(OUT, "corpus_sigs.json")
    if os.path.exists(cache):
        return json.load(open(cache))
    files = sorted(glob.glob(os.path.join(CORPUS, "gx150_sp_*", "bitstream.rbf")))[:n]
    if not files:
        return {}
    vals, sites = [], []
    for f in files:
        v, _ = cff_tab.read(f)
        vals.append(v)
        sites.append({(m[1], int(m[2]), int(m[3]), int(m[4])) for m in loc.finditer(open(os.path.join(os.path.dirname(f), "postfit.vo")).read())})
    V = np.stack(vals).astype(np.float32)
    use = collections.defaultdict(list)
    for i, s in enumerate(sites):
        for k in s:
            use[k].append(i)
    out = {}
    for (t, x, y, nn), pos in use.items():
        if len(pos) < 8:
            continue
        neg = np.setdiff1d(np.arange(len(files)), pos)
        if len(neg):
            out[f"{t}_X{x}_Y{y}_N{nn}"] = np.nonzero((V[pos].mean(0) >= 0.95) & (V[neg].mean(0) <= 0.03))[0].tolist()
    json.dump(out, open(cache, "w"))
    return out


def cmd_analyse(a):
    cff_tab = IO.Cff()
    sample = sample_sites()
    pairs = pair_list()
    oracle = corpus_signatures(cff_tab)
    rows, status = [], collections.Counter()
    for pin, v in sample.items():
        sd = os.path.join(OUT, "builds", f"{pin}_{v['site']}")
        if not os.path.isdir(sd):
            continue
        cache = {}

        def get(b):
            n = bid(*b)
            if n not in cache:
                cache[n] = load_build(sd, n)
                if cache[n] is None:
                    status["failed" if os.path.exists(os.path.join(sd, n, "FAILED")) else "absent"] += 1
            return cache[n]
        for setting, value, b, s in pairs:
            gb, gs = get(b), get(s)
            if gb is None or gs is None:
                rows.append(dict(pin=pin, setting=setting, value=value, status="no-build", base=bid(*b), spec=bid(*s)))
                continue
            rows.append(dict(pin=pin, setting=setting, value=value, status="ok", base=bid(*b), spec=bid(*s), pin_base=gb["pin"], pin_spec=gs["pin"],
                             **diff(cff_tab, gb, gs)))
    # location pairs: `out` base at site S vs at the first sampled site R (R2 = second): sig(S) = d(S,R) - sig(R)
    out_b = {}
    for pin, v in sample.items():
        f = load_build(os.path.join(OUT, "builds", f"{pin}_{v['site']}"), bid("out", (("STD", BASE_STD),)))
        if f is not None:
            out_b[pin] = f
    locs = {}
    groups = collections.defaultdict(list)
    for pin in out_b:
        groups[aux_pins(sample[pin]["bank"], sample)[1]].append(pin)     # same aux pins within a group, so d(S, R) is the sites only
    for ab, order in groups.items():
        if len(order) < 3:
            continue
        R = order[0]
        d = {p: set(np.nonzero(out_b[p]["cff"] != out_b[R]["cff"])[0].tolist()) for p in order[1:]}
        sigR = set.intersection(*d.values())
        locs.update({p: sorted(d[p] - sigR) for p in d})
        locs[R] = sorted(sigR)
    res = dict(sample=sample, rows=rows, location=locs, status=dict(status))
    # per-site oracle comparison for the location signatures
    cmp = []
    for pin, bits in locs.items():
        key = f"IOOBUF_{sample[pin]['site']}_N{sample[pin]['n_out']}"
        if key in oracle and oracle[key]:
            e, o = set(oracle[key]), set(bits)
            cmp.append(dict(pin=pin, matched=len(e & o), missing=len(e - o), extra=len(o - e), n_oracle=len(e), n_obs=len(o)))
        else:
            cmp.append(dict(pin=pin, matched=0, missing=0, extra=len(bits), n_oracle=0, n_obs=len(bits), no_oracle=True))
    res["location_vs_corpus"] = cmp
    os.makedirs(os.path.dirname(PAIRS_DB), exist_ok=True)
    json.dump(res, open(PAIRS_DB, "w"))
    md = render(res)
    open(os.path.join(OUT, "io_pairs.md"), "w").write(md)
    log.info("analysed %d rows; wrote %s and io_pairs.md; status %s", len(rows), PAIRS_DB, dict(status))


def anchored(r, locs):
    """CFF diff of a row as offsets from the site's location-signature anchor (None if the site has no signature)."""
    sig = locs.get(r["pin"])
    return [x - sig[0] for x in r["cff"]] if sig else None


def render(res):
    sample, rows, locs = res["sample"], res["rows"], res["location"]
    ok = [r for r in rows if r["status"] == "ok"]
    L = []
    outcap = [p for p in sample if p in locs]
    L.append(f"- sampled sites {len(sample)} (per bank: 2 ends + {SAMPLE_CENTRE} seeded interior), output-capable {len(outcap)}, "
             f"input-only {len(sample) - len(outcap)} (fitter refuses every output / bidir build there)")
    L.append(f"- pair rows: {len(ok)} built, {len(rows) - len(ok)} refused or absent; sof-vs-rbf: every sof CFF diff bit also in the rbf diff "
             f"in {sum(r['rbf_agree'] for r in ok)} / {len(ok)} rows")
    L.append("")
    L.append("| setting | value | base kind | sites built / tried | CFF bits per site | sites with the modal pattern | option bits | CRAM cells (min..max) |")
    L.append("|---|---|---|---|---|---|---|---|")
    by = collections.defaultdict(list)
    tried = collections.Counter()
    for r in rows:
        k = (r["setting"], r["value"], r["base"].split(".")[0])
        tried[k] += 1
        if r["status"] == "ok":
            by[k].append(r)
    pats_out = {}
    for k in sorted(tried, key=lambda k: (k[0], k[2], k[1])):
        rs = by.get(k, [])
        if not rs:
            L.append(f"| {k[0]} | {k[1]} | {k[2]} | 0 / {tried[k]} | - | - | - | - |")
            continue
        n = sorted({len(r["cff"]) for r in rs})
        ap = [tuple(a_) for r in rs if (a_ := anchored(r, locs)) is not None]
        pat, cnt = collections.Counter(ap).most_common(1)[0] if ap else ((), 0)
        pats_out[k] = (pat, cnt, len(ap))
        cram = [r["cram"] for r in rs]
        opt = sorted({x for r in rs for x in r["opt"]})
        L.append(f"| {k[0]} | {k[1]} | {k[2]} | {len(rs)} / {tried[k]} | {n[0] if len(n) == 1 else f'{n[0]}..{n[-1]}'} | {cnt} / {len(ap)} | "
                 f"{len(opt)} | {min(cram)}..{max(cram)} |")
    L.append("")
    L.append("Modal CFF bit offsets from the site anchor (min bit of the site's location signature), per setting:")
    L.append("")
    for k, (pat, cnt, n) in pats_out.items():
        if pat:
            L.append(f"- {k[0]} {k[1]} ({k[2]}): {list(pat)}")
    # distinct standard patterns
    st = {k: v[0] for k, v in pats_out.items() if k[0] == "standard" and k[2] == "out"}
    L.append("")
    L.append(f"- standards (out kind) with distinct anchored CFF diffs: {len(set(st.values()))} of {len(st)} tried")
    for pat in sorted(set(st.values())):
        L.append(f"  - {[k[1] for k, v in st.items() if v == pat]}: {len(pat)} bits")
    return "\n".join(L) + "\n"


def main():
    global OUT
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_io_pairs.log"), mode="a")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("pins").set_defaults(f=cmd_pins)
    b = sp.add_parser("build")
    b.add_argument("--jobs", type=int, default=12)
    b.add_argument("--banks", default="")
    b.add_argument("--kinds", default="")
    b.add_argument("--limit-sites", type=int, default=0)
    b.set_defaults(f=cmd_build)
    sp.add_parser("analyse").set_defaults(f=cmd_analyse)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
