#!/usr/bin/env python3.15t
"""Carve embedded FPGA bitstreams out of arbitrary firmware blobs.

Covers every family pluribus has a lifter for: the Lattice parts (ECP5,
MachXO2/XO3/XO3D/MachXO), GOWIN, and Anlogic.

WHY THIS EXISTS
---------------
The third-party corpus (`ecp5_corpus_fetch.py`) works because open-hardware
projects commit a bare `.bit`.  Commercial products almost never do.  An FPGA in
a shipping product is usually configured by a host MCU or loaded from SPI flash,
so the vendor ships ONE update file — a zip, an installer, a flash image, a
firmware container — with the bitstream somewhere inside it.  To test the
decoder against commercial designs at all, we first have to find the bitstream.

WHAT IT LOOKS FOR
-----------------
Per family, a sync word plus a validator, and independently a part-string scan:

  * **Lattice** (ECP5 + all MachXO variants) — sync `FF FF BD B3`.  All five
    families share it, and share the VERIFY_ID (0xE2) command, so ONE scanner
    finds them all; they are told apart afterwards.  This is the real anchor:
    the configuration engine itself searches for this word, so it is present in
    every loadable bitstream regardless of who packed it.
  * **Anlogic** — sync `CC 55 AA 33` (the flash `.bin` form), then a header
    record walk to the DEVICE_ID, matched against `anlogic_unpack.EG4_IDCODES`.
  * **GOWIN** — the `.fs` form is not binary at all: it is ASCII '1'/'0' text,
    one frame per line (confirmed against a real GW1N-2 capture).  So there is
    no sync word to scan for, and GOWIN is detected as a long run of ASCII
    binary digits, plus its part string.  A GOWIN hit is reported as a candidate
    for `gowin_unpack.py` rather than validated here, because validating it
    means decoding it.
  * Part strings for every family (`LFE5U-25F`, `LCMXO2-1200HC`, `GW1NR-9`,
    `EG4S20`, ...) anywhere in the blob, used both to identify a validated hit
    and, on their own, as a signal that a container is worth a closer look.

IDENTIFICATION IS NOT UNIFORM, AND THAT MATTERS
-----------------------------------------------
Only ECP5 carries IDCODEs in Trellis `devices.json`; MachXO2/XO3 entries have
`idcode=None`.  So the ECP5 trick — validate a sync hit by looking its IDCODE up
in the device table — does NOT generalise.  For the MachXO families we accept a
well-formed VERIFY_ID and then resolve the part from the ASCII header's part
string, or leave it unresolved and let the tester's geometry search settle it.
Pretending we can name the part from the IDCODE alone would mean decoding an
LCMXO2-7000 with LCMXO2-1200 geometry, which does not fail loudly: it produces a
plausible, wrong fabric.

VALIDATION IS THE POINT
-----------------------
A 4-byte magic in a multi-megabyte blob yields false positives constantly.  So
every candidate offset is parsed as a bitstream preamble before it is carved.
For ECP5 the IDCODE must be a real ECP5 IDCODE from devices.json; the shared
`idcode_table`/`scan_idcode` logic is imported from `ecp5_corpus_test`, not
re-implemented, so the carver and the tester cannot drift apart in what they
consider a bitstream.

Containers are unwrapped recursively (zip/tar/gzip/bz2/xz), because vendor
packages nest — a zip holding an installer holding a firmware image is normal.

Usage:
    python3.15t scripts/ecp5_carve.py FILE_OR_DIR [...] [--out DIR] [--json OUT]
    python3.15t scripts/ecp5_carve.py FW --families ecp5,machxo2,gowin,anlogic

Logs to ./tmp/logs/ecp5_carve.log.
"""
import argparse
import bz2
import gzip
import hashlib
import io
import json
import logging
import lzma
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

SYNC = b"\xff\xff\xbd\xb3"          # every Lattice family (ECP5 + MachXO*)
ANLOGIC_SYNC = b"\xcc\x55\xaa\x33"  # Anlogic flash .bin

