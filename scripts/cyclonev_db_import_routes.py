#!/usr/bin/env python3.15t
"""Import Cyclone V routing-node tables into pluribus's SQLite/Postgres DB.

WHY THIS EXISTS
----------------
docs/cyclonev-rust-port.md's "Next-session scope" item 1: the die-geometry +
PRAM-strip import (scripts/cyclonev_db_import.py) landed cv_dies/cv_pram_strips
but explicitly left the routing/mux layer unimported. cv-bmux.cc/cv-rmux.cc
(the actual Rust-port target) consume exactly this data, so it has to be in
SQLite before any of that logic can be written as queries instead of pointer
arithmetic over Mistral's compiled blobs.

BOOTSTRAP/VERIFICATION SOURCE, NOT A PERMANENT DEPENDENCY
----------------------------------------------------------
The 5 files this script parses (data/<die>-r.txt.xz, -l.txt.xz, -d.txt.xz,
-p2r.txt, -p2p.txt) are Project Mistral's (Ravenslofty/mistral) own curated
routing ground truth -- borrowed the same way cv_pram_strips already borrows
-pram.txt. This import is useful and real (it gives a working Rust node/mux
layer something true to query today), but it is not meant to be pluribus's
permanent source of Cyclone V routing truth. The independent, longer-term
path for the same ground truth is a Quartus-based fuzzing campaign: compile
known test designs that exercise specific routing patterns, decompile, and
cross-check against the known design -- the same method already used for
DSP operational modes (scripts/cyclonev_dsp_fuzz.py) and for the Lattice side
(scripts/run_prjtrellis_fuzz.py). That campaign is explicitly NOT attempted
here -- the routing-pattern space is far larger than DSP modes -- and is real
future work, not a gap in this script.

GRAMMARS (read from the generator/*.cc PRODUCER side, not the cv-rmux.cc
compiled-consumer side -- same discipline as cyclonev_db_import.py reading
generator/pram.cc rather than reverse-engineering cvd-*.cc's binary layout):

  <die>-r.txt.xz   (generator/routes.cc  RoutesParser)
      "RTYPE.x.y.z PATTERN:X_Y SLOT:STYPE.x.y.z SLOT:STYPE.x.y.z ...\n"
      or "RTYPE.x.y.z -\n" (no mux -- terminal rnode).
      PATTERN is "N" (0..69) or "N.M" (pattern 6's 4 sub-variants -> 70+M).
      "X_Y" is the cram frame-word position (pat_x + pat_y*width), textually
      "<x>_<y>" per routes.cc's own %d_%d-shaped read (lookup_int then '_').

  <die>-l.txt.xz   (generator/lines.cc  LinesParser)
      "RTYPE.x.y.z TC1 TC2 R85 CAP DRIVERPOS LENGTH [POS:TARGET ...]\n"
      TARGET is "STYPE.x.y.z:0|1" (subslot flag) or a bare float (capacitance
      tap, no downstream rnode).

  <die>-d.txt.xz   (generator/rdriver.cc  RDriverParser)
      "RTYPE.x.y.z DRIVER_LEFT [DRIVER_RIGHT]\n" -- driver name tokens from
      generator/drivers.cc's driver_type_names (stored here as literal text,
      see schema.py's cv_route_drivers comment for why).

  <die>-p2r.txt    (generator/p2r.cc  P2RLoader)
      Block header "BLOCKTYPE bx by\n", then indented port lines
      "  porttype INST BIT rnode_or_dash rnode_or_dash ...\n" where INST/BIT
      are each either "." (no range, 1 entry) or an integer count; the
      trailing list is nbit-fastest (inner loop) across ninst (outer loop),
      exactly mirroring P2RLoader's nested for(inst) for(bit) order.

  <die>-p2p.txt    (generator/p2p.cc  P2PLoader)
      "SRC_PNODE DST_PNODE\n", each pnode "BLOCKTYPE.x.y[.inst][:porttype[.bit]]".

MULTITHREADING
--------------
python3.15t, real threading.Thread + queue.Queue, mirroring reach.py's worker
pattern exactly (CountedLock, work_q.get(timeout=...), error_event, bulk
insert after join -- not during). Two independent levels of parallel work,
both real (see docs/cyclonev-rust-port.md for measured wall-clock numbers):

  1. Per-die: importing N dies is N independent units of work -- one thread
     per die up to --workers.
  2. Per-file-chunk: e50f's -r.txt.xz (695,446 lines) and -l.txt.xz (625,862
     lines) are each large enough that splitting one file's lines into
     --chunk-workers independent byte ranges (split on '\n', which is safe
     here because every record in every one of these 5 grammars is exactly
     one line -- confirmed by reading the generator parsers above, none of
     which carries state across a '\n') and parsing each range in its own
     thread measurably beats single-threaded parsing of one die's files.

Always-rebuild per die (delete + reinsert), db.die() fail-fast on any parse
mismatch. Logs to ./tmp/logs/cyclonev_db_import_routes.log.

Usage:
    python3.15t scripts/cyclonev_db_import_routes.py --die e50f
    python3.15t scripts/cyclonev_db_import_routes.py --die e50f --chunk-workers 8
    python3.15t scripts/cyclonev_db_import_routes.py          # all 7 dies, threaded
"""
import argparse
import datetime
import logging
import lzma
import os
import queue
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import db
import schema

