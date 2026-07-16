#!/usr/bin/env python3
"""Pure-Python MachXO2 bitstream parser (pluribus issue P2).

Decodes a MachXO2 `.bit`/`.bin` into the CRAM frame bit-matrix, byte-faithful
to prjtrellis `libtrellis/src/Bitstream.cpp::deserialise_chip`.  Handles both
compressed (vendor, `LSC_PROG_INCR_CMP`) and uncompressed (fuzz,
`LSC_PROG_INCR_RTI`) streams, plus `WRITE_INC_FRAME` (inverted data).

Design rules (match the C++ exactly, no silent truncation):
  * CRC16 poly 0x8005, init 0x0000, MSB-first, finalised by pushing 16 zero
    bits — identical to `BitstreamReadWriter::update_crc16/finalise_crc16`.
  * The command opcode byte is folded into CRC unless it is DUMMY (0xFF).
  * An unknown command is a loud RuntimeError, never a truncation.
  * `frames_read` is tracked and asserted against the device frame count.
  * The final-frame CRC (once-at-end) must verify or we die.

The undocumented `0x72` EFB config-preload command is handled per
`docs/cmd-0x72.md`: total = 4 + info[2] bytes, folded into CRC, no embedded CRC.

CRAM layout matches pytrellis: `cram[idx][j]`, idx = frame index (MachXO2 is
NOT reversed), j in [0, bits_per_frame).
"""
import argparse

PREAMBLE = bytes([0xFF, 0xFF, 0xBD, 0xB3])
CRC16_POLY = 0x8005
CRC16_INIT = 0x0000

# Command opcodes (from prjtrellis BitstreamCommand enum + the RE'd 0x72).
DUMMY = 0xFF
LSC_RESET_CRC = 0x3B
VERIFY_ID = 0xE2
LSC_PROG_CNTRL0 = 0x22
LSC_PROG_CNTRL1 = 0x23
LSC_PROG_CNTRL0_2 = 0xC4
ISC_PROGRAM_DONE = 0x5E
ISC_PROGRAM_DONE_2 = 0x7A
ISC_PROGRAM_SECURITY = 0xCE
ISC_PROGRAM_USERCODE = 0xC2
ISC_PROGRAM_USERCODE_2 = 0xC3
LSC_WRITE_COMP_DIC = 0x02
LSC_INIT_ADDRESS = 0x46
LSC_WRITE_ADDRESS = 0xB4
LSC_PROG_INCR_CMP = 0xB8
LSC_PROG_INCR_RTI = 0x82
WRITE_INC_FRAME = 0x41
LSC_EBR_ADDRESS = 0xF6
LSC_EBR_WRITE = 0xB2
SPI_MODE = 0x79
JUMP = 0x7E
LSC_PROG_SED_CRC = 0xA2
CMD_0x72 = 0x72

CMD_NAME = {
    DUMMY: "DUMMY", LSC_RESET_CRC: "LSC_RESET_CRC", VERIFY_ID: "VERIFY_ID",
    LSC_PROG_CNTRL0: "LSC_PROG_CNTRL0", LSC_PROG_CNTRL1: "LSC_PROG_CNTRL1",
    LSC_PROG_CNTRL0_2: "LSC_PROG_CNTRL0_2", ISC_PROGRAM_DONE: "ISC_PROGRAM_DONE",
    ISC_PROGRAM_DONE_2: "ISC_PROGRAM_DONE_2", ISC_PROGRAM_SECURITY: "ISC_PROGRAM_SECURITY",
    ISC_PROGRAM_USERCODE: "ISC_PROGRAM_USERCODE", ISC_PROGRAM_USERCODE_2: "ISC_PROGRAM_USERCODE_2",
    LSC_WRITE_COMP_DIC: "LSC_WRITE_COMP_DIC", LSC_INIT_ADDRESS: "LSC_INIT_ADDRESS",
    LSC_WRITE_ADDRESS: "LSC_WRITE_ADDRESS", LSC_PROG_INCR_CMP: "LSC_PROG_INCR_CMP",
    LSC_PROG_INCR_RTI: "LSC_PROG_INCR_RTI", WRITE_INC_FRAME: "WRITE_INC_FRAME",
    LSC_EBR_ADDRESS: "LSC_EBR_ADDRESS", LSC_EBR_WRITE: "LSC_EBR_WRITE",
    SPI_MODE: "SPI_MODE", JUMP: "JUMP", LSC_PROG_SED_CRC: "LSC_PROG_SED_CRC",
    CMD_0x72: "CMD_0x72",
}