# Part strings as they appear in vendor headers and blobs, per family.  Kept
# broad because the point is to notice the container is interesting; the
# preamble validator classifies it.
PART_RES = {
    "ecp5":    re.compile(rb"LFE5(?:UM5G|UM|U)-?\d{2}F(?:-[0-9A-Za-z]+)?"),
    "machxo2": re.compile(rb"LCMXO2-\d{3,4}[0-9A-Za-z]*"),
    "machxo3": re.compile(rb"LCMXO3D?-\d{3,4}[0-9A-Za-z]*"),
    "machxo":  re.compile(rb"LCMXO\d{3,4}[0-9A-Za-z]*"),
    "gowin":   re.compile(rb"GW[12][ANR]{1,3}-?\d+[0-9A-Za-z-]*"),
    # Anchored on the real Anlogic families (EG4/EF2/EF3/AL3) rather than a
    # loose E[GF]<digits> pattern.  The loose form matched EF19/EG26/EF71 and
    # similar by chance thousands of times in a 154 MB binary, which buries the
    # genuine signal -- a part-string report is only useful if a hit means
    # something.
    "anlogic": re.compile(rb"(?:EG4[A-Z]?\d{2}|EF[23]L?\d{2}|AL3-\d+)"
                          rb"[0-9A-Za-z]*"),
}
# Which families a Lattice-preamble hit could be.  ECP5 is separable by IDCODE;
# the MachXO* families are not (devices.json has idcode=None for them), so they
# are resolved by part string or left unresolved for the tester to settle.
LATTICE_FAMILIES = ("ecp5", "machxo2", "machxo3", "machxo")
ALL_FAMILIES = ("ecp5", "machxo2", "machxo3", "machxo", "gowin", "anlogic")

DEFAULT_OUT = os.path.join(REPO, "corpus", "commercial")

# Smallest real ECP5 bitstream (12F, compressed) is comfortably over 60 KB.
# Below that a sync-word hit with a plausible IDCODE is still noise.
MIN_CARVE = 40 * 1024
# Fallback cap for devices whose geometry is not in the Trellis database (GOWIN,
# Anlogic).  The largest ECP5 (85F) is ~2.5 MB uncompressed, so this is roomy.
MAX_PLAUSIBLE = 8 * 1024 * 1024
# Recursion guard: vendor packages nest, but not deeply.  A blob that claims to
# need more than this is either a bomb or a loop.
MAX_DEPTH = 6
# Do not try to unwrap or scan anything absurd; ECP5 update files are MB-scale.
MAX_MEMBER = 512 * 1024 * 1024
# Trailing 0xFF run kept as the vendor's own padding after DONE (see exact_end).
# A standalone .bit ends in a handful of pad bytes; a megabyte of 0xFF is erased
# flash, which is not part of the bitstream.
TAIL_PAD_MAX = 4096


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
# device table (shared with ecp5_corpus_test so the two cannot disagree)
# ---------------------------------------------------------------------------

def _idcode_table():
    from ecp5_corpus_test import idcode_table
    return idcode_table()


def _ecp5_idcodes(tbl):
    """IDCODE -> device, ECP5 entries only."""
    out = {}
    for idc, hits in tbl.items():
        ecp5 = [d for fam, d in hits if fam == "ECP5"]
        if ecp5:
            out[idc] = ecp5[0]
    return out


# ---------------------------------------------------------------------------
# preamble validation
# ---------------------------------------------------------------------------

def _lattice_opcodes():
    """The set of known Lattice configuration opcodes.

    Taken from native_bitstream's own CMD_NAMES table rather than duplicated, so
    the carver's idea of a valid command cannot drift from the decoder's.
    """
    try:
        import native_bitstream
        return set(native_bitstream.CMD_NAMES)
    except Exception:
        # Conservative fallback: the opcodes actually observed opening real
        # bitstreams (RESET_CRC, dictionary write, control regs, ID, jump).
        return {0x3B, 0x02, 0xE2, 0x22, 0x23, 0xC4, 0x46, 0x08, 0x09, 0x50,
                0xB8, 0x5E, 0x82, 0xA4, 0xF0, 0xC2, 0x30, 0x40}


def _plausible_opcodes(opcodes):
    """True if a command sequence looks like a real Lattice preamble.

    The first command after the sync word is essentially always LSC_RESET_CRC
    (0x3B) in the images observed, and the next few are recognised opcodes.  A
    coincidental sync word inside compressed data fails this immediately -- that
    is what keeps the 8 MB-of-random-data false-positive count at zero even
    without an IDCODE to check.
    """
    if not opcodes:
        return False
    known = _lattice_opcodes()
    if opcodes[0] != 0x3B:                   # LSC_RESET_CRC
        return False
    head = opcodes[:4]
    return sum(1 for c in head if c in known) >= max(2, len(head) - 1)