DEFAULT_MISTRAL_ROOT = "/mnt/2tb/git/mistral"
ALL_DIES = ["e50f", "gt75f", "gt150f", "gt300f", "gx25f", "sx50f", "sx120f"]

# rmux_patterns bit-width table (generator/routes.cc) -- only .bits (source
# span) is needed here, to sanity-check parsed source-slot counts against the
# pattern's declared span rather than trusting the text blindly.
RMUX_SPAN = [
    1, 2, 5, 5, 5, 5, 9, 9, 9, 9, 9, 9, 29, 32, 32, 32, 51, 11, 73, 73,
    36, 36, 36, 36, 36, 36, 73, 11, 51, 11, 91, 69, 91, 103, 44, 44, 44, 44,
    44, 44, 109, 91, 91, 91, 91, 91, 91, 175, 175, 175, 175, 175, 175, 52, 52,
    175, 175, 175, 76, 76, 76, 76, 175, 175, 119, 119, 76, 76, 76, 76,
    9, 9, 9, 9,  # pattern 6's 4 sub-variants (70..73), same span as pattern 6
]


def setup_logging():
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    log = logging.getLogger("cyclonev_db_import_routes")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fh = logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cyclonev_db_import_routes.log"))
    sh = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh.setFormatter(fmt)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    return log


# ── shared tokenizers ─────────────────────────────────────────────────────

def _rnode(tok):
    """Parse 'TYPE.x.y.z' -> (type, x, y, z). None if tok is '-' (no node)."""
    if tok == "-":
        return None
    parts = tok.split(".")
    if len(parts) != 4:
        return "BAD"
    t, x, y, z = parts
    if not (x.isdigit() and y.isdigit() and z.isdigit()):
        return "BAD"
    return (t, int(x), int(y), int(z))


