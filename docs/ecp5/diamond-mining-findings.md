# What Lattice Diamond 3.14 knows that the open ECP5 flow does not

Systematic sweep of the locally installed Diamond 3.14 (a local Diamond 3.14 install,
12 GB) for ECP5 data absent from yosys / nextpnr-ecp5 / prjtrellis.

Harvesters live in `scripts/diamond_*.py`; structured output lands in
`tmp/diamond-mine/`, logs in `tmp/logs/`. Everything below was produced by
script, not by browsing.

## Device-tree attribution — READ THIS FIRST

Diamond splits device data by internal tree name, and **the names are a trap**.
`ep5c00` reads like "ECP5" but is **LatticeECP3**. The real ECP5 tree is
`sa5p00`, whose codename bears no resemblance to the marketing name.

Do not guess this from the directory name. The authoritative mapping is
`data/DiamondDevFile.xml`, which states it outright:

```
Family name="ECP5U"      text="sa5p00"      <- LFE5U-12F/25F
Family name="ECP5UM"     text="sa5p00m"
Family name="ECP5UM5G"   text="sa5p00g"
Family name="LatticeECP3" text="ep5c00"     <- NOT ECP5
Family name="LatticeECP2" text="ep5a00"
Family name="LatticeXP"   text="mg5g00"
Family name="MachXO2"     text="xo2c00"
```

and confirms it per part: `Part name="LFE5U-12F-6BG256C" ach="sa5p00"`.

Corroborating evidence: `ispfpga/sa5p00/data/` contains
`LFE5U-12F_CABGA256.con`, `LFE5U-25F_TQFP144.svg` and so on — the actual
LFE5U devices. `ispfpga/ep5c00/data/` contains **no `LFE5U` file at all**.

| tree | family |
|---|---|
| **`sa5p00`** | **ECP5U — LFE5U-12F/25F** |
| `sa5p00m` / `sa5p00g` | ECP5UM / ECP5UM5G |
| `ep5c00`, `ep5c00a` | LatticeECP3 — **not ECP5** |
| `or5g00`, `mg5g00`, `xo2c00`, `se5c00`, … | other families |

`bitgen` accepts only three ECP5 architecture spellings: `ECP5U`, `ECP5UM`,
`ECP5UM5G`. It rejects tree names outright (`bitgen -h ep5c00` errors), which
is why the `bitgen -h` findings below are safe regardless of the tree confusion.

### Consequence for this document

This mistake was in the brief that commissioned the sweep and was propagated
before being caught. **Findings below are tagged with the tree they came from.**
Anything sourced from `bitgen -h ECP5U` or from the webhelp's explicit "ECP5"
tags is unaffected, because those name the family directly. Anything sourced
from files under `ep5c00`/`ep5c00a` describes **LatticeECP3** and must be
re-derived against `sa5p00` before being trusted — this applies to the `.spd`
timing and `.tac` findings, which is called out where it bites.

## Correcting the record

Two open questions from earlier sessions are now settled — one confirming the
prior conclusion, one replacing it.