# LCMXO2-1200 geometry (only device needed for now; generalise later).
MACHXO2_1200 = dict(
    idcode=0x012ba043, name="LCMXO2-1200",
    num_frames=333, bits_per_frame=1080,
    pad_bits_after_frame=0, pad_bits_before_frame=0,
    reversed_frames=False, one_hot_dictionary=False,
)


class ParseError(RuntimeError):
    pass


class BitstreamReader:
    """Byte reader with a running CRC16, mirroring BitstreamReadWriter."""

    def __init__(self, data):
        self.d = data
        self.i = 0
        self.crc16 = CRC16_INIT

    # --- CRC ---------------------------------------------------------------
    def update_crc16(self, val):
        crc = self.crc16
        for k in range(7, -1, -1):
            bit_flag = crc >> 15
            crc = ((crc << 1) & 0xFFFF) | ((val >> k) & 1)
            if bit_flag:
                crc ^= CRC16_POLY
        self.crc16 = crc & 0xFFFF

    def finalise_crc16(self):
        crc = self.crc16
        for _ in range(16):
            bit_flag = crc >> 15
            crc = (crc << 1) & 0xFFFF
            if bit_flag:
                crc ^= CRC16_POLY
        self.crc16 = crc & 0xFFFF
        return self.crc16

    def reset_crc16(self):
        self.crc16 = CRC16_INIT

    # --- byte access -------------------------------------------------------
    def get_byte(self):
        if self.i >= len(self.d):
            raise ParseError(f"read past end of stream at offset {self.i}")
        v = self.d[self.i]
        self.i += 1
        self.update_crc16(v)
        return v

    def get_command_opcode(self):
        if self.i >= len(self.d):
            raise ParseError(f"read past end of stream at offset {self.i}")
        v = self.d[self.i]
        self.i += 1
        if v != DUMMY:
            self.update_crc16(v)
        return v

    def get_bytes(self, count):
        return bytes(self.get_byte() for _ in range(count))

    def skip_bytes(self, count):
        for _ in range(count):
            self.get_byte()

    def get_uint32(self):
        b = self.get_bytes(4)
        return (b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]

    def check_crc16(self):
        actual = self.finalise_crc16()
        hi = self.get_byte()
        lo = self.get_byte()
        expected = (hi << 8) | lo
        self.reset_crc16()
        if actual != expected:
            raise ParseError(
                f"crc fail at offset {self.i}: calculated 0x{actual:04x} "
                f"but expecting 0x{expected:04x}")
        return actual

    def find_preamble(self):
        idx = self.d.find(PREAMBLE, self.i)
        if idx < 0:
            return False
        self.i = idx + len(PREAMBLE)
        return True

    def is_end(self):
        return self.i >= len(self.d)

    # --- compressed byte decoder (port of get_compressed_bytes) ------------
    def get_compressed_bytes(self, count, comp_dict):
        out = bytearray(count)
        read_data = 0
        remaining_bits = 0
        for n in range(count):
            if remaining_bits == 0:
                read_data = self.get_byte()
                remaining_bits = 8
            next_bit = (read_data >> (remaining_bits - 1)) & 1
            remaining_bits -= 1
            if next_bit:
                if remaining_bits < 5:
                    read_data = (read_data << 8) | self.get_byte()
                    remaining_bits += 8
                next_bit = (read_data >> (remaining_bits - 1)) & 1
                remaining_bits -= 1
                if next_bit:
                    # 11 xxxxxxxx -> literal byte
                    if remaining_bits < 8:
                        read_data = (read_data << 8) | self.get_byte()
                        remaining_bits += 8
                    udata = (read_data >> (remaining_bits - 8)) & 0xFF
                    remaining_bits -= 8
                else:
                    # 10 ?xxx -> onehot (idx 0..7) or dict (idx 8..15)
                    idx = (read_data >> (remaining_bits - 4)) & 0xF
                    remaining_bits -= 4
                    udata = comp_dict[idx]
            else:
                udata = 0
            out[n] = udata
        return out