def _pnode(tok):
    """Parse 'BLOCKTYPE.x.y[.inst][:porttype[.bit]]' -> dict. None if '-'.

    The ':porttype' suffix is OPTIONAL (nodes.cc lookup_p: the instance digit
    is consumed unconditionally, the ':port' branch only `if(*p == ':')`) --
    272/1755 e50f -p2p.txt lines are a bare block+instance reference with no
    port at all, e.g. "DQS16.000.016.0" (port_type stored as None = PNONE).
    """
    if tok == "-":
        return None
    head, has_port, port = tok.partition(":")
    hparts = head.split(".")
    if len(hparts) not in (3, 4):
        return "BAD"
    btype, bx, by = hparts[0], hparts[1], hparts[2]
    binst = int(hparts[3]) if len(hparts) == 4 else None
    if not (bx.isdigit() and by.isdigit()):
        return "BAD"
    if not has_port:
        return {
            "block_type": btype, "block_x": int(bx), "block_y": int(by), "block_instance": binst,
            "port_type": None, "port_bit": None,
        }
    pparts = port.split(".")
    ptype = pparts[0]
    pbit = int(pparts[1]) if len(pparts) == 2 else None
    return {
        "block_type": btype, "block_x": int(bx), "block_y": int(by), "block_instance": binst,
        "port_type": ptype, "port_bit": pbit,
    }


# ── data/<die>-r.txt.xz : routes ────────────────────────────────────────────

def parse_routes_chunk(lines, path, line_offset, log):
    rows = []
    for i, line in enumerate(lines):
        line = line.rstrip("\r\n")
        if not line:
            continue
        lineno = line_offset + i + 1
        sp = line.find(" ")
        if sp == -1:
            db.die(f"{path}:{lineno}: no space after destination rnode: {line!r}")
        rn = _rnode(line[:sp])
        if rn is None or rn == "BAD":
            db.die(f"{path}:{lineno}: bad destination rnode: {line!r}")
        rest = line[sp + 1:]
        toks = rest.split(" ")

        # A '-' pattern token means "no mux selection" (routes.cc: consumes
        # '-', sets pattern=0xfe/fw_pos=0) but the rnode can still carry a
        # fixed source list after it -- 82,932/695,446 e50f rows, e.g. a
        # sector-clock-buffer stage with exactly one hardwired input and no
        # actual mux bits. Only the pattern/fw_pos fields are absent, sources
        # are parsed the same as the normal case.
        if toks[0] == "-":
            pattern, fw_pos = None, 0
            src_toks = toks[1:]
        else:
            pat_tok, _, fwpos_tok = toks[0].partition(":")
            if "." in pat_tok:
                base, _, opt = pat_tok.partition(".")
                if base != "6":
                    db.die(f"{path}:{lineno}: only pattern 6 has '.' options: {line!r}")
                pattern = 70 + int(opt)
            else:
                pattern = int(pat_tok)
            if "_" not in fwpos_tok:
                db.die(f"{path}:{lineno}: bad pattern position token {toks[0]!r}: {line!r}")
            px, _, py = fwpos_tok.partition("_")
            fw_pos = int(px) + int(py) * ROUTES_WIDTH[0]
            src_toks = toks[1:]

        sources = []
        for tok in src_toks:
            slot_tok, _, srn_tok = tok.partition(":")
            if not slot_tok.isdigit():
                db.die(f"{path}:{lineno}: bad slot number {tok!r}: {line!r}")
            srn = _rnode(srn_tok)
            if srn is None or srn == "BAD":
                db.die(f"{path}:{lineno}: bad source rnode {tok!r}: {line!r}")
            sources.append({"slot": int(slot_tok), "type": srn[0], "x": srn[1], "y": srn[2], "z": srn[3]})

        if pattern is not None and pattern < len(RMUX_SPAN):
            span = RMUX_SPAN[pattern]
            bad_slots = [s["slot"] for s in sources if s["slot"] >= span]
            if bad_slots:
                db.die(f"{path}:{lineno}: pattern {pattern} span={span} but got slot(s) "
                       f"{bad_slots} out of range: {line!r}")

        rows.append({
            "rn_type": rn[0], "rn_x": rn[1], "rn_y": rn[2], "rn_z": rn[3],
            "pattern": pattern, "fw_pos": fw_pos, "sources": sources,
        })
    return rows


# width is per-die; threaded chunk parsers need it without a closure rebuild
# per chunk, so it's set as a 1-element list "cell" before dispatch.
ROUTES_WIDTH = [0]


# ── data/<die>-l.txt.xz : lines ─────────────────────────────────────────────