The general lesson is a source hierarchy. Diamond's **webhelp prose** disagrees
with Diamond's **binaries** in several places, and the binaries win: `bitgen -h
<arch>` is generated from the tables the tool actually uses. The per-device
`.usg` files agree with the binaries **provided you read the right device
tree** — see the attribution warning above; most of the apparent unreliability
in this area turned out to be tree confusion, not stale documentation. Where
prjtrellis has reverse-engineered the same thing from silicon, it has agreed
with the binaries every time it came up here.

**Ranking: `bitgen -h <arch>` / binary strings ≈ correct-tree `.usg` >
prjtrellis bits > webhelp prose > `cae_library` simulation models.**

The simulation models sit last for good reason: they are demonstrably wrong in
both directions (see the SEDGA case below).

### ReadBack / ReadCapture are NOT ECP5 features — prior finding upheld, but for the wrong reason

The webhelp page `Reference Guides/Command Line/running_bit_generation_from_the_command_line.htm`
explicitly tags ReadCapture as applying to ECP5:

> `-g ReadCapture:<value>` … (ECP5, LatticeECP/EC and LatticeXP Only) Optional
> values are Disable (default) and Enable.

That text would overturn the earlier "not ECP5" conclusion. **It is wrong.**
`bitgen -h ECP5U` — the tool's own per-architecture table — lists exactly seven
`-g` options, and ReadBack/ReadCapture are not among them. The earlier
conclusion (reached from the `or5g00`/`mg5g00` tree evidence) was right; the
webhelp prose is unreliable and should not be cited on its own.

### The SEDGA `SED_CLK_FREQ` 77.5 / 155.0 puzzle is explained, and the correct set is now known

The previous session found `cae_library/simulation/verilog/ecp5u/SEDGA.v`
commenting values 77.5 and 155.0 that Diamond's own mapper rejects, and
concluded the simulation models are unreliable documentation.

Where those numbers came from: **77.5 and 155.0 are OSCG frequencies.**
`Reference Guides/FPGA Libraries/oscg.htm` gives the ECP5 oscillator table —
base 310 MHz, `DIV=2 → 155.0 MHz`, `DIV=4 → 77.5 MHz`. SED is clocked from
OSCG, so the model comment appears to have been copied from the oscillator's
top-end range rather than the SED block's own legal set.

The authoritative legal set comes from prjtrellis's bitstream database,
`tiledata/EFB2_PICB0/bits.db` (verified directly):

```
.config_enum SED.CLK_FREQ NONE
  2.4  4.8  9.7  19.4  38.8  62.0  NONE
