#!/usr/bin/env python3
"""Pure-Python MachXO2 bitstream command-stream walker.

Walks an *uncompressed* MachXO2 bitstream command-by-command, printing each
opcode, its offset, and consumed length.  Written to reverse-engineer the
undocumented 0x72 command (pluribus issue P1 / P2).

For compressed streams (real vendor bitstreams) pass --data-file pointing at a
raw post-header byte dump (e.g. produced from pytrellis .data), or use the
built-in bit-header stripper on an uncompressed .bit.
"""
import sys, argparse

PREAMBLE = bytes([0xFF, 0xFF, 0xBD, 0xB3])

CMD = {
    0x79: "SPI_MODE",
    0x7E: "JUMP",
    0x3B: "LSC_RESET_CRC",
    0xE2: "VERIFY_ID",
    0x02: "LSC_WRITE_COMP_DIC",
    0x22: "LSC_PROG_CNTRL0",
    0x23: "LSC_PROG_CNTRL1",
    0x46: "LSC_INIT_ADDRESS",
    0xB4: "LSC_WRITE_ADDRESS",
    0xB8: "LSC_PROG_INCR_CMP",
    0x82: "LSC_PROG_INCR_RTI",
    0xA2: "LSC_PROG_SED_CRC",
    0xCE: "ISC_PROGRAM_SECURITY",
    0xC2: "ISC_PROGRAM_USERCODE",
    0xC3: "ISC_PROGRAM_USERCODE_2",
    0xF6: "LSC_EBR_ADDRESS",
    0xB2: "LSC_EBR_WRITE",
    0x5E: "ISC_PROGRAM_DONE",
    0x7A: "ISC_PROGRAM_DONE_2",
    0xC4: "LSC_PROG_CNTRL0_2",
    0x41: "WRITE_INC_FRAME",
    0x72: "CMD_0x72",  # undocumented
    0xFF: "DUMMY",
}

# MachXO2-1200 geometry
BITS_PER_FRAME = 1080
PAD_AFTER = 0
PAD_BEFORE = 0
NUM_FRAMES = 333
BYTES_PER_FRAME = (BITS_PER_FRAME + PAD_AFTER + PAD_BEFORE) // 8  # 135


class Reader:
    def __init__(self, data, start=0):
        self.d = data
        self.i = start
        self.crc = 0x0000

    def _upd(self, val):
        for k in range(7, -1, -1):
            bf = self.crc >> 15
            self.crc = (self.crc << 1) & 0xFFFF
            self.crc |= (val >> k) & 1
            if bf:
                self.crc ^= 0x8005
        self.crc &= 0xFFFF

    def byte(self):
        v = self.d[self.i]
        self.i += 1
        self._upd(v)
        return v

    def opcode(self):
        v = self.d[self.i]
        self.i += 1
        if v != 0xFF:
            self._upd(v)
        return v

    def skip(self, n):
        for _ in range(n):
            self.byte()

    def u32(self):
        b = [self.byte() for _ in range(4)]
        return (b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]

    def finalise_crc(self):
        c = self.crc
        for _ in range(16):
            bf = c >> 15
            c = (c << 1) & 0xFFFF
            if bf:
                c ^= 0x8005
        self.crc = c & 0xFFFF
        return self.crc

    def check_crc(self):
        exp = self.finalise_crc()
        hi = self.byte(); lo = self.byte()
        act = (hi << 8) | lo
        self.crc = 0x0000
        return exp, act

    def reset_crc(self):
        self.crc = 0x0000


def strip_bit_header(raw):
    """Return byte vector after the .bit ASCII header (as pytrellis .data)."""
    i = 0
    if raw[0:2] == b'LS' or raw[0:4] == b'LSCC':
        # LSCC + FF 00 ... then meta ... FF then FFFFFFFF
        i = 4
    # expect FF 00
    assert raw[i] == 0xFF and raw[i+1] == 0x00, "no FF 00 header"
    i += 2
    while raw[i] != 0xFF:
        i += 1
    i += 1  # consume terminating FF
    return raw[i:]


def find_preamble(data, start=0):
    idx = data.find(PREAMBLE, start)
    if idx < 0:
        return -1
    return idx + len(PREAMBLE)