def parse_lines_chunk(lines, path, line_offset, log):
    rows = []
    for i, line in enumerate(lines):
        line = line.rstrip("\r\n")
        if not line:
            continue
        lineno = line_offset + i + 1
        toks = line.split(" ")
        if len(toks) < 6:
            db.die(f"{path}:{lineno}: too few fields: {line!r}")
        rn = _rnode(toks[0])
        if rn is None or rn == "BAD":
            db.die(f"{path}:{lineno}: bad source rnode: {line!r}")
        try:
            tc1, tc2, r85, cap_raw = (float(toks[1]), float(toks[2]),
                                       float(toks[3]), float(toks[4]))
            driver_position = int(toks[5])
            length = int(toks[6]) if len(toks) > 6 and toks[6].lstrip("-").isdigit() else 0
        except ValueError:
            db.die(f"{path}:{lineno}: bad numeric field: {line!r}")

        # length is present whenever there IS a 7th token that parses as a
        # plain int; targets start at the first "N:..." token after it.
        target_start = 7 if (len(toks) > 6 and toks[6].lstrip("-").isdigit()) else 6
        targets = []
        for tok in toks[target_start:]:
            if not tok:
                continue
            pos_tok, _, val_tok = tok.partition(":")
            if not pos_tok.isdigit():
                db.die(f"{path}:{lineno}: bad target position {tok!r}: {line!r}")
            pos = int(pos_tok)
            rn_tok, sep, sub_tok = val_tok.partition(":")
            if sep:  # "TYPE.x.y.z:subslot"
                trn = _rnode(rn_tok)
                if trn is None or trn == "BAD":
                    db.die(f"{path}:{lineno}: bad target rnode {tok!r}: {line!r}")
                targets.append({
                    "pos": pos, "type": trn[0], "x": trn[1], "y": trn[2], "z": trn[3],
                    "subslot": sub_tok == "1", "cap": None,
                })
            else:  # bare capacitance tap
                try:
                    cap = float(val_tok)
                except ValueError:
                    db.die(f"{path}:{lineno}: bad capacitance target {tok!r}: {line!r}")
                targets.append({
                    "pos": pos, "type": None, "x": None, "y": None, "z": None,
                    "subslot": False, "cap": cap,
                })

        rows.append({
            "rn_type": rn[0], "rn_x": rn[1], "rn_y": rn[2], "rn_z": rn[3],
            "tc1": tc1, "tc2": tc2, "r85": r85, "c_farads": cap_raw * 1e-15,
            "driver_position": driver_position, "length": length, "targets": targets,
        })
    return rows


# ── data/<die>-d.txt.xz : rdriver ───────────────────────────────────────────

def parse_rdriver_chunk(lines, path, line_offset, log):
    rows = []
    for i, line in enumerate(lines):
        line = line.rstrip("\r\n")
        if not line:
            continue
        lineno = line_offset + i + 1
        toks = line.split(" ")
        if len(toks) < 2:
            db.die(f"{path}:{lineno}: too few fields: {line!r}")
        rn = _rnode(toks[0])
        if rn is None or rn == "BAD":
            db.die(f"{path}:{lineno}: bad rnode: {line!r}")
        left = toks[1]
        right = toks[2] if len(toks) > 2 and toks[2] else left
        rows.append({
            "rn_type": rn[0], "rn_x": rn[1], "rn_y": rn[2], "rn_z": rn[3],
            "driver_left": left, "driver_right": right,
        })
    return rows


# ── data/<die>-p2r.txt : port -> rnode ──────────────────────────────────────