```

So trellis and Diamond's mapper agree that 77.5 and 155.0 are fiction — **and
trellis additionally documents 62.0, which Diamond's sim-model comment omits
entirely.** The bitstream database is the better reference here. The lesson
generalises: the simulation models are not documentation in *either* direction,
they both overstate and understate.

Trellis also documents `SED.CHECKALWAYS` and `SED.SEDEXCLK_USED`.

## Authoritative ECP5 bitgen options (`bitgen -h ECP5U`)

Identical for `ECP5U`, `ECP5UM`, `ECP5UM5G`. First value is the default.

```
CfgMode     Disable, Flowthrough, Bypass
RamCfg      Reset, NoReset
DONEPHASE   T3, T2, T1, T0
GOEPHASE    T1, T3, T2
GSRPHASE    T2, T3, T1
GWEPHASE    T2, T3, T1
ES          Yes, No
```

**`ispfpga/sa5p00/data/bitgen.usg` (the ECP5 one, dated 2014) matches this
byte for byte**, `-sei` and `GWEPHASE` included. The `.usg` files are not
unreliable — the *ECP3* one is simply not the ECP5 one. The earlier impression
that the shipped usage text was stale and wrong came entirely from reading
`ep5c00/data/bitgen.usg` (dated 2008) under the mistaken belief it was ECP5.
This is worth stating because it changes the source hierarchy: **the ECP5
`.usg` is trustworthy; it was the tree attribution that was broken.**

Two things still to note, both of which catch anyone reading the webhelp prose:

- **`GWEPHASE`**, not `GWDPHASE` as the webhelp spells it. ECP3 genuinely uses
  `GWDPHASE`, so this is a real ECP5-specific rename. The ECP5 `.usg`, the ECP5
  binary help, and prjtrellis (`SYSCONFIG.GWEPHASE`, reverse-engineered from
  silicon) all agree against the prose — three independent sources.
- **`ES` defaults to `Yes` on ECP5** (`ES Yes, No`, first is default), where the
  MachXO2/ECP3 tables list `No, Yes`.

There is also an **undocumented** ECP5 bitgen option: `-g DisableUES:FALSE`
appears on the real bitgen command line in the shipped ECP5 example build, but
in no usage text for any architecture.

None of these seven exist in `ecppack`. They control wake-up sequencing
(the order in which DONE, output enable, global set/reset and global write
disable are released), which is exactly the area governing whether a design
comes up cleanly after configuration.

## Findings ranked by what they would change

### 0. SEDGA works in the open flow up to the final step — two small patches away

Traced end to end, empirically, not by inspection:

1. yosys has **no** `SEDGA` in `share/yosys/ecp5/cells_bb.v` →
   `ERROR: Module '\SEDGA' ... is not part of the design`.
2. Adding a 9-line blackbox declaration (ports taken from Diamond's `SEDGA.v`)
   → yosys synthesises cleanly, emits `1 SEDGA` cell.
3. `nextpnr-ecp5` **already knows SEDGA as a real bel** — the chipdb has the bel
   and the full port list (`SEDSTDBY`, `SEDENABLE`, `SEDSTART`, `SEDFRCERR`,
   `SEDDONE`, `SEDINPROG`, `SEDERR`; confirmed present in the binary). It
   reports `SEDGA: 1/1 100%` and places and routes it successfully.
4. It then aborts in the bitstream writer:
   `Assertion failure: unsupported cell type (ecp5/bitstream.cc:1559)`.

So SEDGA needs a yosys blackbox declaration **and** a nextpnr `bitstream.cc`
case. Placement, routing and the underlying bit definitions all already exist.

This is listed first because it is the only finding here that is both
immediately actionable and directly useful to this project: for a board that
boots from flash, having the FPGA continuously self-check its own configuration
memory is a real robustness feature currently sitting behind a small patch.

Contrast with `PLLREFCS` and `IMIPI`, which are absent from nextpnr's chipdb
entirely — no bel, no string. Those are genuine silicon-support gaps, not
declaration gaps, and are much larger pieces of work.

### 1. ECP5 package and I/O topology in plain text — `sa5p00/data/*.con`

**Tree: `sa5p00` (ECP5U). Zero reverse engineering required.**

45 `.con` files, one per part+package, including every LFE5U-relevant
device: `LFE5U-12F_CABGA256.con`, `LFE5U-25F_CABGA256.con`, `_TQFP144`,
`_CSFBGA285`, `_QFN88`, … Each row is quoted-attribute plain text:

```
IO      ID="70" X="30" Y="63" SITE="PL2A" PIN_NAME="B1" BANK="7" SIDE="left"
        DIFF_PAIR="True_OF_PL2B" TRUE_LVDS="TRUE" MIPI="false"
IOLOGIC ID="71" X="50" Y="63" SITE="IOL_L2A" IO="70" DQS="0" DQS_GROUP="8"
```

That is die X/Y coordinates, internal site name, package ball name, bank, die
side, differential pairing with polarity, true-LVDS capability, MIPI
capability, and DQS group — plus `DQSLOGIC`, `DLLDEL`, `DDRDLL`, `CLKDIV`,
`ECLK`, `ECLKBRIDGE`, `GXPLL` and `BANKID` site rows. LFE5U-25F: 443 rows,
197 I/O, banks 0/1/2/3/6/7/8, 64 true-LVDS pairs.

This is the complete package and clock/DDR topology for the exact part on the
board, readable today. Extracted to `tmp/diamond-mine/con/*.json`.

### 2. Timing data: Diamond has vastly more of it, and the format is decoded

**Tree: the ECP5 files are `sa5p00/data/sa5p25.spd`, `sa5p45.spd`, `sa5p85.spd`
(16 MB each, dated 2024).** Note `sa5p25` is the LFE5U-25F die — a common
part.

Format, fully worked out: 128-byte header, then **exactly 5 speed-grade
sections**, each marked `0xAAAA` plus a version tag. Records are
`<4 × int32be delay><u8 len><NAME>\0<u16be len><CONDITION>\0 0xFF`.
**Raw delay units are picoseconds × 1024** — dividing by 1024 yields clean
quarter-picosecond values across every arc, which is itself strong evidence the
scaling is right.

Roughly 20,500 arcs per grade (~102,000 per device), 136 distinct arc names,
~10,300 unique (name, condition) pairs per grade. Conditions are rich attribute
selectors, e.g. `IO_TYPE=LVCMOS33,DRIVE=12,SLEWRATE=FAST,BANK_VCCIO=3.3` and
`CLKMUX:CLK:::CLK=#INV MODE:IDDRX1_ODDRX1`.

That the 5 sections are speed grades was confirmed by checking that delays rise
monotonically across them for arcs that should scale.

Scale of the gap against prjtrellis `speed_6`:

| | prjtrellis | Diamond `.spd` |
|---|---|---|
| timing entries | **1051** (33 cell variants, 8 cell types) | ~10,300 conditioned arcs **per grade** |
| interconnect classes | 371 | — |
| I/O standards covered | **10** | **34** |
| speed grades shipped | 4 (`speed_6/7/8/8_5G`) | 5 per file |
| vintage | 2025-02 files, older upstream data | 2024 vendor data |

I/O standards in Diamond but **missing from trellis**: BLVDS25(E), HSUL12(D),
LVCMOS25D, LVCMOS33D, LVDS25E, LVPECL33(E), LVTTL33(D), MIPI, MLVDS25(E),
SLVS, SSTL135(D)_I/II, SSTL15D_I/II, SSTL18D_I/II, SUBLVDS.

**Caveats, stated plainly.** The picosecond scaling was validated by magnitude
agreement against trellis (Diamond `CLK_MPW` 337.75/500 ps vs trellis
IOLOGIC/SLOGICB `Width` 525/1050 ps) and by the quantisation being exactly
clean at ÷1024 — but **the arc-name-to-trellis-entry semantic mapping is not
established**. Numbers should be spot-checked against the published datasheet
before being trusted in a timing model. Separately, an earlier parse of the
*wrong* tree (`ep5c00a`, i.e. ECP3) reached 96.3% byte coverage but never
produced EBR/DSP arcs; whether the ECP5 parse has the same blind spot has not
been re-checked.

**`sa5p00/data/sa5p00.tac` is the schema** — 96 KB of **plain text** declaring
every primitive configuration with its ports, pin roles and named timing arcs.
No reverse engineering needed to read it.

This is the largest body of data recovered: timing errors are invisible until a
design mysteriously fails, and the open flow's model is thin by comparison —
particularly on I/O standards, where trellis covers under a third of what the
vendor characterises.

### 2. Soft Error Injection — an entire workflow with no open equivalent

`bitgen` on ECP5 supports options with no `ecppack` equivalent whatsoever. Both
the ECP5 `.usg` (`sa5p00/data/bitgen.usg`) and `bitgen -h ECP5U` document them;
the webhelp's bitgen page does not mention `-sei` at all, which is why casual
reading missed it:

```
-sei <type>   Inject soft error in a bitstream frame.
              random: Pick a random bit
              unused: Pick a random bit in an unused site
-site <stype> When "-sei unused", select site type: PFU, EBR, DSP, ANY
```

`-sei` is confirmed present in the `bitgen` binary's strings and confirmed
**absent** from `ecppack`. `User Guides/Implementing the Design/Analyzing_Using_SEI.htm`
documents the SEI Editor GUI workflow and lists **ECP5U and ECP5UM** among
supported devices.

Combined with `-m <format>` (mask/readback file generation, ECP5-valid per both
the webhelp and the binary), this is a complete configuration-memory integrity
testing capability that the open flow cannot reproduce.

Note that SED *itself* is well supported in the open flow — `ecppack` knows
`SEDGA` and all its ports, nextpnr knows `SEDGA`, and trellis has the full SED
routing (`JSEDDONE_SED`, `JSEDERR_SED`, `JSEDINPROG_SED`, `SEDSTDBY_OSC` …) in
`tiledata/EFB0_PICB0/bits.db`. The gap is specifically the *injection and mask
file* tooling, not the primitive.

### 3. `-crc frame|global` — per-frame CRC, ECP5-valid, absent from ecppack

From the universal file writer (`ddtcmd`) reference:

> `-crc <frame|global>`: The "frame" option includes the CRC checking for each
> data frame. The "global" option disables the frames CRC but still calculates
> the global CRC at the end of the configuration data. **Valid for ECP5**…

`ecppack` has CRC16 insert/check machinery but exposes no frame-vs-global
control. Relevant to any work on bitstream robustness or on understanding
configuration failures.

### 4. OSCG divider table — 65 legal ratios the open flow does not validate

`Reference Guides/FPGA Libraries/oscg.htm` gives the full ECP5 table: base
310 MHz, DIV 2–128, but **non-contiguous above 32** (…32, 34, 36, 38, 40, 42,
44, 46, 48, 50, 52, 54, 56, 58, 60, 62, 64, 68, 72, 76, 80, 84, 88, 92, 96,
100, 104, 108, 112, 116, 120, 124, 128) — 65 legal values, each with its
typical frequency.

yosys declares `OSCG` with `parameter DIV = 128` and **no validation**.
prjtrellis encodes `OSC.DIV` as a 127-value enum in `tiledata/EFB0_PICB0/bits.db`,
but many of those values share identical bit patterns — i.e. the database maps
values the hardware cannot actually distinguish. Diamond's table tells you
which ones are real. Setting an unlisted DIV in the open flow silently gives
you a different frequency than you asked for.

The same 22-value frequency list appears in `ddtcmd` as the legal ECP5 MCCLK
set: 2.4, 3.2, 4.1, 4.8, 6.5, 8.2, 9.7, 12.9, 15.5, 16.3, 19.4, 20.7, 25.8,
31, 34.4, 38.8, 44.3, 51.7, 62, 77.5, 103.3, 155 MHz.

### 5. ECP5 primitives the open flow cannot instantiate

`Reference Guides/FPGA Libraries/ecp5u_um.htm` is the ECP5-specific primitive
list — better evidence than `cae_library/simulation/verilog/ecp5u/`, which
carries models Diamond's own mapper rejects. 143 primitives listed.

After excluding soft macros (gates, generic flip-flops, ROMs, muxes — yosys
infers these and needs no blackbox), and excluding I/O buffers (yosys maps
these from generic IO), the real gaps are:

| primitive | in nextpnr | in trellis | note |
|---|---|---|---|
| `PRADD18A`, `PRADD9A` | no | no | DSP pre-adders |
| `MULT9X9C`, `MULT9X9D`, `MULT18X18C` | no | no | DSP multiplier variants (yosys has only `MULT18X18D`) |
| `ALU24A`, `ALU24B`, `ALU54A` | no | no | DSP ALUs (yosys has only `ALU54B`) |
| `PLLREFCS` | no bel | routing only | PLL dynamic reference clock switching — see note below |
| `IMIPI` | no | no | MIPI input support |
| `BCINRD`, `BCLVDSOB`, `INRDB` | no | no | dynamic bank controllers |
| `START` | no | yes | startup controller |

On `PLLREFCS` specifically, be careful not to overstate what trellis has.
`tiledata/PLL0_*/bits.db` contains PLLREFCS **routing** entries
(`.fixed_conn N1_CLK0_PLLREFCS N1_REFCLK0`, `N1_JSEL_PLLREFCS`, …), so the mux
into the PLL is mapped — but nextpnr's chipdb has **no PLLREFCS bel**. It is
therefore not merely a missing declaration like SEDGA; it needs bel definition
work as well. Closer than a from-scratch primitive, further than SEDGA.

The DSP gaps matter for anyone wanting the full sysDSP feature set; the open
flow supports one multiplier (`MULT18X18D`) and one ALU shape (`ALU54B`) out of
several.

**Where yosys is not behind — a negative result worth recording.** For every
ECP5 hard block yosys *does* declare, its parameter set matches Diamond's
synthesis model exactly, including `DCUA` at all **265** parameters, plus
`JTAGG`, `EXTREFB`, `PCSCLKDIV`, `DTR` and `EHXPLLL`. There is no
parameter-richness gap to close on the SERDES or the PLL. Two apparent extras
(`EHXPLLL.FIN`, `DDRDLLA.LOCK_CYC`) exist only in the *simulation* model and
not the synthesis model — testbench annotations with no silicon bits. Not worth
chasing.

Also note `ecp5u`, `ecp5um` and `ecp5um5g` synthesis models are **byte-identical**
(same md5). ECP5 has one primitive library; the -UM/-5G difference is
device-level (SERDES presence and rate), not cell-level.

### 6. sysCONFIG: 9 ECP5 attributes Diamond sets have no bits in prjtrellis

Diamond's ECP5 sysCONFIG set (cross-checked three ways: `ep5c00/data/edif2ngd.prp`,
the `SYSCONFIG.htm` rows tagged ECP5, and a real LFE5U-25F build under
`examples/Reveal_debugger/counter_reveal_ECP5/`) is 17 attributes.

Every `SYSCONFIG.*` key in the entire prjtrellis ECP5 database is 11 (verified
by grep over `database/ECP5/tiledata/*/bits.db`):

```
BACKGROUND_RECONFIG  DONE_EX  DONEPHASE  GOEPHASE  GSRPHASE  GWEPHASE
MASTER_SPI_PORT  SLAVE_PARALLEL_PORT  SLAVE_SPI_PORT  TRANSFR  WAKE_UP
```

**In Diamond for ECP5, no bits in trellis:** `MCCLK_FREQ`, `CONFIG_SECURE`,
`COMPRESS_CONFIG`, `DONE_OD`, `DONE_PULL`, `CONFIG_IOVOLTAGE`, `CONFIG_MODE`,
`PERSISTENT`, `INBUF`.

Two deserve singling out because they look supported but are not:

- **`MCCLK_FREQ`** — the string appears in the `ecppack` binary and `--freq`
  exists, but there are **zero MCCLK bits anywhere in the ECP5 trellis
  database**. Worth verifying what `ecppack --freq` actually encodes.
- **`CONFIG_SECURE`** — readback lockout. Diamond: when ON, no readback is
  supported through the sysCONFIG or ispJTAG port. No trellis bits, so an
  open-flow ECP5 bitstream cannot set the readback-disable bit at all.

Note this list independently corroborates `GWEPHASE` over the webhelp's
`GWDPHASE` — trellis, reverse-engineered from silicon, uses the same spelling
the binary does.

Separately, nextpnr *does* accept 15 SYSCONFIG keys on its input (it parses
`SYSCONFIG <attr>=<value>`), so the front-end is not the bottleneck; the missing
bit definitions are.

### 6b. ECP5 bitstream opcodes and configuration sequencing — `ECP5.xfp`

**Directly relevant to this project's recorded INITN / reconfigure-from-flash
problem.** `data/vmdata/database/xpga/ecp5/ECP5.xfp` (6.8 KB XML, ECP5-specific
by path) gives the bitstream command opcode table in plain text:

```
PREAMBLE = hBDB3          ENCRYPTION_PREAMBLE = hFFFFBAB3
VERIFYID = hE2            CONTROLREG0 = h22
RESETADDR = h46           WRITEINC = hB8
USERCODE = hC2            PROGRAMSECURE = hCE
PROGRAMDONE = h5E         CLEARALL = h0E
COMMAND_INFO_CRC_OFF = h000000   COMMAND_INFO_CRC_ON = h800000
```

Note `COMMAND_INFO_CRC_ON/OFF` — this is the bitstream-level encoding of the
`-crc frame|global` option in finding 3, so that option is not merely a tool
flag but a documented bitstream field.

The same file carries the explicit PROGRAMN/INITN/DONE ordering script
(PROG low → INIT low → DONE low → PROG high → INIT high). Given that a prior
session concluded "reconfigure-from-flash cannot work — INITN is never
released", this is the vendor's own statement of the intended sequence and is
worth checking that conclusion against.

Alongside it: `LFE5U-45F.msk` / `LFE5U-85F.msk`, 1–1.9 MB bitstream-shaped mask
files beginning `ff 00 "Lattice Semiconductor Corporation Bitstream"`.

### 7. `bstool` — vendor bitstream disassembler and BFD dumper

`ispfpga/bin/lin64/bstool` runs once given Diamond's environment (it needs
`LD_LIBRARY_PATH` to find `libbasbs.so`). Confirmed working; usage captured:

```
-x <arch> <f1> <f2>    Convert <arch> bitfile to NeoCAD format.
-c/-r <file1> <file2>  Compare two NeoCAD bitfiles (binary / raw ASCII).
-d <bitfile>           Dump a NeoCAD bitfile.
-i <bitfile>           Print info about a NeoCAD bitfile.
-a                     Write an ascii BFD file (must precede -b)
-b <arch> <asc> <bin>  Write a binary BFD file.
-s <bitfile> {<soifile>}  Print a soisim file.   -l  create location file
-t <bitfile>           Test the BFD against a bitfile
```

The **BFD is the bitstream frame database** — the tile-to-bit mapping that
prjtrellis reverse-engineered by experiment.

**This works.** The invocation is `bstool -a -b <arch> <in.bfd> <out.asc>`
(despite the usage text reading `-b <arch> <asc> <bin>`), run from a directory
containing a writable copy of the input:

```
LD_LIBRARY_PATH=<diamond>/bin/lin64:<diamond>/ispfpga/bin/lin64 \
FOUNDRY=<diamond>/ispfpga \
bstool -a -b ECP5U ep5c00.bfd out.asc
```

Run against the **correct ECP5 tree** (`sa5p00/data/sa5p00.bfd`, 7.8 MB) this
produced **13 MB of readable ASCII** describing **198 tile types**, each with
its geometry, site list and node table:

```
# ECP5U Bitfile Description
Tile "PLC" Rows=12 Columns=106 Rams=1272 Nodes=264
{
   Sites { SLICE_A Row=19, SLICE_B Row=18, SLICE_C Row=17, ... }
   Nodes { A0 = JA0, A1 = JA1, CE0 = JCE0, CLK0 = JCLK0, ... }
}
```

`SLICE_A/B/C` is the ECP5 slice naming, confirming the right device (the ECP3
tree gives different sites and a different bitstream status line — 10.27 for
ECP5 vs 1.133 for ECP3, a useful sanity check).

**Cross-checked against prjtrellis, and the result is reassuring:**

| | count |
|---|---|
| tile types in vendor BFD | **198** |
| tile types in trellis `tiledata/` | 185 |
| in both | **185** |
| in trellis but not in the vendor BFD | **0** |
| in the vendor BFD only | 13 |

**prjtrellis is a strict subset of the vendor database** — it invented nothing
and got no tile name wrong. The 13 it lacks are `PLC`, `PVT_COUNT`,
`DUMMY_TILE_3`, `BMID_0`, `BMID_1` and eight `BANKREF*X` bank-reference
variants. That is a strong independent endorsement of trellis's accuracy, and
it narrows the remaining reverse-engineering surface to a named, finite list.

For anyone extending the trellis ECP5 database this is a direct route to vendor
ground truth for the tile-bit mapping.

### 8. ECP5 cannot encrypt its primary bitstream

`ddtmain` contains the literal string **"ECP5 does not support the encrypted
primary."** This is a hard silicon/tooling constraint rather than an open-flow
gap, and it bounds what any ECP5 secure-boot design can do. Consistent with
`bitgen -h ECP5U` omitting `-e`/`-s`/`-k`. Caveat: a real ECP5 `.bgn` in the
examples tree does show `-e -s -k` on the bitgen command line, so the flags are
accepted for ECP5 — the restriction is specifically on the *primary* image.

### 6. Package pinout and geometry data is decodable

The `.pkg`, `.hrg`, `.grf`, `.nph`, `.bxg`, `.tld` files are **zlib-compressed**
and inflate to a self-describing tagged format with plain-text headers
(`Format Version: 9.1`, creation dates, device names) and readable site/port
name tables (`APIO`, `IOLOGIC`, `IOLDO`, `ECLKDQSR`, `DDRCLKPOL`, …).

Package pinouts were successfully recovered — e.g. for `ep5c00a`, packages
`FPBGA256/484/672/1152/1156`, `FTBGA256`, `TQFP144` with 1452–1748 ball records
each. Relevant to the ECP5 lifter work: this is vendor geometry data in a
tractable format, not an opaque blob.

## What was examined

- **`docs/webhelp/eng/`** — all 2092 HTML pages harvested to JSONL with text and
  2105 extracted tables. Fully swept.
- **`bin/lin64/` and `ispfpga/bin/lin64/`** — CLI tools run with a correctly
  reconstructed Diamond environment; `bitgen` per-architecture help captured
  for every architecture it admits to.
- **`.usg` usage files** — harvested across all device trees, attributed. Mostly
  thin (13–26 lines each) and, for ECP5, **stale**: the shipped `bitgen.usg` is
  dated 2008 against a 2024 tool.
- **`ispfpga/sa5p00/data/` (the real ECP5 tree)** — `.con` package/IO topology
  extracted to JSON for all 45 part+package combinations; `.spd` timing parsed;
  `.bfd` dumped to ASCII via `bstool` and diffed against trellis; `.tac` read.
- **`ispfpga/ep5c00*/data/`** — swept before the tree error was caught. This is
  **LatticeECP3** data; retained only as format-discovery work, since the
  container formats are shared across families.
- **`data/vmdata/database/xpga/ecp5/`** — `ECP5.xfp` config opcodes and
  sequencing read; `LatticeECP5.svp` and `ispVM_023.xdf` previously known.
- **`cae_library/`** — ECP5 sim (157) and synthesis (146) models diffed against
  yosys, including a parameter-level three-way classification against trellis.
- **`examples/`** — all 13 projects inventoried, primitive instantiations and
  constraints extracted. Result is thin: only **one** targets ECP5
  (`SimpleDesign_ECP5U`, LFE5U-45F), a trivial 4-bit adder with **zero**
  primitive instantiations. The other 12 target MachXO2/ECP2/ECP3/XP2/SC and
  their primitives do not transfer. The example tree's only ECP5 value was the
  `.sty` bitgen property list and the real `.bgn`/`.prf` command lines.
- **`micosystem/` (629 MB)** — inventoried and sampled. Largely MachXO2/Platform
  Manager oriented; `dualboot/` and `ascboot/` are built on the hard EFB that
  ECP5 does not have. There is **no USB IP** anywhere in it. One item of
  architectural interest: `components/sefb/` (Soft EFB), Lattice's own soft
  I2C+SPI replacement for the hard EFB, Wishbone-attached with tri-state
  break-outs designed to arbitrate SPI access against another master — a
  directly comparable problem to sharing SPI flash between a SoC and the
  configuration engine. Note its licence header is proprietary; read for
  architecture, do not copy.
- **`share/trellis/database/ECP5/`, yosys `cells_bb.v`, `ecppack`/`nextpnr-ecp5`
  strings** — used as the cross-reference baseline throughout.

## What was not examined

- **The per-tile bit contents of the BFD.** The 13 MB ASCII dump gives tile
  types, geometry, sites and node tables. Mapping individual configuration bits
  to trellis's `bits.db` entries was not attempted.
- **`.hrg`/`.nph` contents** — format characterised (multi-stream zlib,
  self-describing, ~4300 streams inflating to 70 MB of site/wire names), but not
  extracted into a usable routing graph.
- **Whether the ECP5 `.spd` parse has the same EBR/DSP blind spot** as the ECP3
  parse did. The ECP3 run reached 96.3% byte coverage yet produced no `EBSR_CO`
  arcs; the ECP5 run has not been checked for the same gap.
- **`questasim/`, `synpbase/`, `module/`** — third-party simulator and Synplify
  install trees, judged out of scope.
- **`ddtcmd`/`ddtcmain`** — menu-interactive, yields no useful non-interactive
  usage. Its capabilities were inferred from `ddtmain` strings only, so the
  multiboot/golden-image and CRC/ACA-compression items from that binary are
  **leads, not confirmed ECP5 capabilities** — `ddtmain` is family-generic.
- **Anything under `ep5c00`/`ep5c00a` was ECP3 and is not reported here** except
  where explicitly flagged. The early part of this sweep was spent on the wrong
  tree.

## Where the next pass should start

1. **Re-audit any earlier session's conclusions that cite `ep5c00`.** That tree
   is LatticeECP3. This sweep caught the error for its own findings, but prior
   work may carry it.
2. **Check the ECP5 `.spd` parse for the EBR/DSP blind spot** seen in the ECP3
   run, using `.tac` arc names such as `EBSR_CO` as the search target.
3. **Compare recovered per-arc delays against
   `share/trellis/database/ECP5/timing/` entry by entry.** The tile comparison
   showed trellis is a strict subset structurally; the open question is whether
   the *numbers* agree. Any systematic disagreement is a real correctness bug.
   Establish the arc-name-to-trellis-entry mapping first.
4. **The 13 tiles trellis lacks** — `PLC`, `PVT_COUNT`, `BMID_0/1`, eight
   `BANKREF*X`. Now a named, finite list rather than an unknown.
5. Verify what `ecppack --freq` encodes, given there are no MCCLK bits anywhere
   in the ECP5 trellis database.
6. SEDGA: yosys blackbox + nextpnr `bitstream.cc` case (see finding 0).
7. Check the `ECP5.xfp` PROGRAMN/INITN/DONE sequence against the earlier
   "reconfigure-from-flash cannot work" conclusion.