def strip_bit_header(raw):
    """Return the raw command stream: strip the .bit ASCII header if present.

    A vendor `.bin` starts directly at the preamble; a Diamond `.bit` has an
    'FF 00 <metadata...> FF' (optionally LSCC-prefixed) header.  We only strip
    when a header is actually present, otherwise pass the bytes through.
    """
    if raw[0:4] == PREAMBLE:
        return raw  # bare command stream (.bin)
    i = 0
    if raw[0:4] == b'LSCC':
        i = 4
    if not (raw[i] == 0xFF and raw[i + 1] == 0x00):
        # No recognised header and not a bare preamble: hand back as-is and
        # let find_preamble locate the start (loud failure if absent).
        return raw
    i += 2
    while raw[i] != 0xFF:
        i += 1
    i += 1  # consume terminating FF
    return raw[i:]


class ParsedBitstream:
    def __init__(self, geom):
        self.geom = geom
        self.num_frames = geom["num_frames"]
        self.bits_per_frame = geom["bits_per_frame"]
        # cram[idx] is a bytearray of bits_per_frame 0/1 values.
        self.cram = [bytearray(self.bits_per_frame) for _ in range(self.num_frames)]
        self.frames_read = 0
        self.idcode = None
        self.usercode = None
        self.ctrl0 = None
        self.commands = []          # (offset, opcode, name, info)
        self.efb_blocks = []        # (offset, flags, sel, payload)
        self.frame_block_end = None  # byte offset (in stream) after last frame block
        self.crc_verified = False
        # --- re-encode skeleton (issue #34) --------------------------------
        # Enough structure to losslessly re-serialise the exact byte stream.
        # `header`  : original bytes before the command stream (.bit header, or
        #             b"" for a bare .bin).
        # `pre`     : command-stream bytes up to and including the preamble.
        # `records` : ordered list of command records (see parse()).
        # `trailer` : bytes after the terminating DONE command.
        self.header = b""
        self.pre = b""
        self.records = []
        self.trailer = b""

    def bit(self, frame, j):
        return self.cram[frame][j]


def _store_frame(pb, idx, frame_bytes, bytes_per_frame, pad_after, invert=False):
    row = pb.cram[idx]
    for j in range(pb.bits_per_frame):
        ofs = j + pad_after
        b = (frame_bytes[(bytes_per_frame - 1) - (ofs >> 3)] >> (ofs & 7)) & 1
        row[j] = b ^ 1 if invert else b