def parse_p2r_file(path, log):
    """Not chunked: has block-header/indented-port cross-line state
    (P2RLoader tracks "current block" across lines), unlike the other 4
    grammars. Only 1,536 lines for e50f -- not worth the complexity."""
    rows = []
    cblock_type = cblock_x = cblock_y = None
    with open(path, "r") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip("\r\n")
            if not line:
                continue
            if not line.startswith(" "):
                toks = line.split()
                if len(toks) != 3:
                    db.die(f"{path}:{lineno}: bad block header: {line!r}")
                cblock_type, cblock_x, cblock_y = toks[0], int(toks[1]), int(toks[2])
                continue
            if cblock_type is None:
                db.die(f"{path}:{lineno}: port line before any block header: {line!r}")
            toks = line.split()
            if len(toks) < 3:
                db.die(f"{path}:{lineno}: bad port line: {line!r}")
            port_type, inst_tok, bit_tok = toks[0], toks[1], toks[2]
            ninst = 1 if inst_tok == "." else int(inst_tok)
            nbit = 1 if bit_tok == "." else int(bit_tok)
            rnode_toks = toks[3:]
            if len(rnode_toks) != ninst * nbit:
                db.die(f"{path}:{lineno}: expected {ninst}*{nbit}={ninst*nbit} rnodes, "
                       f"got {len(rnode_toks)}: {line!r}")
            k = 0
            for inst in range(ninst):
                for bit in range(nbit):
                    rn = _rnode(rnode_toks[k])
                    k += 1
                    row = {
                        "block_type": cblock_type, "block_x": cblock_x, "block_y": cblock_y,
                        "block_instance": inst if ninst > 1 else None,
                        "port_type": port_type, "port_bit": bit if nbit > 1 else None,
                        "rn_type": None, "rn_x": None, "rn_y": None, "rn_z": None,
                    }
                    if rn == "BAD":
                        db.die(f"{path}:{lineno}: bad rnode token {rnode_toks[k-1]!r}: {line!r}")
                    if rn is not None:
                        row["rn_type"], row["rn_x"], row["rn_y"], row["rn_z"] = rn
                    rows.append(row)
    return rows


# ── data/<die>-p2p.txt : port -> port ───────────────────────────────────────

def parse_p2p_file(path, log):
    rows = []
    with open(path, "r") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip("\r\n")
            if not line:
                continue
            toks = line.split()
            if len(toks) != 2:
                db.die(f"{path}:{lineno}: expected 2 pnodes: {line!r}")
            s, d = _pnode(toks[0]), _pnode(toks[1])
            if s in (None, "BAD") or d in (None, "BAD"):
                db.die(f"{path}:{lineno}: bad pnode: {line!r}")
            rows.append({
                "src_block_type": s["block_type"], "src_block_x": s["block_x"],
                "src_block_y": s["block_y"], "src_block_instance": s["block_instance"],
                "src_port_type": s["port_type"], "src_port_bit": s["port_bit"],
                "dst_block_type": d["block_type"], "dst_block_x": d["block_x"],
                "dst_block_y": d["block_y"], "dst_block_instance": d["block_instance"],
                "dst_port_type": d["port_type"], "dst_port_bit": d["port_bit"],
            })
    return rows


# ── threaded chunk dispatch (mirrors reach.py's worker/queue/lock pattern) ──

