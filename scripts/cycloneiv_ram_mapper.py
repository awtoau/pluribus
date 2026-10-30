#!/usr/bin/env python3
"""RAM port-input mapper tables from CODE (#165, #169): (explicit RAM mode, group index) -> (RAM_INPUT_PORT_TYPE, port index).

Source: libcomp_asmram family-switch blocks of the ASM_RAM_MS_* constructors fill std::map<pair<ASM_EXPLICIT_RAM_MODE, gi>, pair<type, idx>>
(ASM_RAM_MS_INPUT_MAPPER::look_up_port_source@0x661b0 reads it).  The block is run in a Unicorn x86-64 emulator (python3, not the free-threaded build):
operator[] (PLT 0x1e820) is hooked to record the key and the two stores of the value.  Static analysis only: no vendor code is executed natively.

  python3.14 scripts/cycloneiv_ram_mapper.py --all   -> lifters/cycloneiv_clean/ram_mapper_table.json
  python3.14 scripts/cycloneiv_ram_mapper.py <ctor-name> <family-target-vaddr> <block-type 0x26 SEAB | 0x27 MEAB>   -> JSON on stdout
Log: tmp/logs/cycloneiv_ram_mapper.log
"""
import json
import os
import struct
import sys

import capstone
import unicorn
from unicorn import x86_const as X

LIB = "/mnt/2tb/opt/altera/quartus-25.1/quartus/linux64/libcomp_asmram.so"
OPER_INDEX = 0x1e820        # source: objdump PLT slot of std::map<pair<ASM_EXPLICIT_RAM_MODE,unsigned>,pair<RAM_INPUT_PORT_TYPE,unsigned>>::operator[]
STACK, SCRATCH, NODE = 0x7f000000, 0x7e000000, 0x7d000000
MAX_STEPS = 200000          # source: block of ~5k instructions with loops over <= 40 groups x 9 modes; 40x margin, expiry = error


def load(mu):
    d = open(LIB, "rb").read()
    for off, va, fsz, msz in ((0, 0, 0x9e120, 0x9e120), (0x9e5b8, 0x9f5b8, 0x55f0, 0x6210)):     # source: readelf -lW PT_LOAD
        base = va & ~0xfff
        size = (va + msz - base + 0xfff) & ~0xfff
        mu.mem_map(base, size) if base not in getattr(load, "m", set()) else None
        mu.mem_write(va, d[off:off + fsz])


def run(start, btype, log=None):
    mu = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_64)
    load(mu)
    mu.mem_map(STACK - 0x10000, 0x20000)
    mu.mem_map(SCRATCH, 0x1000)
    mu.mem_map(NODE, 0x1000)
    sp = STACK
    mu.reg_write(X.UC_X86_REG_RSP, sp)
    mu.reg_write(X.UC_X86_REG_RAX, btype)
    mu.reg_write(X.UC_X86_REG_RBX, NODE)
    ent, cur = {}, {}
    pend = {}

    def code_hook(uc, addr, size, _):
        ins = next(cs.disasm(bytes(uc.mem_read(addr, size)), addr))
        if ins.mnemonic == "call":
            tgt = int(ins.op_str, 16) if ins.op_str.startswith("0x") else None
            if tgt == OPER_INDEX:
                rsi = uc.reg_read(X.UC_X86_REG_RSI)
                key = struct.unpack("<II", bytes(uc.mem_read(rsi, 8)))
                cur["key"] = key
                ent.setdefault(key, [None, None])
                uc.mem_write(SCRATCH, b"\0" * 16)
                uc.reg_write(X.UC_X86_REG_RAX, SCRATCH)
            else:
                uc.reg_write(X.UC_X86_REG_RAX, 0)
            uc.reg_write(X.UC_X86_REG_RIP, addr + size)
        elif ins.mnemonic == "ret":
            uc.emu_stop()

    def mem_hook(uc, access, addr, size, value, _):
        if SCRATCH <= addr < SCRATCH + 8 and "key" in cur:
            ent[cur["key"]][(addr - SCRATCH) // 4] = value & 0xffffffff

    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    mu.hook_add(unicorn.UC_HOOK_CODE, code_hook)
    mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, mem_hook)
    try:
        mu.emu_start(start, 0, count=MAX_STEPS)
    except unicorn.UcError as e:
        print(f"stop at rip={mu.reg_read(X.UC_X86_REG_RIP):#x}: {e}", file=sys.stderr)
    return ent


# source: family jump tables of the constructors (objdump; table index = base_family - 6, entry = relative offset); family 14 targets
# (Cyclone IV GX: the only family whose WRITE_ADDRESS gi set {0..7, 12} and DATA low-address gi 12..15 agree, docs/cycloneiv-clean-hardblocks.md)
GROUPS = {"RAM_MS_DATA_INPUT": 0x6b5eb, "RAM_MS_DATA_INPUT_B": 0x75fae, "RAM_MS_WRITE_ADDRESS_INPUT": 0x78c00,
          "RAM_MS_READ_ADDRESS_INPUT": 0x7c2ac, "RAM_MS_BYTE_ENABLE_INPUT": 0x6cf97}
MEAB = 0x27         # source: ASMDB_ARCH_GROUP_BLOCK_TYPE MEAB
# source: ASM_RAM_MS_INPUT_MAPPER::calculate_explicit_mode@0x65ddc switch on the port width
WIDTH_MODE = {1: 1, 2: 2, 4: 3, 8: 4, 9: 10, 16: 5, 18: 11, 32: 12, 36: 13}      # 32 / 36: the DATA group's modes 12 / 13 (32 pins skipping gi 8 and 26; 36 pins)

if __name__ == "__main__":
    if sys.argv[1] == "--all":
        out = {"width_mode": WIDTH_MODE, "source": "libcomp_asmram ASM_RAM_MS_* constructors, family 14 MEAB block (emulated, cycloneiv_ram_mapper.py)", "groups": {}}
        for g, a in GROUPS.items():
            ent = run(a, MEAB)
            out["groups"][g] = [[k[0], k[1], v[0], v[1]] for k, v in sorted(ent.items())]
        json.dump(out, open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lifters", "cycloneiv_clean", "ram_mapper_table.json"), "w"))
        print({g: len(v) for g, v in out["groups"].items()})
        sys.exit(0)
    ent = run(int(sys.argv[2], 16), int(sys.argv[3], 16))
    print(json.dumps([{"mode": k[0], "gi": k[1], "type": v[0], "idx": v[1]} for k, v in sorted(ent.items())]))
