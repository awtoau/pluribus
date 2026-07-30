# ECP5 introspection primitives: what is usable, and one real gap

The ECP5 exposes a handful of primitives that report on the chip itself rather
than doing user logic. They are worth surfacing over the sideband link and to
the soft CPU, because they answer questions no external instrument can.

## What each one gives you

| primitive | reports | interface |
|---|---|---|
| `DTR` | **die temperature** | `STARTPULSE` in, `DTROUT[7:0]` out |
| `SEDGA` | **soft-error detection** — CRC over the configuration memory | `SEDENABLE`/`SEDSTART` in, `SEDDONE`/`SEDINPROG`/`SEDERR` out |
| `OSCG` | internal oscillator, independent of any PLL | divider parameter |
| `JTAGG` | user JTAG data registers ER1/ER2 | TCK/TDI/TDO taps |
| `GSR`, `SGSR` | global set/reset | |
| `USRMCLK` | the configuration clock pin | the only way to drive SCK after configuration |
| `EXTREFB` | SERDES reference clock | |

`SRAMWB` is listed among ECP5 primitives and looks by name like SRAM with a
Wishbone interface. It is not: its ports are `WDO0..3`/`WADO0..3`, a
slice-level write-data and write-address mux for distributed LUT RAM.

Two are genuinely diagnostic rather than structural:

**`DTR`** gives die temperature with a start pulse and eight bits back. Useful
for the long-run thermal testing the bring-up issue asks for, and it needs no
external sensor.

**`SEDGA`** runs a CRC over the configuration memory and raises `SEDERR` if it
does not match — detecting a bit flip in the loaded bitstream. `CHECKALWAYS`
makes it run continuously in the background. That is the difference between "a
long run failed" and "a long run failed *and* the configuration was corrupt at
the time".

## Open-tool support: everything except SEDGA

Diamond declares 171 ECP5 primitives; yosys's `cells_bb.v` declares 36. Most of
the difference is primitives yosys generates itself — logic gates, LUT and
flip-flop variants, I/O buffers — not gaps.

Checking the introspection primitives specifically:

| primitive | in yosys |
|---|---|
| `DTR` | yes |
| `OSCG` | yes |
| `USRMCLK` | yes |
| `JTAGG` | yes |
| `GSR`, `SGSR` | yes |
| `EXTREFB` | yes |
| **`SEDGA`** | **no** |

So all but one can be instantiated today. `SEDGA` needs a manual `Instance()`
with the port list from Diamond's `SEDGA.v`, and — more importantly — nextpnr
and prjtrellis need to know where its configuration bits live.

## The gap is in the fuzzers, and it is bounded

prjtrellis has **73 ECP5 fuzzers and 54 for MachXO2**, so ECP5 is better
covered overall. But the SED block is one of the places where it is not:

    fuzzers/machxo2/105-sedfa      exists
    fuzzers/ECP5/...-sed*          does not

`102-oscg` and `104-jtagf` are likewise MachXO2-only, though those primitives
are already in yosys for ECP5 by another route.

Adding ECP5 SED support therefore means writing one fuzzer, with a working
MachXO2 equivalent as a template. That needs Diamond to generate the reference
bitstreams — which is installed at `~/lscc/diamond/3.14` — and the fuzzer
infrastructure, which is checked out at `/mnt/2tb/git_mirror/YosysHQ/prjtrellis`
along with a fork under `awtoau/`.

Bounded work with a clear template, not open-ended reverse engineering.
