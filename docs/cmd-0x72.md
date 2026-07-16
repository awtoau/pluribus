# MachXO2 bitstream command `0x72` — reverse-engineered spec

Status: **length rule solved and validated** (pluribus P1 unblocker for the
native Python bitstream parser, P2).

`0x72` (`0b0111_0010`) is a MachXO2/MachXO3 bitstream command that prjtrellis
does not model (not in its `BitstreamCommand` enum). It is emitted **after** the
fabric config frames and **before** `ISC_PROGRAM_USERCODE` (0xC2) / the EBR
init blocks / `ISC_PROGRAM_DONE` (0x5E). It appears only when the **EFB**
(Embedded Function Block) has an active peripheral. It is an EFB
feature/config-register preload command (nearest documented neighbour is
`LSC_PROG_INCR_NV` = 0x70, one bit away).

## Byte structure

```
+--------+--------+--------+--------+===================+
| 0x72   | flags  | sel    | len    | payload[len]      |
| opcode | info0  | info1  | info2  | (len bytes)       |
+--------+--------+--------+--------+===================+
```

| Field | Offset | Meaning |
|---|---|---|
| opcode | 0 | `0x72` |
| `flags` (info0) | 1 | Command flags. MSB (`0x80`) = "CRC follows", as with other Lattice commands. **Always `0x10` in every real block observed → MSB clear → NO embedded CRC in the 0x72 block.** |
| `sel` (info1) | 2 | EFB peripheral / register selector. `0x54` = **SPI** EFB config; `0x5e` = **TC** (timer/counter) config. |
| `len` (info2) | 3 | **Payload length in bytes.** This is the whole length rule. |
| `payload` | 4 | `len` bytes: the selected peripheral's config-register value. |

### Length rule (the deliverable)

```
total_bytes_consumed = 4 + info[2]        # opcode + 3 info bytes + payload
```

- No embedded CRC (info0 MSB is clear), so nothing extra to skip.
- The block's bytes **are** part of the running CRC16 accumulator (they are
  consumed with normal `get_byte` semantics). This is proven by the fact that
  the *next* command, `ISC_PROGRAM_USERCODE` with its CRC-check flag set,
  validates **CRC OK** on every stream — impossible unless the 0x72 bytes were
  folded into the CRC exactly.
- `0x72` blocks may appear **0, 1, or 2 times consecutively** (SPI block then
  TC block). A parser must loop while the current opcode is `0x72`.

Parser pseudocode:

```python
while opcode == 0x72:
    flags, sel, length = read(3)      # info bytes, folded into CRC16
    payload = read(length)            # folded into CRC16
    # do NOT check_crc here; flags MSB is clear
    opcode = read_opcode()
```

## Payload semantics

`sel` selects which EFB peripheral register the payload programs; the payload
is that register's literal value. Length is fixed *per selector* but the rule
never needs to hard-code it — always take `info[2]`.

| `sel` | Emitted when | `len` | Payload (fuzz default) | Notes |
|---|---|---|---|---|
| `0x54` | `EFB_SPI` enabled | 10 (`0x0a`) | `00 80 00 00 ff 00 00 00 00 00` | Constant across all SPI-enabled streams and both vendor bitstreams. SPI EFB config register preload. |
| `0x5e` | `EFB_TC` enabled | 18 (`0x12`) | `88 55 ff ff ff 7f 00 …` | Content **varies with the timer configuration**: fuzz default `88 55 ff ff ff 7f …`, a real vendor stream `48 1a 23 f4 11 7a 00 …`. Timer/counter config-register preload. |

Feature → block mapping, from single-feature fuzz toggles
(`re_efb_<I2C1><I2C2><SPI><TC><UFM>_S`):

| Target | Enabled | 0x72 blocks |
|---|---|---|
| `00000` | none | none |
| `00001` | UFM | **none** (UFM alone emits no 0x72) |
| `00010` | TC | `sel=0x5e` only |
| `00100` | SPI | `sel=0x54` only |
| `00110` | SPI+TC | `0x54` then `0x5e` |
| `00111` | SPI+TC+UFM | `0x54` then `0x5e` |

So `0x72` carries **EFB peripheral config-register preloads**, one block per
active register-bearing peripheral (SPI, TC). UFM and the bare fabric emit
none.

## Validation evidence

A block is "validated" iff a parser consuming it by `total = 4 + info[2]`
lands exactly on the next real command and walks cleanly to `ISC_PROGRAM_DONE`,
with the intervening `ISC_PROGRAM_USERCODE` reporting **CRC OK** (byte-exact
proof). All of the following passed:

| Bitstream | Compressed? | 0x72 blocks | Result |
|---|---|---|---|
| `re_efb_00010_S` | yes | 1 (`5e`) | PASS → DONE, USERCODE CRC OK |
| `re_efb_00011_S` | yes | 1 (`5e`) | PASS |
| `re_efb_00100_S` / `_nc` | yes / no | 1 (`54`) | PASS |
| `re_efb_00101_S` / `_nc` | yes / no | 1 (`54`) | PASS |
| `re_efb_00110_S` | yes | 2 (`54`,`5e`) | PASS |
| `re_efb_00111_S` / `_nc` | yes / no | 2 (`54`,`5e`) | PASS |
| **vendor A** (compressed) | yes | 1 (`54`) @0x58c0 | PASS → 6 EBR blocks → DONE |
| **vendor B** (compressed) | yes | 2 (`54`,`5e`) @0x56a8 | PASS → 6 EBR blocks → DONE |
| `re_efb_00000_S` (`_nc`), `re_efb_00001_S` | — | none | Negative controls: parse to DONE with no 0x72 |

For the two real vendor streams the length rule lands the parser exactly on the
following byte: vendor A `0x58c0 + 14 = 0x58ce` = USERCODE; vendor B
`0x56a8 + 14 = 0x56b6` = second 0x72, `+ 22 = 0x56cc` = USERCODE.

## Tools (pure Python, no pytrellis needed)

- `scripts/cmd72_walk.py` — command-stream walker for uncompressed MachXO2
  `.bit` files. Walks preamble → DONE printing each opcode, offset, consumed
  length. `--no-stop` consumes 0x72 by the length rule; without it, stops at
  the first 0x72. Handles the CRC16 exactly as libtrellis.
- `scripts/cmd72_analyze.py` — locates and validates the 0x72 chain in any
  bitstream (compressed vendor `.bin` included) by trying candidate offsets and
  requiring a byte-exact walk to DONE with USERCODE CRC OK. Prints each block's
  info bytes + payload.

```
python3 scripts/cmd72_walk.py <uncompressed.bit> [--no-stop]
python3 scripts/cmd72_analyze.py <any.bit|.bin> ...
```

## For the P2 native parser

Add to the command switch:

```python
elif op == 0x72:              # EFB feature/config preload (undocumented)
    flags, sel, length = rd.get_bytes(3)   # folded into CRC16
    payload = rd.get_bytes(length)         # folded into CRC16
    # flags MSB (0x80) would mean an embedded CRC; never seen set — assert it.
    # may repeat: the outer command loop handles a following 0x72 naturally.
```

No `check_crc()` inside the handler. Do not special-case single vs double
blocks — the normal opcode loop re-enters on the next `0x72`.