def _run_chunked(path, parse_fn, n_workers, log, extra_log=""):
    """Decompress-or-read path, split into n_workers line-range chunks on
    real newline boundaries (safe: every record in these grammars is exactly
    one line), parse each chunk in its own thread, return concatenated rows
    in original file order.
    """
    t0 = time.time()
    if path.endswith(".xz"):
        with lzma.open(path, "rb") as f:
            text = f.read().decode("ascii")
    else:
        with open(path, "r") as f:
            text = f.read()
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    n = len(lines)
    t_read = time.time() - t0

    if n_workers <= 1 or n < n_workers * 1000:
        rows = parse_fn(lines, path, 0, log)
        log.info(f"  {os.path.basename(path)}: {n} lines, 1 thread "
                  f"(single-threaded: too small to chunk), read={t_read:.1f}s{extra_log}")
        return rows

    chunk_size = (n + n_workers - 1) // n_workers
    chunks = [(i, lines[i:i + chunk_size]) for i in range(0, n, chunk_size)]
    results = [None] * len(chunks)
    error_event = threading.Event()

    def _worker(idx, offset, chunk_lines):
        try:
            results[idx] = parse_fn(chunk_lines, path, offset, log)
        except SystemExit:
            error_event.set()
        except Exception as exc:
            error_event.set()
            print(f"FATAL: chunk worker {idx} died: {exc}", file=sys.stderr)

    t1 = time.time()
    threads = [threading.Thread(target=_worker, args=(idx, off, cl), daemon=True)
               for idx, (off, cl) in enumerate(chunks)]
    for t in threads: t.start()
    for t in threads: t.join()
    t_parse = time.time() - t1

    if error_event.is_set():
        db.die(f"{path}: one or more chunk-parse threads failed, see FATAL lines above")

    rows = [r for chunk_rows in results for r in chunk_rows]
    log.info(f"  {os.path.basename(path)}: {n} lines, {len(chunks)} threads, "
              f"read={t_read:.1f}s parse={t_parse:.1f}s{extra_log}")
    return rows


# ── per-die import ───────────────────────────────────────────────────────

