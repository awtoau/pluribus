#!/usr/bin/env python3
"""RAM clock-enable / clear shared-PIA-line preferences from CODE (#165, #169): constructor of ASM_RAM_CE_FAST_MUX (and CLEAR_FAST_MUX) per group index.

ASM_RAM_CE_FAST_MUX::ASM_RAM_CE_FAST_MUX@0x2f686 stores m_unused_index_preferred (+0x38) / m_unused_index_alternate (+0x3c) = PIA line numbers by
family / block type / group index; process_end_of_phase selects one of them (docs/cycloneiv-clean-hardblocks.md).  Run in Unicorn (python3.14): the family
jump table (base_family - 6) is entered at the target of family FAMILY with the group index and block type in the ASMDB_ARCH_GROUP_BASE stub.
  python3.14 scripts/cycloneiv_ram_ce_lines.py [ctor_vaddr [family]]      -> JSON {gi: [preferred, alternate, flags]}
"""
import json
import struct
import sys

import capstone
import unicorn
from unicorn import x86_const as X

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import cycloneiv_ram_mapper as R

CTOR = {"CE": 0x2f686}
FAMILY = 14         # source: same family as the port-input mapper (cycloneiv_ram_mapper.py)
TABLE = 0x8d378     # source: objdump of the ctor: lea 8d378 (family jump table, 56 relative entries)
GROUP_PTR, THIS, BASE_FAMILY_CELL = 0x7c000000, 0x7b000000, 0x7a000000


def run(ctor, family, gi, btype=0x27):
    mu = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_64)
    R.load(mu)
    for a in (R.STACK - 0x10000, GROUP_PTR, THIS, BASE_FAMILY_CELL):
        mu.mem_map(a, 0x20000 if a == R.STACK - 0x10000 else 0x1000)
    mu.mem_write(0xa3e28, struct.pack("<Q", BASE_FAMILY_CELL))           # GOT slot of ASM_MODEL::s_base_family (readelf: R_X86_64_GLOB_DAT)
    mu.mem_write(BASE_FAMILY_CELL, struct.pack("<I", family))
    mu.mem_write(GROUP_PTR + 8, struct.pack("<I", gi))
    mu.mem_write(GROUP_PTR + 0x10, struct.pack("<I", btype))
    mu.mem_write(THIS + 0x38, struct.pack("<ii", -1, -1))
    mu.reg_write(X.UC_X86_REG_RSP, R.STACK)
    mu.reg_write(X.UC_X86_REG_RDI, THIS)
    mu.reg_write(X.UC_X86_REG_RSI, GROUP_PTR)
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)

    def hook(uc, addr, size, _):
        ins = next(cs.disasm(bytes(uc.mem_read(addr, size)), addr))
        if ins.mnemonic == "call":
            uc.reg_write(X.UC_X86_REG_RIP, addr + size)
        elif ins.mnemonic == "ret":
            uc.emu_stop()
    mu.hook_add(unicorn.UC_HOOK_CODE, hook)
    try:
        mu.emu_start(ctor, 0, count=2000)
    except unicorn.UcError as e:
        print(f"gi {gi}: stop {e} at {mu.reg_read(X.UC_X86_REG_RIP):#x}", file=sys.stderr)
    pref, alt = struct.unpack("<ii", bytes(mu.mem_read(THIS + 0x38, 8)))
    return [pref, alt, list(bytes(mu.mem_read(THIS + 0x34, 4)))]


if __name__ == "__main__":
    ctor = int(sys.argv[1], 16) if len(sys.argv) > 1 else CTOR["CE"]
    fam = int(sys.argv[2]) if len(sys.argv) > 2 else FAMILY
    out = {"family": fam, "ce_fast_mux": {str(gi): run(ctor, fam, gi) for gi in range(4)},
           "source": "ASM_RAM_CE_FAST_MUX::ASM_RAM_CE_FAST_MUX@0x2f686 emulated: [preferred line, alternate line, flag bytes +0x34..+0x37] per group index (MEAB)"}
    if len(sys.argv) > 3 and sys.argv[3] == "--write":
        import os
        json.dump(out, open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lifters", "cycloneiv_clean", "ram_ce_lines.json"), "w"))
    print(json.dumps(out))