def parse(data, geom=MACHXO2_1200, verbose=False):
    """Parse a header-stripped command stream into a ParsedBitstream."""
    rd = BitstreamReader(data)
    if not rd.find_preamble():
        raise ParseError("preamble not found in bitstream")

    pb = ParsedBitstream(geom)
    pb.pre = bytes(data[:rd.i])   # leading bytes + preamble (consumed above)
    comp_dict = None
    no_id_mode = False
    cfg0 = 0

    def log(off, op, info=""):
        name = CMD_NAME.get(op, f"UNKNOWN_0x{op:02x}")
        pb.commands.append((off, op, name, info))
        if verbose:
            print(f"0x{off:06x}  0x{op:02x} {name:22s} {info}")

    def rec(kind, **kw):
        # Append a re-encode record.  DUMMY runs are coalesced.
        if kind == "DUMMY" and pb.records and pb.records[-1][0] == "DUMMY":
            pb.records[-1][1]["count"] += kw["count"]
            return
        pb.records.append((kind, dict(kw)))

    def raw_span(off):
        # Bytes from the opcode at `off` up to the current position.
        return bytes(data[off:rd.i])

    while not rd.is_end():
        off = rd.i
        cmd = rd.get_command_opcode()

        if cmd == DUMMY:
            rec("DUMMY", count=1)
            continue

        elif cmd == LSC_RESET_CRC:
            rd.skip_bytes(3)
            rd.reset_crc16()
            rec("RAW_RESET", raw=raw_span(off))
            log(off, cmd)

        elif cmd == VERIFY_ID:
            rd.skip_bytes(3)
            if no_id_mode:
                rd.reset_crc16()
                rec("RAW_RESET", raw=raw_span(off))
                log(off, cmd, "reset-address (no_id_mode)")
            else:
                pb.idcode = rd.get_uint32()
                rec("RAW", raw=raw_span(off))
                log(off, cmd, f"id=0x{pb.idcode:08x}")

        elif cmd == LSC_PROG_CNTRL0_2:
            no_id_mode = True
            rd.skip_bytes(3)
            cfg0 = rd.get_uint32()
            rec("RAW", raw=raw_span(off))
            log(off, cmd, f"cfg0=0x{cfg0:08x}")

        elif cmd == LSC_PROG_CNTRL0:
            rd.skip_bytes(3)
            pb.ctrl0 = rd.get_uint32()
            rec("RAW", raw=raw_span(off))
            log(off, cmd, f"ctrl0=0x{pb.ctrl0:08x}")

        elif cmd == LSC_PROG_CNTRL1:
            rd.skip_bytes(3)
            cfg = rd.get_uint32()
            rec("RAW", raw=raw_span(off))
            log(off, cmd, f"ctrl1=0x{cfg:08x}")

        elif cmd in (ISC_PROGRAM_DONE, ISC_PROGRAM_DONE_2):
            flags = rd.get_byte()
            check_crc = (flags & 0x80) != 0
            skip2 = bytes(rd.get_bytes(2))
            if check_crc:
                rd.check_crc16()
            rec("DONE", opcode=cmd, flags=flags, skip2=skip2, check_crc=check_crc)
            log(off, cmd, "DONE")
            break  # end of stream

        elif cmd == ISC_PROGRAM_SECURITY:
            rd.skip_bytes(3)
            rec("RAW", raw=raw_span(off))
            log(off, cmd)

        elif cmd in (ISC_PROGRAM_USERCODE, ISC_PROGRAM_USERCODE_2):
            flags = rd.get_byte()
            check_crc = (flags & 0x80) != 0
            skip2 = bytes(rd.get_bytes(2))
            pb.usercode = rd.get_uint32()
            info = f"usercode=0x{pb.usercode:08x}"
            if check_crc:
                rd.check_crc16()
                info += " crc OK"
            rd.reset_crc16()
            rec("USERCODE", opcode=cmd, flags=flags, skip2=skip2,
                usercode=pb.usercode, check_crc=check_crc)
            log(off, cmd, info)

        elif cmd == LSC_WRITE_COMP_DIC:
            flags = rd.get_byte()
            check_crc = (flags & 0x80) != 0
            skip2 = bytes(rd.get_bytes(2))
            comp_dict = [0] * 16
            if geom["one_hot_dictionary"]:
                for k in range(15, -1, -1):
                    comp_dict[k] = rd.get_byte()
            else:
                for k in range(7, -1, -1):
                    comp_dict[k] = 1 << k
                    comp_dict[8 + k] = rd.get_byte()
            if check_crc:
                rd.check_crc16()
            rec("DICT", flags=flags, skip2=skip2, check_crc=check_crc,
                one_hot=geom["one_hot_dictionary"],
                dict_bytes=bytes(comp_dict[8:16]))
            log(off, cmd, "dict=" + " ".join(f"{b:02x}" for b in comp_dict[8:16]))

        elif cmd == LSC_INIT_ADDRESS:
            rd.skip_bytes(3)
            rec("RAW", raw=raw_span(off))
            log(off, cmd)

        elif cmd in (LSC_PROG_INCR_CMP, LSC_PROG_INCR_RTI):
            if cmd == LSC_PROG_INCR_CMP and comp_dict is None:
                raise ParseError(
                    "compressed frame block before compression dictionary")
            params = rd.get_bytes(3)
            check_crc = bool(params[0] & 0x80)
            crc_after_each_frame = check_crc and not (params[0] & 0x40)
            dummy_bytes = params[0] & 0x0F
            frame_count = (params[1] << 8) | params[2]
            bpf = (pb.bits_per_frame + geom["pad_bits_after_frame"]
                   + geom["pad_bits_before_frame"]) // 8
            if cmd == LSC_PROG_INCR_CMP:
                bpf += (7 - ((bpf - 1) % 8))  # 64-bit pad on compressed frames
            for i in range(frame_count):
                idx = (pb.num_frames - 1 - i) if geom["reversed_frames"] else i
                if cmd == LSC_PROG_INCR_CMP:
                    fb = rd.get_compressed_bytes(bpf, comp_dict)
                else:
                    fb = rd.get_bytes(bpf)
                _store_frame(pb, idx, fb, bpf, geom["pad_bits_after_frame"])
                pb.frames_read += 1
                if crc_after_each_frame or (check_crc and i == frame_count - 1):
                    rd.check_crc16()
                    pb.crc_verified = True
                rd.skip_bytes(dummy_bytes)
            pb.frame_block_end = rd.i
            rec("FRAMES", opcode=cmd, params=bytes(params),
                compressed=(cmd == LSC_PROG_INCR_CMP),
                frame_count=frame_count, inverted=False)
            log(off, cmd, f"params={params[0]:02x} frames={frame_count} "
                          f"dummy={dummy_bytes} bpf={bpf}")

        elif cmd == WRITE_INC_FRAME:
            params = rd.get_bytes(3)
            check_crc = bool(params[0] & 0x80)
            crc_after_each_frame = check_crc and not (params[0] & 0x40)
            dummy_bytes = 4
            frame_count = (params[1] << 8) | params[2]
            bpf = (pb.bits_per_frame + geom["pad_bits_after_frame"]
                   + geom["pad_bits_before_frame"]) // 8
            for i in range(frame_count):
                idx = (pb.num_frames - 1 - i) if geom["reversed_frames"] else i
                fb = rd.get_bytes(bpf)
                _store_frame(pb, idx, fb, bpf, geom["pad_bits_after_frame"],
                             invert=True)
                pb.frames_read += 1
                if crc_after_each_frame or (check_crc and i == frame_count - 1):
                    rd.check_crc16()
                    pb.crc_verified = True
                rd.skip_bytes(dummy_bytes)
            end_fuse = bytes(rd.get_bytes(20))  # End Fuse Data Frame
            rd.check_crc16()
            pb.frame_block_end = rd.i
            rec("FRAMES", opcode=cmd, params=bytes(params),
                compressed=False, frame_count=frame_count, inverted=True,
                dummy_bytes=dummy_bytes, end_fuse=end_fuse)
            log(off, cmd, f"params={params[0]:02x} frames={frame_count} (inverted)")

        elif cmd == LSC_EBR_ADDRESS:
            rd.skip_bytes(3)
            addr = rd.get_uint32()
            rec("RAW", raw=raw_span(off))
            log(off, cmd, f"ebr_addr=0x{addr:08x}")

        elif cmd == LSC_EBR_WRITE:
            params = rd.get_bytes(3)
            check_crc = bool(params[0] & 0x80)
            frame_count = (params[1] << 8) | params[2]
            ebr_words = []
            for _ in range(frame_count):
                fr = rd.get_bytes(9)
                ebr_words.append((
                    (fr[0] << 1) | (fr[1] >> 7),
                    ((fr[1] & 0x7F) << 2) | (fr[2] >> 6),
                    ((fr[2] & 0x3F) << 3) | (fr[3] >> 5),
                    ((fr[3] & 0x1F) << 4) | (fr[4] >> 4),
                    ((fr[4] & 0x0F) << 5) | (fr[5] >> 3),
                    ((fr[5] & 0x07) << 6) | (fr[6] >> 2),
                    ((fr[6] & 0x03) << 7) | (fr[7] >> 1),
                    ((fr[7] & 0x01) << 8) | fr[8],
                ))
            if check_crc:
                rd.check_crc16()
            rec("EBR_WRITE", params=bytes(params), check_crc=check_crc,
                words=ebr_words)
            log(off, cmd, f"ebr_frames={frame_count}")

        elif cmd == SPI_MODE:
            rd.get_byte()
            rd.skip_bytes(2)
            rec("RAW", raw=raw_span(off))
            log(off, cmd)

        elif cmd == JUMP:
            rd.skip_bytes(3)
            rd.skip_bytes(4)
            rec("RAW", raw=raw_span(off))
            log(off, cmd)

        elif cmd == LSC_PROG_SED_CRC:
            rd.skip_bytes(3)
            cfg = rd.get_uint32()
            rec("RAW", raw=raw_span(off))
            log(off, cmd, f"sed=0x{cfg:08x}")

        elif cmd == CMD_0x72:
            # EFB feature/config-register preload (undocumented). See
            # docs/cmd-0x72.md.  total = 4 + info[2]; folded into CRC; no
            # embedded CRC (info0 MSB clear).  May repeat; the loop re-enters.
            flags = rd.get_byte()
            sel = rd.get_byte()
            length = rd.get_byte()
            if flags & 0x80:
                raise ParseError(
                    f"0x72 block at 0x{off:x} has CRC-follows flag set "
                    f"(flags=0x{flags:02x}); unmodelled")
            payload = rd.get_bytes(length)
            pb.efb_blocks.append((off, flags, sel, bytes(payload)))
            rec("EFB", flags=flags, sel=sel, payload=bytes(payload))
            log(off, cmd, f"efb sel=0x{sel:02x} len={length} "
                          f"payload={' '.join(f'{b:02x}' for b in payload)}")

        else:
            raise ParseError(
                f"unsupported command 0x{cmd:02x} at offset 0x{off:x}")

    pb.trailer = bytes(data[rd.i:])
    return pb