def parse_preamble(data, sync_off, idcodes, part_hint=None):
    """Validate a Lattice sync-word hit by parsing the command stream after it.

    Returns a dict on success, None if this offset is not a real bitstream
    start.  For ECP5 the discriminator is the IDCODE: a chance `FF FF BD B3` in
    compressed data is overwhelmingly unlikely to be followed by a well-formed
    VERIFY_ID carrying a genuine ECP5 IDCODE.

    A VERIFY_ID IS NOT ALWAYS PRESENT.  MachXO2 images built for SPI-flash
    configuration routinely omit it: the SummerCart64 LCMXO2-7000HC bitstream
    (chunk 3 of its update container) goes straight from the sync word to

        3B 00 00 00   LSC_RESET_CRC
        02 00 00 00   LSC_WRITE_COMP_DIC     <- compressed bitstream
        09 03 30 28   ...
        ...

    with no 0xE2 anywhere.  Requiring VERIFY_ID therefore rejects genuine
    MachXO2 bitstreams, so acceptance falls back to "the command stream opens
    with recognised Lattice opcodes".  Opcodes come from native_bitstream's own
    table, so the carver and the decoder agree on what a command is.

    ECP5 is still identified by IDCODE when a VERIFY_ID exists -- that remains
    the strongest discriminator, and ECP5 images do carry it.  For a MachXO hit
    the part is taken from a nearby ASCII part string when there is one, and
    otherwise left unresolved for the tester's geometry search to settle: naming
    the wrong part decodes into a plausible, wrong fabric instead of failing.
    """
    i = sync_off + 4
    # The command stream before the frame data is short; VERIFY_ID, when
    # present, appears within the first few hundred bytes.  Cap the walk so a
    # garbage region cannot run away.
    end = min(len(data) - 8, i + 4096)
    idcode = None
    verify_off = None
    opcodes = []
    while i < end:
        cmd = data[i]
        if cmd == 0xFF:                      # DUMMY padding byte
            i += 1
            continue
        if cmd == 0xE2:                      # VERIFY_ID
            idcode = int.from_bytes(data[i + 4:i + 8], "big")
            verify_off = i
            break
        opcodes.append(cmd)
        if len(opcodes) >= 6:                # enough to judge plausibility
            break
        i += 4
    if idcode is not None and idcode in idcodes:
        return {"sync_off": sync_off, "verify_off": verify_off,
                "idcode": idcode, "device": idcodes[idcode], "family": "ecp5"}
    # No usable IDCODE.  Accept only if the stream opens with real Lattice
    # commands -- a chance sync word in compressed data almost never does.
    if not _plausible_opcodes(opcodes):
        return None
    fam, dev = "machxo2", None
    if part_hint:
        for f in ("machxo2", "machxo3", "machxo"):
            m = PART_RES[f].search(part_hint)
            if m:
                fam, dev = f, m.group().decode()
                break
    return {"sync_off": sync_off, "verify_off": verify_off, "idcode": idcode,
            # Keep the device token filesystem-safe: it becomes part of the
            # carved filename, and spaces/parens there break downstream tooling
            # that takes an unquoted path.
            "device": dev or "unresolved-no-id",
            "device_note": None if dev else
                           "no VERIFY_ID record and no part string in the "
                           "container; part must come from external evidence",
            "family": fam, "opcodes": [f"0x{c:02x}" for c in opcodes]}


def parse_anlogic(data, sync_off):
    """Validate an Anlogic `CC 55 AA 33` hit and pull its DEVICE_ID.

    The flash `.bin` header is a run of LENGTH-PREFIXED records:

        <tag:1> <len:3 big-endian> <body:len>

    and the stride is 4 + len, verified against the FNIRSI 2D15P vendor image
    where the first record is

        f0 | 00 00 06 | 0a 01 4c 35 a3 bd
        tag  len=6      idcode        crc

    i.e. tag 0xF0 (DEVICE_ID), body = the 4-byte IDCODE 0x0A014C35 followed by a
    2-byte CRC.  That IDCODE is the EG4S20 JTAG IDCODE that
    boards/fnirsi-eg4s20/board.toml independently documents, which is what
    confirms the reading.  Records run until the 0xEC CONFIG header, which is
    reached cleanly after 11 records on the real image.

    The stride is load-bearing.  Walking a fixed width, or byte-at-a-time,
    mis-reads body bytes as tags and never finds DEVICE_ID at all -- the failure
    mode is a silent miss, not an error.  The IDCODE is then matched against
    `anlogic_unpack.EG4_IDCODES`, the same discriminator role the ECP5 IDCODE
    plays, so a chance sync word is rejected.
    """
    try:
        from anlogic_unpack import EG4_IDCODES
    except Exception:
        EG4_IDCODES = {}
    i = sync_off + 4
    end = min(len(data), i + 4096)
    idcode = None
    while i + 4 <= end:
        tag = data[i]
        if tag == 0xEC:                       # CONFIG header: end of preamble
            break
        ln = int.from_bytes(data[i + 1:i + 4], "big")
        # Header records are small and non-empty; anything else means this is
        # not really an Anlogic header and the sync word was a coincidence.
        if ln == 0 or ln > 64:
            return None
        if tag == 0xF0 and idcode is None and ln >= 4:   # DEVICE_ID
            idcode = int.from_bytes(data[i + 4:i + 8], "big")
        i += 4 + ln
    if idcode is None:
        return None
    dev = EG4_IDCODES.get(idcode)
    if dev is None:
        return None
    return {"sync_off": sync_off, "verify_off": None, "idcode": idcode,
            "device": dev, "family": "anlogic"}