def import_die_routes(mistral_root, die, chunk_workers, log):
    t_die = time.time()
    paths = {
        "r": os.path.join(mistral_root, "data", f"{die}-r.txt.xz"),
        "l": os.path.join(mistral_root, "data", f"{die}-l.txt.xz"),
        "d": os.path.join(mistral_root, "data", f"{die}-d.txt.xz"),
        "p2r": os.path.join(mistral_root, "data", f"{die}-p2r.txt"),
        "p2p": os.path.join(mistral_root, "data", f"{die}-p2p.txt"),
    }
    for kind, p in paths.items():
        if not os.path.isfile(p):
            db.die(f"missing {p} ({kind}) — is --mistral-root correct?")

    conn = db.connect_threadsafe()
    cur = conn.execute("SELECT id, tile_sx FROM cv_dies WHERE name = ?", (die,)) \
        if db.BACKEND != "postgres" else None
    if db.BACKEND == "postgres":
        import pg8000.native
        row = conn.run("SELECT id, tile_sx FROM cv_dies WHERE name = :d", d=die)
        if not row:
            db.die(f"die {die!r} not found in cv_dies — run scripts/cyclonev_db_import.py first")
        die_id, tile_sx = row[0]
    else:
        row = cur.fetchone()
        if not row:
            db.die(f"die {die!r} not found in cv_dies — run scripts/cyclonev_db_import.py first")
        die_id, tile_sx = row
    conn.close()

    ROUTES_WIDTH[0] = tile_sx  # routes.cc's "width" param = tile_sx (generator.cc call site)

    routes = _run_chunked(paths["r"], parse_routes_chunk, chunk_workers, log)
    lines_ = _run_chunked(paths["l"], parse_lines_chunk, chunk_workers, log)
    rdriver = _run_chunked(paths["d"], parse_rdriver_chunk, chunk_workers, log)
    p2r = parse_p2r_file(paths["p2r"], log)
    p2p = parse_p2p_file(paths["p2p"], log)

    log.info(f"{die}: parsed routes={len(routes)} lines={len(lines_)} "
              f"rdriver={len(rdriver)} p2r={len(p2r)} p2p={len(p2p)}")

    conn = db.connect_threadsafe()
    try:
        # Always-rebuild: delete this die's rows from all 5 tables first.
        for tbl in ("cv_route_muxes", "cv_route_lines", "cv_route_drivers", "cv_p2r", "cv_p2p"):
            conn.execute(f"DELETE FROM {tbl} WHERE die = ?", (die_id,))

        def _bulk(table, cols, rows):
            if not rows:
                return
            placeholders = ",".join("?" * (len(cols) + 1))
            sql = f"INSERT INTO {table} (die,{','.join(cols)}) VALUES ({placeholders})"
            CHUNK = 50_000
            for i in range(0, len(rows), CHUNK):
                batch = rows[i:i + CHUNK]
                conn.executemany(sql, [
                    (die_id,) + tuple(
                        __import__("json").dumps(r[c]) if isinstance(r[c], list) else r[c]
                        for c in cols
                    )
                    for r in batch
                ])

        _bulk("cv_route_muxes",
              ["rn_type", "rn_x", "rn_y", "rn_z", "pattern", "fw_pos", "sources"], routes)
        _bulk("cv_route_lines",
              ["rn_type", "rn_x", "rn_y", "rn_z", "tc1", "tc2", "r85", "c_farads",
               "driver_position", "length", "targets"], lines_)
        _bulk("cv_route_drivers",
              ["rn_type", "rn_x", "rn_y", "rn_z", "driver_left", "driver_right"], rdriver)
        _bulk("cv_p2r",
              ["block_type", "block_x", "block_y", "block_instance", "port_type", "port_bit",
               "rn_type", "rn_x", "rn_y", "rn_z"], p2r)
        _bulk("cv_p2p",
              ["src_block_type", "src_block_x", "src_block_y", "src_block_instance",
               "src_port_type", "src_port_bit", "dst_block_type", "dst_block_x", "dst_block_y",
               "dst_block_instance", "dst_port_type", "dst_port_bit"], p2p)

        if db.BACKEND == "sqlite":
            conn.commit()
    finally:
        conn.close()

    dt = time.time() - t_die
    log.info(f"{die}: inserted {len(routes)+len(lines_)+len(rdriver)+len(p2r)+len(p2p)} "
              f"total rows in {dt:.1f}s")
    return dt


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--die", choices=ALL_DIES, help="import a single die (default: all 7)")
    ap.add_argument("--mistral-root", default=DEFAULT_MISTRAL_ROOT)
    ap.add_argument("--chunk-workers", type=int, default=min(8, os.cpu_count() or 4),
                     help="threads used to parse EACH large file's lines in parallel (default: 8)")
    ap.add_argument("--die-workers", type=int, default=min(4, os.cpu_count() or 4),
                     help="threads used to import DIFFERENT DIES in parallel when --die is omitted")
    ap.add_argument("--single-threaded", action="store_true",
                     help="force 1 chunk worker and 1 die worker, for A/B timing comparison")
    args = ap.parse_args()

    log = setup_logging()
    schema.init()

    chunk_workers = 1 if args.single_threaded else args.chunk_workers
    die_workers = 1 if args.single_threaded else args.die_workers

    dies = [args.die] if args.die else ALL_DIES
    log.info(f"NoGIL: {not sys._is_gil_enabled()}  "
             f"importing {len(dies)} die(s) from {args.mistral_root}, "
             f"chunk_workers={chunk_workers} die_workers={die_workers if len(dies) > 1 else 1}")

    t0 = time.time()
    if len(dies) == 1 or die_workers <= 1:
        for die in dies:
            import_die_routes(args.mistral_root, die, chunk_workers, log)
    else:
        error_event = threading.Event()
        results = {}

        def _die_worker(die):
            try:
                results[die] = import_die_routes(args.mistral_root, die, chunk_workers, log)
            except SystemExit:
                error_event.set()
            except Exception as exc:
                error_event.set()
                print(f"FATAL: die worker {die} died: {exc}", file=sys.stderr)

        work_q = queue.Queue()
        for d in dies:
            work_q.put(d)

        def _pool_worker():
            while True:
                try:
                    d = work_q.get_nowait()
                except queue.Empty:
                    return
                _die_worker(d)

        threads = [threading.Thread(target=_pool_worker, daemon=True) for _ in range(die_workers)]
        for t in threads: t.start()
        for t in threads: t.join()
        if error_event.is_set():
            db.die("one or more die import threads failed — see FATAL lines above")

    log.info(f"done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