def parse_file(path, geom=MACHXO2_1200, verbose=False):
    raw = open(path, "rb").read()
    data = strip_bit_header(raw)
    pb = parse(data, geom=geom, verbose=verbose)
    pb.header = bytes(raw[:len(raw) - len(data)])  # .bit header, or b"" for .bin
    return pb


# ===========================================================================
# ENCODER  (config -> bitstream, the inverse of parse) -- pluribus issue #34
# ===========================================================================
#
# Ported from prjtrellis libtrellis/src/Bitstream.cpp writer functions
# (serialise_chip / write_compressed_frames / insert_crc16).  The parser stores
# an ordered `records` skeleton plus the decoded CRAM/EFB/EBR/registers; the
# encoder replays that skeleton, REGENERATING every config-bearing payload from
# the decoded structures (config frames from `pb.cram`, EFB blocks from the
# 0x72 records, EBR words re-packed from the decoded 9-bit words) and RECOMPUTING
# every CRC16 with the same engine/reset points as the reader.  Pure structural
# scaffolding (the .bit header, preamble, dummy 0xFF runs, fixed zero fills, and
# scalar register operands) is replayed verbatim -- it carries no config.
#
# Because the writer mirrors the reader's CRC state transitions byte-for-byte,
# the recomputed CRCs equal the originals whenever the regenerated payloads do,
# so an exact round-trip is a genuine proof the decode captured every bit.