def parse_gowin_fs(data):
    """Detect a GOWIN `.fs` bitstream: ASCII '1'/'0', one frame per line.

    Verified against DavidClawson's GW1N-2 capture of the FNIRSI 2C53T scope,
    whose first bytes are a 160-character run of '1' then further binary-digit
    lines.  There is no binary sync word in this format, so detection is
    structural: the file must be almost entirely '0'/'1'/newline, and long
    enough to be a real fabric.

    Deliberately NOT validated further here.  Confirming a `.fs` really decodes
    means running apycula, which only imports under the oss-cad-suite
    interpreter (see scripts/gowin_unpack.py) -- so this returns a CANDIDATE and
    the decode stays where it belongs, in the tester.  Returns None unless the
    whole blob looks like one, because a `.fs` embedded at an offset inside a
    binary container has no delimiter that would let us find its bounds.
    """
    if len(data) < 4096:
        return None
    # Cheap rejection first: sample the head rather than scanning megabytes.
    head = data[:4096]
    allowed = set(b"01\r\n")
    if sum(1 for b in head if b in allowed) < len(head) * 0.99:
        return None
    # Confirm over the whole blob, and require plenty of digits.
    digits = data.count(b"0") + data.count(b"1")
    nl = data.count(b"\n")
    if digits < len(data) * 0.95 or nl < 8:
        return None
    return {"sync_off": None, "verify_off": None, "idcode": None,
            "device": "unknown (GOWIN .fs carries no device id)",
            "family": "gowin", "validated": False,
            "note": "ASCII .fs candidate; decode with scripts/gowin_unpack.py "
                    "under the oss-cad-suite interpreter to confirm"}


def ascii_header_start(data, sync_off):
    """Find the start of the ASCII comment header preceding a sync word.

    Diamond and ecppack both prefix the binary with a comment block, and its
    real shape is a run of 0xFF-PREFIXED, NUL-terminated ASCII strings:

        ff 00 "Part: LFE5U-25F-6CSFBGA285" 00 ff ff ff bd b3 ...
        ^^                                    ^^^^^ ^^^^^^^^^
        marker                                dummies  sync

    So the leading 0xFF at offset 0 is part of the header, not padding before
    it.  A backward walk that only accepts printable/NUL bytes stops one byte
    short and drops it -- which makes the carved file differ from the shipped
    one by a single byte, and that is enough to fail a byte-identical oracle
    comparison for a reason that has nothing to do with the decoder.

    Carving from the header rather than the sync word keeps the file
    byte-identical to what the vendor shipped, which matters because the oracle
    (`ecpunpack`) accepts the header and our decoder must too.  Returns
    sync_off if no header is found.
    """
    lo = max(0, sync_off - 4096)
    i = sync_off
    # Skip back over the 0xFF dummy run that separates header from sync.
    while i > lo and data[i - 1] == 0xFF:
        i -= 1
    hdr_end = i
    # Then back over printable/NUL header bytes.
    while i > lo:
        b = data[i - 1]
        if b == 0x00 or 0x20 <= b < 0x7F or b in (0x0A, 0x0D, 0x09):
            i -= 1
            continue
        break
    if hdr_end - i < 8:
        return sync_off
    # Include the 0xFF marker that introduces the header's first string.
    if i > 0 and data[i - 1] == 0xFF:
        i -= 1
    return i


_MAXSIZE_CACHE = {}


