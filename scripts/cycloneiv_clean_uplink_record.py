#!/usr/bin/env python3
"""Ground->air uplink record as m1400 builds it (FUN_0001698a @0x1698a, C1_FW_V01.06.0000), for simulation stimulus.

Record (0x38 bytes, written to FPGA regs 0x44..0x7B), all V from the decompile unless marked:
  [0x00..0x0E] header, from a RAM template at 0x10003af0 (contents U: filled by other code; sticks/IDs)
  [0x0F..0x10] CRC-16 LE, reflected poly 0x8408 table @0x2f4b8, init 0x55AA, over [0..0x0E] then [0x11..0x36]
  [0x11..0x1A] stick/control words (template, U)
  [0x1B]       chunk length (template, U) -- 23 for a normal DUML chunk
  [0x1C..0x32] one 23-byte DUML chunk (from the port-1 queue 0x100033d0)
  [0x33..0x36] 32-bit frame counter LE (rc_state+0x70, incremented per record)
  bytes 1..0x37 ^= key[i & 7]  (8-byte key at rc_state+0x64; value U)
  [0x37]       CRC-8 after scrambling: reflected poly 0x8C (Dallas) table @0x2f6b8, init 0xAA, over [0..0x36]
ID block (8 bytes, regs 0x40..0x43 then 0x7C..0x7F): rc_state+0x0C..0x12 (7 bytes, U) + CRC-8 init 0xA8 (mode 1/3) / 0xA9 (mode 0).

  python3 scripts/cycloneiv_clean_uplink_record.py      # self-test, prints one record
"""
CRC16_POLY = 0x8408      # reflected CRC-16-CCITT; the firmware table at 0x2f4b8 matches exactly
CRC8_POLY = 0x8C         # reflected Dallas/Maxim; table at 0x2f6b8 matches exactly


def crc16(data, init=0x55AA):
    c = init
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ CRC16_POLY if c & 1 else c >> 1
    return c & 0xFFFF


def crc8(data, init=0xAA):
    c = init
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ CRC8_POLY if c & 1 else c >> 1
    return c & 0xFF


def build_record(template, chunk, frame_counter, key, scramble=True):
    """template: 0x38 bytes (header/sticks/len; bytes 0x1C.. overwritten), chunk: <=23 bytes, key: 8 bytes."""
    r = bytearray(template[:0x38].ljust(0x38, b"\0"))
    r[0x1B] = len(chunk)
    r[0x1C:0x1C + len(chunk)] = chunk
    r[0x33:0x37] = (frame_counter & 0xFFFFFFFF).to_bytes(4, "little")
    c = crc16(r[0x11:0x37], crc16(r[0:0x0F], 0x55AA))
    r[0x0F:0x11] = c.to_bytes(2, "little")
    if scramble:
        for i in range(1, 0x38):
            r[i] ^= key[i & 7]
    r[0x37] = crc8(r[0:0x37], 0xAA)
    return bytes(r)


def build_id_block(id7, mode=3):
    """7 bytes rc_state+0x0C..0x12 + CRC-8 (init 0xA8 for mode 1/3, 0xA9 for mode 0) -> 8 bytes."""
    init = 0xA8 if mode in (1, 3) else 0xA9
    return bytes(id7[:7]) + bytes([crc8(id7[:7], init)])


def duml_frame(cmd_set, cmd_id, payload, seq=1):
    """A DUML frame (0x55, len/ver, hdr CRC-8, src/dst, seq, cmd_type, set, id, payload, CRC-16): the chunk payload."""
    length = 13 + len(payload)
    hdr = bytes([0x55, length & 0xFF, 0x04 | ((length >> 8) & 0x03)])
    hdr += bytes([crc8(hdr, 0x77)])        # DUML header CRC-8 (poly 0x8C reflected, seed 0x77: the public DUML seed)
    body = bytes([0x02, 0x0A]) + seq.to_bytes(2, "little") + bytes([0x40, cmd_set, cmd_id]) + bytes(payload)
    f = hdr + body
    return f + crc16(f, 0x3692).to_bytes(2, "little")   # seed 0x3692 = m1400's own DUML CRC-16 seed (FUN_0001fa7a)


if __name__ == "__main__":
    tmpl = bytes([0x01, 0x12, 0x34, 0x56, 0x78] + [0] * 10 + [0, 0] + [0x80, 0x00] * 5 + [23]) + bytes(0x38 - 0x1C)
    ch = duml_frame(0x09, 0x0C, b"\x01\x02\x03\x04")[:23]
    rec = build_record(tmpl, ch, 7, bytes(range(1, 9)))
    print(rec.hex(), len(rec))
    print(build_id_block(bytes([0x12, 0x34, 0x56, 0x78, 0x00, 0x01, 0x02])).hex())