def walk(data, stop_at_72=True, cmd72_len=None, verbose=True):
    """Walk commands. Returns list of (offset, opcode, name, consumed)."""
    start = find_preamble(data)
    if start < 0:
        raise RuntimeError("preamble not found")
    r = Reader(data, start)
    events = []
    no_id_mode = False
    while r.i < len(data):
        off = r.i
        op = r.opcode()
        name = CMD.get(op, "UNKNOWN")
        consumed_start = off
        info = ""
        if op == 0xFF:  # DUMMY
            # consume run of dummies quietly
            continue
        elif op == 0x3B:  # LSC_RESET_CRC
            r.skip(3); r.reset_crc()
        elif op == 0xE2:  # VERIFY_ID
            r.skip(3)
            if no_id_mode:
                r.reset_crc()
            else:
                idc = r.u32(); info = f"id=0x{idc:08x}"
        elif op == 0xC4:  # LSC_PROG_CNTRL0_2
            no_id_mode = True; r.skip(3); cfg = r.u32(); info = f"cfg0=0x{cfg:08x}"
        elif op == 0x22:  # LSC_PROG_CNTRL0
            r.skip(3); cfg = r.u32(); info = f"ctrl0=0x{cfg:08x}"
        elif op == 0x23:  # LSC_PROG_CNTRL1
            r.skip(3); cfg = r.u32(); info = f"ctrl1=0x{cfg:08x}"
        elif op in (0x5E, 0x7A):  # ISC_PROGRAM_DONE
            m = r.byte(); check = (m & 0x80) != 0; r.skip(2)
            if check:
                e, a = r.check_crc(); info = f"crc exp=0x{e:04x} act=0x{a:04x} {'OK' if e==a else 'FAIL'}"
            events.append((off, op, name, r.i - consumed_start, info))
            if verbose:
                print(f"0x{off:06x}  0x{op:02x} {name:22s} len={r.i-consumed_start:<4d} {info}")
            break  # DONE = end
        elif op == 0xCE:  # ISC_PROGRAM_SECURITY
            r.skip(3)
        elif op in (0xC2, 0xC3):  # ISC_PROGRAM_USERCODE
            m = r.byte(); check = (m & 0x80) != 0; r.skip(2); uc = r.u32(); info = f"usercode=0x{uc:08x}"
            if check:
                e, a = r.check_crc(); info += f" crc {'OK' if e==a else 'FAIL'}"
            r.reset_crc()
        elif op == 0x02:  # LSC_WRITE_COMP_DIC
            m = r.byte(); check = (m & 0x80) != 0; r.skip(2)
            for _ in range(8):
                r.byte()
            if check:
                e, a = r.check_crc(); info = f"crc {'OK' if e==a else 'FAIL'}"
        elif op == 0x46:  # LSC_INIT_ADDRESS
            r.skip(3)
        elif op in (0x82, 0xB8):  # LSC_PROG_INCR_RTI / CMP
            p = [r.byte() for _ in range(3)]
            check = bool(p[0] & 0x80)
            crc_each = check and not (p[0] & 0x40)
            dummy = p[0] & 0x0F
            fcount = (p[1] << 8) | p[2]
            bpf = BYTES_PER_FRAME
            if op == 0xB8:
                bpf += (7 - ((bpf - 1) % 8))
            info = f"params={p[0]:02x} frames={fcount} dummy={dummy} bpf={bpf}"
            for i in range(fcount):
                if op == 0xB8:
                    raise RuntimeError("compressed frames not supported in this walker path")
                r.skip(bpf)
                if crc_each or (check and i == fcount - 1):
                    r.check_crc()
                r.skip(dummy)
        elif op == 0xF6:  # LSC_EBR_ADDRESS
            r.skip(3); r.u32()
        elif op == 0xB2:  # LSC_EBR_WRITE
            p = [r.byte() for _ in range(3)]
            fcount = (p[1] << 8) | p[2]
            check = bool(p[0] & 0x80)
            for _ in range(fcount):
                r.skip(9)
            if check:
                r.check_crc()
            info = f"frames={fcount}"
        elif op == 0x79:  # SPI_MODE
            r.byte(); r.skip(2)
        elif op == 0x7E:  # JUMP
            r.skip(3); r.skip(4)
        elif op == 0xA2:  # LSC_PROG_SED_CRC
            r.skip(3); r.u32()
        elif op == 0x72:  # UNDOCUMENTED
            if stop_at_72 and cmd72_len is None:
                events.append((off, op, name, 0, "STOP (unknown length)"))
                if verbose:
                    print(f"0x{off:06x}  0x{op:02x} {name:22s} <-- STOP, unknown length")
                break
            # LENGTH RULE: opcode + 3 info bytes + info[2] payload bytes.
            p = [r.byte() for _ in range(3)]
            plen = p[2] if cmd72_len is None else (cmd72_len - 4)
            r.skip(plen)
            info = f"flags={p[0]:02x} mid={p[1]:02x} len={p[2]} -> total={4+p[2]}"
        else:
            events.append((off, op, name, 0, "UNKNOWN OPCODE"))
            if verbose:
                print(f"0x{off:06x}  0x{op:02x} {name:22s} <-- UNKNOWN, STOP")
            break
        events.append((off, op, name, r.i - consumed_start, info))
        if verbose:
            print(f"0x{off:06x}  0x{op:02x} {name:22s} len={r.i-consumed_start:<4d} {info}")
    return events, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bitfile")
    ap.add_argument("--data-file", action="store_true", help="input is raw data (already header-stripped)")
    ap.add_argument("--cmd72-len", type=int, default=None)
    ap.add_argument("--no-stop", action="store_true")
    args = ap.parse_args()
    raw = open(args.bitfile, "rb").read()
    data = raw if args.data_file else strip_bit_header(raw)
    print(f"# {args.bitfile}  data={len(data)} bytes")
    events, r = walk(data, stop_at_72=not args.no_stop, cmd72_len=args.cmd72_len)
    print(f"# ended at offset 0x{r.i:06x} / 0x{len(data):06x}  ({len(data)-r.i} bytes left)")


if __name__ == "__main__":
    main()