def _max_size(device):
    """Generous upper bound, in bytes, on a bitstream for `device`.

    Derived from the device's own frame geometry in Trellis devices.json --
    frames * bits_per_frame / 8 -- rather than a fixed constant, because the
    parts span 12F to 85F (and MachXO2-256 to XO3-9400), a 30x range.  Doubled
    plus a fixed slack to cover the command stream, per-frame CRCs, padding, and
    an uncompressed-with-overhead worst case.

    This is only the OUTER bound that keeps a carve from running away; the exact
    end comes from `exact_end()`, which decodes the candidate.  Too large here is
    recoverable, too small truncates a real bitstream, so it errs large.

    Falls back to MAX_PLAUSIBLE for devices not in the database (e.g. GOWIN).
    """
    if device in _MAXSIZE_CACHE:
        return _MAXSIZE_CACHE[device]
    limit = MAX_PLAUSIBLE
    try:
        import native_bitstream
        geo = native_bitstream.geometry_for(device)
        raw = geo["num_frames"] * geo["bits_per_frame"] // 8
        limit = raw * 2 + (1 << 20)
    except Exception:
        pass
    _MAXSIZE_CACHE[device] = limit
    return limit


def exact_end(data, start, cap, device):
    """Exact byte length of the bitstream at `start`, per the decoder itself.

    Returns (length, note).  `length` is None when the span cannot be decoded,
    in which case the caller keeps the generous `_max_size()` bound.

    WHY THIS IS NOT COSMETIC.  A carve bounded only by "the next bitstream or the
    device's maximum size" ends with whatever container bytes happened to follow
    -- shared-library `.rodata`, zip structures, erased flash.  Our own decoder
    never notices, because `parse()` stops at ISC_PROGRAM_DONE.  `ecpunpack` does
    not stop: it decodes to `program DONE` and then keeps reading, and dies with

        Failed to process input bitstream: unsupported command 0x00 [at 0x35297]

    So an over-long carve silently costs us CLAIM 2 -- agreement with the
    reference decoder, the only independent oracle available without source.
    Every carved Saleae bitstream failed the oracle for exactly this reason while
    decoding perfectly, which reads as a decoder problem and is not one.

    Trimming also upgrades the evidence for the carve itself.  A hit accepted on
    a sync word plus a plausible IDCODE is circumstantial; a span that parses to
    DONE with every frame consumed is a bitstream beyond argument, so the
    returned note doubles as the validation record.

    TRAILING 0xFF.  Padding after DONE is kept when the remainder of the source
    is nothing BUT padding and is short -- that is the vendor's own tail, and
    keeping it leaves a standalone `.bit` byte-identical to the shipped file.  An
    unbounded 0xFF run (erased flash) or any non-0xFF byte means foreign data, so
    the carve stops at DONE.
    """
    try:
        import native_bitstream as nb
        geom = nb.geometry_for(device)
    except Exception as exc:
        return None, f"no geometry for {device!r} ({exc})"
    span = bytes(data[start:cap])
    try:
        stripped = nb.strip_bit_header(span)
        pb = nb.parse(stripped, geom=geom)
    except Exception as exc:
        return None, f"decode failed: {exc}"
    if pb.frames_read != pb.num_frames:
        return None, (f"decoded but frames incomplete "
                      f"({pb.frames_read}/{pb.num_frames})")
    n = (len(span) - len(stripped)) + (len(stripped) - len(pb.trailer))
    tail = data[start + n:]
    if tail and len(tail) <= TAIL_PAD_MAX and set(tail) == {0xFF}:
        n += len(tail)
    return n, f"decoded to DONE, {pb.frames_read}/{pb.num_frames} frames"