def _decode_onehot(b):
    """Index of the single set bit (0=lsb..7=msb), or -1 if not a power of two."""
    for k in range(8):
        if b == (1 << k):
            return k
    return -1


class BitstreamWriter:
    """Byte writer with a running CRC16, mirroring BitstreamReadWriter."""

    def __init__(self):
        self.out = bytearray()
        self.crc16 = CRC16_INIT

    def update_crc16(self, val):
        crc = self.crc16
        for k in range(7, -1, -1):
            bit_flag = crc >> 15
            crc = ((crc << 1) & 0xFFFF) | ((val >> k) & 1)
            if bit_flag:
                crc ^= CRC16_POLY
        self.crc16 = crc & 0xFFFF

    def finalise_crc16(self):
        crc = self.crc16
        for _ in range(16):
            bit_flag = crc >> 15
            crc = (crc << 1) & 0xFFFF
            if bit_flag:
                crc ^= CRC16_POLY
        self.crc16 = crc & 0xFFFF
        return self.crc16

    def reset_crc16(self):
        self.crc16 = CRC16_INIT

    def write_raw(self, bs):
        """Append bytes WITHOUT touching CRC (header / preamble / dummies)."""
        self.out += bytes(bs)

    def write_byte(self, b):
        self.out.append(b & 0xFF)
        self.update_crc16(b & 0xFF)

    def write_bytes(self, bs):
        for b in bs:
            self.write_byte(b)

    def write_uint32(self, v):
        self.write_byte((v >> 24) & 0xFF)
        self.write_byte((v >> 16) & 0xFF)
        self.write_byte((v >> 8) & 0xFF)
        self.write_byte(v & 0xFF)

    def insert_crc16(self):
        """Finalise CRC, emit the 2 CRC bytes (updating CRC), then reset."""
        crc = self.finalise_crc16()
        self.write_byte((crc >> 8) & 0xFF)
        self.write_byte(crc & 0xFF)
        self.reset_crc16()


def _cram_to_frames(pb, geom, invert=False):
    """Re-assemble uncompressed frame byte-rows from the decoded CRAM."""
    pad_after = geom["pad_bits_after_frame"]
    pad_before = geom["pad_bits_before_frame"]
    bpf = (pb.bits_per_frame + pad_after + pad_before) // 8
    frames = []
    for i in range(pb.num_frames):
        idx = (pb.num_frames - 1 - i) if geom["reversed_frames"] else i
        fb = bytearray(bpf)
        row = pb.cram[idx]
        for j in range(pb.bits_per_frame):
            ofs = j + pad_after
            bit = (row[j] & 1) ^ 1 if invert else (row[j] & 1)
            fb[(bpf - 1) - (ofs >> 3)] |= bit << (ofs & 7)
        frames.append(bytes(fb))
    return frames


