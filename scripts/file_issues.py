#!/usr/bin/env python3
"""One-shot: file the native-decoder epic + sub-issues (awtoau/pluribus) and the
prjtrellis-correctness epic + A-I (awtoau/prjtrellis), link subs to their epic,
and log every URL. Run ONCE. Log: ./tmp/file_issues.log

Content is deliberately GENERIC (MachXO2 / toolchain in the abstract) — no private
paths, no secrets, no reference to any specific board or its bitstreams.
"""
import subprocess, re, pathlib, sys

LOG = []
def log(s): print(s); LOG.append(s)

def gh_create(repo, title, body):
    r = subprocess.run(["gh", "issue", "create", "--repo", repo,
                        "--title", title, "--body", body],
                       capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    m = re.search(r"/issues/(\d+)", out)
    num = int(m.group(1)) if m else None
    log(f"  [{'ok' if num else 'FAIL'}] {repo}#{num}  {title}")
    if not num: log(f"      -> {out}")
    return num

def gh_edit_body(repo, num, body):
    subprocess.run(["gh", "issue", "edit", str(num), "--repo", repo, "--body", body],
                   capture_output=True, text=True)

def gh_close(repo, num, comment):
    subprocess.run(["gh", "issue", "close", str(num), "--repo", repo, "--comment", comment],
                   capture_output=True, text=True)

PLU = "awtoau/pluribus"
TRE = "awtoau/prjtrellis"

def at(s): return f"\n\n**Acceptance test:** {s}"

# ---- pluribus port sub-issues (generic MachXO2 wording) ----
P = [
 ("[P1] Crack MachXO2 bitstream command 0x72 structure",
  "Command `0x72` (0b01110010) is emitted after the fabric config frames and is NOT in "
  "prjtrellis's `BitstreamCommand` enum. It appears in real MachXO2 vendor bitstreams and when an "
  "EFB peripheral is enabled; leading form `72 10 54 0a 00 80 00 00`; variable length; likely a "
  "Feature-Row/FEABITS/sysCONFIG command (nearest documented opcode `LSC_PROG_INCR_NV 0x70`). "
  "Because it's unmodelled, a decoder can stop there and silently drop the remainder of the "
  "stream (EBR block-RAM init, USERCODE, DONE). Determine its exact byte structure and length "
  "rule.\n\nMethod: build Diamond bitstreams toggling ONE sysCONFIG/EFB feature at a time with "
  "`COMPRESS_CONFIG=OFF`; byte-diff the post-frame region to isolate 0x72's payload + length "
  "encoding."
  + at("A documented length rule such that a parser consuming 0x72 lands exactly on the next "
       "known command, then reaches DONE consuming the whole stream, on several real MachXO2 "
       "bitstreams and >=3 feature-varied fuzz bitstreams.")),
 ("[P2] Native Python bitstream parser (bin -> frames + commands)",
  "Port the bin -> CRAM-frames + command-stream parser to pure Python (replacing the pytrellis "
  "dependency of the parse stage). Handle every command (grammar in libtrellis `Bitstream.cpp`), "
  "the compressed-frame codec, CRC16, and 0x72 (P1). No silent truncation: an unknown command is "
  "a loud error; track `frames_read`."
  + at("Parse a real MachXO2 bitstream to completion: all config frames read, entire stream "
       "consumed to DONE (incl. 0x72 + any EBR blocks), `frames_read==num_frames`, final CRC "
       "verifies; extracted CRAM byte-identical to pytrellis `chip.cram`.")),
 ("[P3] Round-trip re-encode proof (decoder losslessness)",
  "Implement the config -> bitstream encoder (frame assembly, compression, CRC) and prove the "
  "decode loses nothing."
  + at("`re_encode(decode(bin)) == bin` byte-exact for the reference bitstreams and a fuzz-corpus "
       "sample. Any mismatch fails. (This is the completeness test the current decoder fails via "
       "0x72.)")),
 ("[P4] Tile decode: CRAM -> enums/words/arcs via bits.db (NoGIL-parallel)",
  "Decode CRAM into per-tile {enums, words, arcs} using the tile `bits.db` (loaded into the "
  "pluribus DB / parsed). Parallelise across tiles with python3.14t NoGIL."
  + at("Produced `.config` semantically equals pytrellis's for every tile on the reference "
       "bitstreams (verified by the P5 parity harness).")),
 ("[P5] Parity harness: native decode == prjtrellis decode over the whole corpus",
  "Differential test comparing canonical `{tile, bit/enum/arc}` sets (order-independent) of the "
  "native decoder vs prjtrellis across all ~3000 fuzz bitstreams + the reference bitstreams. "
  "prjtrellis is the fidelity reference; Diamond is the correctness oracle for deltas."
  + at("Zero divergences over the corpus EXCEPT the known-corrected cases (0x72 / EBR.MODE / "
       "PULLMODE), which must diverge from prjtrellis and match Diamond.")),
 ("[P6] Completeness #1: recovered.v == source.v (yosys equiv, whole corpus)",
  "For every fuzz target, formally check the lifted `recovered.v` against the original design "
  "`.v` with yosys (`equiv_opt`/SAT LEC); hard-IP targets (EBR/EFB/PLL) compared by config enums "
  "instead of logic. No Diamond re-run needed."
  + at("Equivalence passes for all combinational/sequential targets; every failure is triaged as "
       "a specific lifter defect (the run produces a defect map).")),
 ("[P7] Completeness #2: Diamond round-trip on a real bitstream (bit-diff)",
  "lift a real bitstream -> Verilog (+ LOCATE/routing constraints) -> Diamond synth/PAR/bitgen "
  "-> bitstream' -> compare. Functional (netlist-equiv) and structural (bit-diff) variants; "
  "residual bit count is a quality metric."
  + at("Functional round-trip passes (recovered.v synthesizes and decodes to an equivalent "
       "netlist); structural residual is reported and trends down as the lift improves.")),
 ("[P8] Routing-graph port (deferred)",
  "Port `DedupChipdb`/`RoutingGraph` to Python or derive it from DB-loaded connectivity, for "
  "lift net-globalisation. Until done, the lifter keeps using pytrellis `get_routing_graph` ONLY."
  + at("Net globalisation matches the pytrellis-based lift on the reference bitstream.")),
 ("[P9] Pipeline hygiene",
  "Fix trust/repro issues: `db.py` default backend is `postgres` but the docs say sqlite; a "
  "removed `psycopg2` is still imported in a fuzz status script; `requirements.txt` covers only "
  "~2 of ~7 real deps; some scripts hardcode external absolute paths without an env override; a "
  "referenced Diamond strategy file is absent from the repo copy."
  + at("Fresh checkout runs the pipeline/tests with documented env; no psycopg2 import; hardcoded "
       "paths are env-configurable; `db.py` default matches the docs.")),
]

# ---- prjtrellis reference bugs A-I (generic) ----
T = [
 ("[A] Decoder silently returns partial config on unknown command",
  "`deserialise_chip` lenient default (Bitstream.cpp:811-822) returns `*chip` on the first "
  "unknown opcode with only a stderr NOTE - no error, no flag. In forced mode `chip` is always "
  "set, so it fires unconditionally; a truncated decode is indistinguishable from a complete one."
  + at("Add `truncated`/`stop_offset`/`stop_cmd` to `Chip`, exposed via PyTrellis; default "
       "fail-loud; a decode that stops early is detectable by the caller and by CI.")),
 ("[B] Command 0x72 unmodeled -> post-frame config dropped",
  "After the fabric frames a real MachXO2 stream continues `0x72 -> LSC_EBR_WRITE blocks (fully "
  "modelled) -> USERCODE -> CNTRL0 -> DONE`; the lenient stop discards it, so `.bram_init` never "
  "reaches the config. 0x72 is a standard MachXO2 post-fabric command."
  + at("A consuming case for 0x72 lets the parser continue into the EBR/USERCODE/DONE tail; the "
       "decode yields its `.bram_init` sections.")),
 ("[C] Forced device skips geometry validation (wrong-device silent truncation)",
  "Forced mode builds `Chip(force_device)` and never validates against the stream; a stream for a "
  "larger device pointed at a smaller forced default fills only part of the frames, then desyncs "
  "and lenient-returns."
  + at("Read frame-count is asserted == the forced device's frame-count; a mismatch errors "
       "instead of truncating.")),
 ("[D] pybind11 too old for free-threading -> segfault under python3.14t NoGIL  (DONE)",
  "Bundled pybind11 2.11.0.dev1 predates free-threading; import crashed in `PyInit_pytrellis` "
  "under python3.14t. FIXED: upgraded to pybind11 2.13.6 + `py::mod_gil_not_used()`; pytrellis "
  "now imports and decodes under 3.14t (GIL disabled)."
  + at("pytrellis imports + decodes under python3.14t with the GIL disabled. (Met.)")),
 ("[E] No parser tests; CI is packaging-only",
  "libtrellis ships no `add_test`/pytest and no round-trip test; CI is an Arch package build."
  + at("A decode-completeness + byte-exact `read->deserialise->serialise->write` round-trip "
       "regression on golden bitstreams runs in CI.")),
 ("[F] Unvalidated frame_count causes desync",
  "`frame_count` from the stream is used unchecked as loop bound and CRAM index "
  "(Bitstream.cpp:677-702); `frame_count==0` skips the trailing CRC -> desync."
  + at("frame_count is bounds-checked against num_frames; the zero case is handled; a crafted "
       "bad count errors cleanly.")),
 ("[G] assert-only over-read guard compiled out under Release",
  "`get_byte()`/`get_command_opcode()` guard end-of-buffer with `assert` only; a Release/NDEBUG "
  "build removes them -> UB on short/corrupt streams."
  + at("End-of-buffer reads throw `BitstreamParseError` regardless of NDEBUG.")),
 ("[H] Unchecked chip-> derefs before device is known",
  "`LSC_PROG_CNTRL0/1`, `LSC_EBR_ADDRESS`, `LSC_PROG_SED_CRC` deref the `boost::optional` chip "
  "without a null-check (:566,:573,:745,:805) - UB if they precede VERIFY_ID in non-forced mode."
  + at("Each deref is guarded; a stream that hits them before device id errors with a clear "
       "parse error.")),
 ("[I] SPI_MODE bad value throws runtime_error, bypassing the parse-error path",
  "`SPI_MODE` on an unknown mode byte throws `runtime_error` (:791), not `BitstreamParseError`."
  + at("An unknown SPI mode throws `BitstreamParseError`, consistent with the other parse "
       "failures.")),
]

def main():
    log("=== pluribus epic ===")
    plu_epic_body = ("Native Python bitstream decoder to replace the prjtrellis decode stage, with "
        "a provable-recovery test harness. Rationale + phases: `docs/prjtrellis-fix-plan.md`, "
        "`docs/native-decoder-direction.md`. Related: #29 (prjtrellis DB gaps).\n\n"
        "Motivating defect: the current decoder can silently truncate a MachXO2 bitstream at "
        "command 0x72, dropping the post-frame config (incl. real EBR block-RAM init). The port "
        "makes silent-incompleteness impossible by construction and unifies decode+lift into the "
        "relational engine.\n\n### Sub-issues\n(filled in after creation)")
    plu_epic = gh_create(PLU, "[EPIC] Native Python decoder + provable recovery", plu_epic_body)

    plu_nums = []
    for title, body in P:
        full = body + (f"\n\nEpic: #{plu_epic}" if plu_epic else "")
        plu_nums.append((gh_create(PLU, title, full), title))

    if plu_epic:
        tasklist = "\n".join(f"- [ ] #{n} {t.split(']')[0][1:]}" for n, t in plu_nums if n)
        gh_edit_body(PLU, plu_epic, plu_epic_body.replace("(filled in after creation)", tasklist))

    log("\n=== prjtrellis epic ===")
    tre_epic_body = ("MachXO2 bitstream-decoder correctness in libtrellis, found via a two-agent "
        "review + byte-decodes of real MachXO2 bitstreams. These are reference-decoder bugs; a "
        "native decoder can fix them by construction, but they are worth fixing/upstreaming here."
        "\n\n### Sub-issues\n(filled in after creation)")
    tre_epic = gh_create(TRE, "[EPIC] MachXO2 bitstream-decoder correctness", tre_epic_body)

    tre_nums = []
    for title, body in T:
        full = body + (f"\n\nEpic: #{tre_epic}" if tre_epic else "")
        tre_nums.append((gh_create(TRE, title, full), title))

    if tre_epic:
        tasklist = "\n".join(f"- [{'x' if '(DONE)' in t else ' '}] #{n} {t.split(']')[0][1:]}"
                             for n, t in tre_nums if n)
        gh_edit_body(TRE, tre_epic, tre_epic_body.replace("(filled in after creation)", tasklist))

    for n, t in tre_nums:
        if n and "(DONE)" in t:
            gh_close(TRE, n, "Fixed: pybind11 -> 2.13.6 + py::mod_gil_not_used(); pytrellis "
                             "imports and decodes under python3.14t with the GIL disabled.")
            log(f"  closed {TRE}#{n} (D, already fixed)")

    log(f"\nEPICS: pluribus#{plu_epic}, prjtrellis#{tre_epic}")
    pathlib.Path("tmp").mkdir(exist_ok=True)
    pathlib.Path("tmp/file_issues.log").write_text("\n".join(LOG) + "\n")

if __name__ == "__main__":
    main()