def find_bitstreams(data, idcodes, log, origin="", families=ALL_FAMILIES):
    """All validated bitstreams inside `data`, any family, as carve records."""
    hits = []
    want_lattice = any(f in families for f in LATTICE_FAMILIES)
    if want_lattice:
        pos = 0
        while True:
            off = data.find(SYNC, pos)
            if off < 0:
                break
            pos = off + 1
            # Give the validator the bytes just before the sync word so it can
            # look for a MachXO part string in the ASCII header.
            hint = data[max(0, off - 512):off]
            pre = parse_preamble(data, off, idcodes, part_hint=hint)
            if pre is None or pre["family"] not in families:
                continue
            start = ascii_header_start(data, off)
            hits.append({**pre, "start": start, "origin": origin})
    if "anlogic" in families:
        pos = 0
        while True:
            off = data.find(ANLOGIC_SYNC, pos)
            if off < 0:
                break
            pos = off + 1
            pre = parse_anlogic(data, off)
            if pre is None:
                continue
            hits.append({**pre, "start": off, "origin": origin})
    if "gowin" in families:
        pre = parse_gowin_fs(data)
        if pre is not None:
            hits.append({**pre, "start": 0, "origin": origin})
    # Bitstreams are carved to the next bitstream start, or to EOF for the last
    # one -- but CAPPED at a generous upper bound on the real bitstream size for
    # the detected device.
    #
    # The cap matters when a bitstream is embedded in something much larger.  A
    # Saleae bitstream sits in the `.rodata` of a 30 MB shared library, so
    # "to EOF" carved 29 MB of unrelated library for one 45F design.  OUR
    # decoding survives that (parse() stops at DONE, so trailing bytes are never
    # read) but `ecpunpack` does not, so an over-carve silently costs the oracle
    # -- see exact_end(), which decodes each span and trims it to its true end.
    for n, h in enumerate(hits):
        nxt = hits[n + 1]["start"] if n + 1 < len(hits) else len(data)
        h["end"] = min(nxt, h["start"] + _max_size(h.get("device")))
        if h["family"] in LATTICE_FAMILIES:
            exact, note = exact_end(data, h["start"], h["end"], h.get("device"))
            h["validated"] = note
            if exact is not None and exact < h["end"] - h["start"]:
                log.info("  trim %s+0x%x %s: %d -> %d bytes (%s)", origin,
                         h["start"], h["device"], h["end"] - h["start"], exact,
                         note)
                h["end"] = h["start"] + exact
            elif exact is None:
                log.info("  no exact end for %s+0x%x %s: %s -- keeping the "
                         "%d-byte bound", origin, h["start"], h["device"], note,
                         h["end"] - h["start"])
        h["length"] = h["end"] - h["start"]
    kept = [h for h in hits if h["length"] >= MIN_CARVE]
    for h in hits:
        if h["length"] < MIN_CARVE:
            # sync_off is None for the families with no sync word (GOWIN .fs),
            # so it is formatted as a string rather than hex.
            log.info("  reject %s at %s: %s but only %d bytes", origin,
                     h["sync_off"], h["device"], h["length"])
    return kept


# ---------------------------------------------------------------------------
# container unwrapping
# ---------------------------------------------------------------------------

def _squashfs_members(data, name, log):
    """Yield members of a squashfs image, via unsquashfs.

    AppImages (Saleae Logic 2 among them) are an ELF stub followed by a
    COMPRESSED squashfs.  So the payload bytes are not present verbatim anywhere
    in the outer file -- scanning it finds literally zero bitstream sync words
    even when the filesystem inside holds ten of them.  Unpacking is the only
    way in, and it needs an external tool because squashfs is not in the Python
    standard library.

    Returns nothing (with a log line) when unsquashfs is unavailable, rather
    than failing: the rest of the carve is still valid.

    FINDING THE SUPERBLOCK.  Searching for the `hsqs` magic does NOT work: in
    the Saleae AppImage the first `hsqs` hit is at 32609, an incidental string
    inside the ELF stub, and unsquashfs rejects it ("Can't find a valid SQUASHFS
    superblock").  The real superblock is at 188392, which is exactly where the
    ELF image ends (e_shoff + e_shentsize * e_shnum).  So the offset is COMPUTED
    from the ELF section table, and magic hits are only tried as a fallback for
    non-ELF-wrapped images.
    """
    tool = shutil.which("unsquashfs")
    if tool is None:
        log.info("  %s: squashfs found but unsquashfs is not installed; "
                 "cannot look inside", name)
        return
    offsets = []
    if data[:4] == b"\x7fELF" and len(data) > 0x40:
        try:
            e_shoff = int.from_bytes(data[0x28:0x30], "little")
            e_shentsize = int.from_bytes(data[0x3A:0x3C], "little")
            e_shnum = int.from_bytes(data[0x3C:0x3E], "little")
            end = e_shoff + e_shentsize * e_shnum
            if 0 < end < len(data):
                offsets.append(end)
        except Exception:
            pass
    pos = 0
    while len(offsets) < 8:
        o = data.find(b"hsqs", pos)
        if o < 0:
            break
        offsets.append(o)
        pos = o + 1
    if not offsets:
        return
    import tempfile
    with tempfile.TemporaryDirectory(dir=os.path.join(REPO, "tmp")) as td:
        img = os.path.join(td, "fs.squashfs")
        dest = os.path.join(td, "root")
        used = None
        for off in offsets:
            with open(img, "wb") as fh:
                fh.write(data[off:])
            probe = subprocess.run([tool, "-s", img], capture_output=True,
                                   text=True)
            if "valid SQUASHFS" not in probe.stdout:
                continue
            used = off
            break
        if used is None:
            log.info("  %s: no valid squashfs superblock at any of %s",
                     name, offsets[:4])
            return
        log.info("  %s: squashfs superblock at %d, unpacking", name, used)
        r = subprocess.run([tool, "-no-progress", "-force", "-dest", dest, img],
                           capture_output=True, text=True)
        if not os.path.isdir(dest):
            log.info("  %s: unsquashfs produced nothing (%s)", name,
                     (r.stderr or r.stdout)[-200:].strip())
            return
        # Only yield files big enough to hold a bitstream; an AppImage has
        # thousands of small assets and reading them all is pure overhead.
        for root, _d, files in os.walk(dest):
            for f in sorted(files):
                p = os.path.join(root, f)
                try:
                    if os.path.getsize(p) < MIN_CARVE or os.path.islink(p):
                        continue
                    with open(p, "rb") as fh:
                        yield f"{name}!{os.path.relpath(p, dest)}", fh.read()
                except OSError:
                    continue