def _build_dictionary(frames):
    """Histogram-based dictionary build, port of write_compressed_frames.

    Returns dict_entries[0..7] (most-frequent first), matching Diamond's
    priority-queue pop order: sort by (count, byte_value) descending.
    """
    histogram = [0] * 256
    for fr in frames:
        for b in fr:
            histogram[b] += 1
    candidates = [i for i in range(256) if i != 0 and _decode_onehot(i) == -1]
    # C++ std::priority_queue<pair<int,uint8_t>> pops the max (count, then byte).
    candidates.sort(key=lambda i: (histogram[i], i), reverse=True)
    return candidates[:8]


def _compress_frames(frames, dict_entries):
    """Bit-pack frames using the 4-case prefix code (port of the encoder loop)."""
    payload = bytearray()
    state = {"buffer": 0, "bits": 0}

    def flush():
        if state["bits"] != 0:
            payload.append(state["buffer"])
            state["buffer"] = 0
            state["bits"] = 0

    def add_bit(bit):
        if bit:
            state["buffer"] |= 1 << (7 - state["bits"])
        state["bits"] += 1
        if state["bits"] == 8:
            flush()

    def add_bits(x, length):
        for i in range(length - 1, -1, -1):
            add_bit((x >> i) & 1)

    for fr in frames:
        fb = len(fr)
        if fb % 8 != 0:
            for _ in range(8 - (fb % 8)):
                add_bit(0)
        for b in fr:
            if b == 0:
                add_bit(0)
                continue
            oh = _decode_onehot(b)
            if oh != -1:
                add_bits(0b100, 3)
                add_bits(oh, 3)
                continue
            found = False
            for j in range(8):
                if dict_entries[j] == b:
                    add_bits(0b101, 3)
                    add_bits(j, 3)
                    found = True
                    break
            if found:
                continue
            add_bits(0b11, 2)
            add_bits(b, 8)
        flush()  # 8-bit align each frame (crc_after_each_frame is False on XO2)
    return bytes(payload)


def _repack_ebr_words(words):
    """Inverse of the EBR 9-byte -> 8x9-bit unpack (port of serialise_chip)."""
    frame = bytearray(9)
    w = words
    frame[0] = (w[0] >> 1) & 0xFF
    frame[1] = ((w[0] & 0x01) << 7 | (w[1] >> 2)) & 0xFF
    frame[2] = ((w[1] & 0x03) << 6 | (w[2] >> 3)) & 0xFF
    frame[3] = ((w[2] & 0x07) << 5 | (w[3] >> 4)) & 0xFF
    frame[4] = ((w[3] & 0x0F) << 4 | (w[4] >> 5)) & 0xFF
    frame[5] = ((w[4] & 0x1F) << 3 | (w[5] >> 6)) & 0xFF
    frame[6] = ((w[5] & 0x3F) << 2 | (w[6] >> 7)) & 0xFF
    frame[7] = ((w[6] & 0x7F) << 1 | (w[7] >> 8)) & 0xFF
    frame[8] = w[7] & 0xFF
    return bytes(frame)


def encode(pb, geom=MACHXO2_1200):
    """Re-serialise a ParsedBitstream into the exact byte stream (inverse of parse).

    Config frames come from `pb.cram`, EFB/EBR from their decoded records, and
    every CRC16 is recomputed.  Structural scaffolding is replayed verbatim.
    """
    w = BitstreamWriter()
    w.write_raw(pb.header)   # .bit ASCII header (b"" for a bare .bin)
    w.write_raw(pb.pre)      # leading bytes + preamble (never CRC'd)

    # If a compressed frame block exists, build its dictionary + payload once so
    # the DICT record and the FRAMES record stay consistent.
    dict_entries = None
    compressed_payload = None
    for kind, r in pb.records:
        if kind == "FRAMES" and r["compressed"]:
            frames = _cram_to_frames(pb, geom)
            dict_entries = _build_dictionary(frames)
            compressed_payload = _compress_frames(frames, dict_entries)
            break

    for kind, r in pb.records:
        if kind == "DUMMY":
            w.write_raw(b"\xFF" * r["count"])

        elif kind == "RAW":
            w.write_bytes(r["raw"])

        elif kind == "RAW_RESET":
            w.write_bytes(r["raw"])
            w.reset_crc16()

        elif kind == "DONE":
            w.write_byte(r["opcode"])
            w.write_byte(r["flags"])
            w.write_bytes(r["skip2"])
            if r["check_crc"]:
                w.insert_crc16()

        elif kind == "USERCODE":
            w.write_byte(r["opcode"])
            w.write_byte(r["flags"])
            w.write_bytes(r["skip2"])
            w.write_uint32(r["usercode"])
            if r["check_crc"]:
                w.insert_crc16()   # finalise + emit + reset
            else:
                w.reset_crc16()    # reader resets unconditionally here

        elif kind == "DICT":
            w.write_byte(LSC_WRITE_COMP_DIC)
            w.write_byte(r["flags"])
            w.write_bytes(r["skip2"])
            entries = dict_entries if dict_entries is not None else \
                list(r["dict_bytes"])
            # Written pattern7..pattern0 (reverse), per write_compressed_frames.
            for i in range(7, -1, -1):
                w.write_byte(entries[i])
            if r["one_hot"]:
                for i in range(7, -1, -1):
                    w.write_byte(1 << i)
            if r["check_crc"]:
                w.insert_crc16()

        elif kind == "FRAMES":
            params = r["params"]
            check_crc = bool(params[0] & 0x80)
            crc_after_each_frame = check_crc and not (params[0] & 0x40)
            dummy_bytes = params[0] & 0x0F
            w.write_byte(r["opcode"])
            w.write_bytes(params)
            if r["compressed"]:
                # dummy_bytes / per-frame CRC are 0 / off for MachXO2 compressed.
                w.write_bytes(compressed_payload)
                if check_crc:
                    w.insert_crc16()
            elif r["inverted"]:
                # MachXO WRITE_INC_FRAME (inverted data + End Fuse Data Frame).
                frames = _cram_to_frames(pb, geom, invert=True)
                for fb in frames:
                    w.write_bytes(fb)
                    if crc_after_each_frame:
                        w.insert_crc16()
                    w.write_bytes(b"\xFF" * r["dummy_bytes"])
                w.write_bytes(r["end_fuse"])
                w.insert_crc16()
            else:
                frames = _cram_to_frames(pb, geom)
                for i, fb in enumerate(frames):
                    w.write_bytes(fb)
                    if crc_after_each_frame or (check_crc and i == len(frames) - 1):
                        w.insert_crc16()
                    w.write_bytes(b"\xFF" * dummy_bytes)

        elif kind == "EBR_WRITE":
            w.write_byte(LSC_EBR_WRITE)
            w.write_bytes(r["params"])
            for words in r["words"]:
                w.write_bytes(_repack_ebr_words(words))
            if r["check_crc"]:
                w.insert_crc16()

        elif kind == "EFB":
            w.write_byte(CMD_0x72)
            w.write_byte(r["flags"])
            w.write_byte(r["sel"])
            w.write_byte(len(r["payload"]))
            w.write_bytes(r["payload"])

        else:
            raise ParseError(f"encode: unknown record kind {kind!r}")

    w.write_raw(pb.trailer)  # bytes after DONE (never CRC'd)
    return bytes(w.out)


def re_encode_file(path, geom=MACHXO2_1200):
    """Parse `path` then re-encode; returns (original_bytes, encoded_bytes)."""
    raw = open(path, "rb").read()
    pb = parse_file(path, geom=geom)
    return raw, encode(pb, geom=geom)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bitfile")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    pb = parse_file(args.bitfile, verbose=args.verbose)
    setbits = sum(sum(row) for row in pb.cram)
    print(f"# {args.bitfile}")
    print(f"# frames_read={pb.frames_read}/{pb.num_frames} "
          f"crc_verified={pb.crc_verified} idcode="
          f"{('0x%08x' % pb.idcode) if pb.idcode is not None else 'none'}")
    print(f"# cram set bits={setbits}  efb_blocks={len(pb.efb_blocks)}")
    if pb.frames_read != pb.num_frames:
        raise SystemExit(f"FAIL: frames_read {pb.frames_read} != {pb.num_frames}")


if __name__ == "__main__":
    main()