def _members(data, name, log):
    """Yield (member_name, bytes) for a container, or nothing if not one."""
    # squashfs / AppImage.  Checked before the archive formats because an
    # AppImage's leading ELF stub means none of their magics match anyway.
    if b"hsqs" in data[:1 << 20]:
        yield from _squashfs_members(data, name, log)
        return
    # zip
    if data[:2] in (b"PK",):
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except Exception as exc:
            log.info("  %s: looks like zip but will not open (%s)", name, exc)
            return
        for info in zf.infolist():
            if info.is_dir() or info.file_size > MAX_MEMBER:
                continue
            try:
                yield f"{name}!{info.filename}", zf.read(info)
            except Exception as exc:
                log.info("  %s!%s: unreadable (%s)", name, info.filename, exc)
        return
    # single-stream compressors
    for magic, opener, label in (
            (b"\x1f\x8b", gzip.decompress, "gzip"),
            (b"BZh", bz2.decompress, "bzip2"),
            (b"\xfd7zXZ", lzma.decompress, "xz")):
        if data.startswith(magic):
            try:
                inner = opener(data)
            except Exception as exc:
                log.info("  %s: %s failed (%s)", name, label, exc)
                return
            yield f"{name}!{label}", inner
            return
    # tar (checked last: no strong leading magic)
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data))
    except Exception:
        return
    for m in tf.getmembers():
        if not m.isfile() or m.size > MAX_MEMBER:
            continue
        fh = tf.extractfile(m)
        if fh is None:
            continue
        yield f"{name}!{m.name}", fh.read()


def scan_blob(data, name, idcodes, log, depth=0, families=ALL_FAMILIES):
    """Carve records from `data` and, recursively, from anything inside it."""
    found = find_bitstreams(data, idcodes, log, origin=name, families=families)
    # Part strings, per family.  Reported even when nothing validates: a blob
    # naming an FPGA part but carrying no parseable preamble is itself the
    # finding (packed, encrypted, or split across records), and it is what
    # tells a reader to go looking rather than assume the family is absent.
    parts = {}
    for fam in families:
        rx = PART_RES.get(fam)
        if rx is None:
            continue
        hits = sorted(set(m.decode("latin-1") for m in rx.findall(data)))
        if hits:
            parts[fam] = hits
    if parts and not found:
        log.info("  %s: part string(s) %s present but no valid bitstream "
                 "preamble -- packed, encrypted, or split", name, parts)
    for rec in found:
        rec["part_strings"] = parts
        # Carry the carved bytes with the record.  The alternative -- re-walking
        # the container to fetch them later -- means re-running unsquashfs once
        # per hit, and an AppImage with ten bitstreams would unpack a 154 MB
        # filesystem ten times.
        rec["_payload"] = data[rec["start"]:rec["end"]]
    if depth >= MAX_DEPTH:
        return found
    for rec in found:
        rec["depth"] = depth
    for mname, mdata in _members(data, name, log):
        found.extend(scan_blob(mdata, mname, idcodes, log, depth + 1,
                               families=families))
    return found


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def dedupe(recs, log):
    """Collapse the same bitstream seen at several nesting depths.

    A zip member STORED without compression appears verbatim in the outer
    container's bytes, so the identical design validates once inside the member
    and again in the enclosing blob -- and the outer copy is truncated at the
    next zip structure, giving a slightly different length each time.  Reporting
    all of them would inflate the corpus with partial duplicates of one design.

    The deepest extraction is the correct one: it has been fully unwrapped, so
    its bytes are the member as the vendor stored it, not a fragment of a
    container.  Keep the deepest; when depths tie, keep the longest.

    Duplicates are matched by CONTENT, not by device.  Grouping by
    (family, device, IDCODE) collapsed the ten distinct Saleae bitstreams inside
    one shared library down to two, because several of them target the same part
    -- ten designs sitting side by side in one `.rodata` are ten designs, not one
    seen ten times.  So a record is only a duplicate of another if their carved
    bytes actually coincide: same SHA-256, or one is a prefix of the other (which
    is what a stored-uncompressed zip member looks like from the enclosing blob).
    """
    if len(recs) <= 1:
        return recs
    # Deepest first, then longest: the survivor of any pair is the one we keep.
    order = sorted(recs, key=lambda r: (-r.get("depth", 0), -r["length"]))
    kept = []
    for r in order:
        pay = r.get("_payload") or b""
        dup_of = None
        for k in kept:
            kpay = k.get("_payload") or b""
            if not pay or not kpay:
                continue
            if pay == kpay or kpay.startswith(pay) or pay.startswith(kpay):
                dup_of = k
                break
        if dup_of is None:
            kept.append(r)
        else:
            log.info("  dedupe: dropping %s (depth %d, %d bytes) -- content "
                     "already covered by %s (depth %d, %d bytes)",
                     r["origin"], r.get("depth", 0), r["length"],
                     dup_of["origin"], dup_of.get("depth", 0),
                     dup_of["length"])
    return kept


def carve_file(path, outdir, idcodes, log, families=ALL_FAMILIES):
    log.info("scanning %s (%d bytes)", path, os.path.getsize(path))
    with open(path, "rb") as fh:
        data = fh.read()
    recs = scan_blob(data, os.path.basename(path), idcodes, log,
                     families=families)
    recs = dedupe(recs, log)
    out = []
    for n, rec in enumerate(recs):
        payload = rec.pop("_payload", None)
        if payload is None:
            log.info("  no payload captured for %s, skipping", rec["origin"])
            continue
        sha = hashlib.sha256(payload).hexdigest()
        safe = re.sub(r"[^0-9A-Za-z._-]+", "_", rec["origin"])[-80:]
        fname = f"{safe}.{rec['family']}.{rec['device']}.{sha[:8]}.bit"
        dest = os.path.join(outdir, fname)
        with open(dest, "wb") as fh:
            fh.write(payload)
        rec.update({"sha256": sha, "bytes": len(payload),
                    "local": os.path.relpath(dest, REPO),
                    "source_file": os.path.relpath(path, REPO)})
        log.info("  CARVED %s/%s %s -> %s (%d bytes, sha %s)",
                 rec["family"], rec["device"], rec["origin"], fname,
                 len(payload), sha[:12])
        out.append(rec)
    if not recs:
        log.info("  no bitstream found in %s", path)
    # Belt and braces: raw bytes must never reach the JSON manifest.
    for rec in out:
        rec.pop("_payload", None)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="firmware file(s) or directory")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="where carved .bit files go (gitignored)")
    ap.add_argument("--json", default=os.path.join(REPO, "tmp",
                                                   "ecp5_carve.json"))
    ap.add_argument("--families", default=",".join(ALL_FAMILIES),
                    help="comma-separated subset of: " + ",".join(ALL_FAMILIES))
    args = ap.parse_args()
    log = setup_logging("ecp5_carve")

    families = tuple(f.strip().lower() for f in args.families.split(",")
                     if f.strip())
    bad = [f for f in families if f not in ALL_FAMILIES]
    if bad:
        sys.exit(f"unknown family/families {bad}; known: {list(ALL_FAMILIES)}")

    os.makedirs(args.out, exist_ok=True)
    idcodes = _ecp5_idcodes(_idcode_table())
    log.info("families: %s", ",".join(families))
    log.info("%d known ECP5 IDCODEs", len(idcodes))

    files = []
    for inp in args.inputs:
        if os.path.isdir(inp):
            for root, _d, fs in os.walk(inp):
                files.extend(os.path.join(root, f) for f in sorted(fs))
        else:
            files.append(inp)

    recs = []
    for path in files:
        try:
            recs.extend(carve_file(path, args.out, idcodes, log,
                                   families=families))
        except Exception as exc:
            log.error("  %s: %s", path, exc)

    with open(args.json, "w") as fh:
        json.dump(recs, fh, indent=2, sort_keys=True)
    log.info("carved %d bitstream(s) from %d file(s) -> %s",
             len(recs), len(files), args.json)
    by_dev = {}
    for r in recs:
        key = f"{r['family']}/{r['device']}"
        by_dev[key] = by_dev.get(key, 0) + 1
    for dev, n in sorted(by_dev.items()):
        log.info("  %s: %d", dev, n)


if __name__ == "__main__":
    main()
