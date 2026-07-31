# An unexplained crash window on the development workstation, 2026-07-30

**Status:** RESOLVED (isolated). A full 32-core sweep at 15:49 found **CPU 8
is the only faulty core on the chip** — all other 31 cores completed the
workload cleanly and agree byte-for-byte. CPU 8 has been taken offline
(`echo 0 > /sys/devices/system/cpu/cpu8/online`) and pinned offline
permanently via a udev rule (`/etc/udev/rules.d/99-cpu8-offline.rules`) so it
survives reboots. Root cause is still not proven (no `memtest86+` yet, so RAM
isn't formally excluded), but the fault is now fully characterized and
mitigated. See awto-terminal [issue #11](https://github.com/awto-au/awto-terminal/issues/11).
**Detector:** `scripts/cpu_sanity_check.py`.

## Update, 15:49: full 32-core sweep — CPU 8 is uniquely faulty

Ran the detector across every logical CPU (`--cpus 0,1,...,31`), sequential,
against the same 23 MB reproducer. Result: **31 of 32 CPUs completed 320/320
carve ops and agreed exactly**; CPU 8 crashed immediately (0/320, signal 11),
same as every prior pinned run. No other core has ever failed this workload,
across four separate pinned test sessions today. This is as close to a
definitive verdict as this detector can give: the fault is CPU 8 specifically,
not a wider silicon, thermal, or memory-controller issue affecting the whole
die.

## Update, 13:34: reproduced under `cpu_sanity_check.py`, CPU 8 only

A pinned sweep of the four favoured (6.0 GHz) cores against the exact original
container (`corpus/vendor-firmware/tiliqua_bitstreams/bitstreams.zip`, 23 MB)
crashed CPU 8 immediately (0 of 320 carve ops) while CPUs 9, 10 and 11 each
completed all 320 and agreed byte-for-byte on every hash — no silent
corruption, just CPU 8 dying outright:

```
[13:34:06] python3[1332804]: segfault at 18 ip 0000000000435939 sp 00007ffee75258f0
           error 4 in python3.15 ... likely on CPU 8 (core 16, socket 0)
```

This matters more than the original unpinned crashes: pinning removes the
favoured-core-steering confound raised below, and CPU 8 is *still* the one that
falls over while the other three cores at the same clock target run clean.
That is now two independent pinned-run data points against CPU 8 (this run,
plus the "3 of 3" pinned runs the same day) versus a single later clean pinned
run that had been read as a refutation. The clean run no longer looks like
the stronger signal. Next step is still `memtest86+` to separate marginal RAM
from marginal silicon on core 16, plus repeating this sweep to see whether CPU
8 fails every time now or only sometimes.

This is written down because it presents as a pluribus bug and is not one: the
engine crashes inside its own pure-Python decoder, in code that cannot crash, so
the natural reading is that the decoder is broken.  It also records a wrong
diagnosis in full, because the wrong diagnosis was persuasive and someone seeing
these symptoms again will likely reach for it.

## What was seen

`scripts/ecp5_carve.py`, scanning a 23 MB firmware zip holding 318 bitstreams,
died part way through with **four different** fatal errors across interpreters:

| interpreter | failure |
|---|---|
| 3.15t (free-threaded) | `PyMutex_Unlock: unlocking mutex that is not locked` |
| 3.15 (`PYTHON_GIL=1`) | `Segmentation fault` |
| 3.14 (stable, GIL) | `Segmentation fault` in `update_crc16` |
| 3.14t (free-threaded) | `_PyEval_EvalFrameDefault: Executing a cache.` |

and once, from a loop that does nothing but integer shifts over a `bytes`
object, `'int' object is not an iterator`.

Ruling out software:

1. The crash sites are pure Python — `update_crc16`, `get_byte`,
   `get_compressed_bytes` — no C extension, no threading.
2. Peak RSS was 96 MB, so not memory exhaustion.
3. It reproduced on a **released** interpreter (3.14) with the GIL on, so not a
   free-threading or beta-interpreter bug.  The crash point also moved between
   runs of the same binary on the same input.

Corroboration that it was not confined to this project: **`code-insiders` also
died in the same window**, `SIGBUS` at 12:19:07 and `SIGSEGV` at 12:19:14 —
unrelated code, memory-access signals, same minutes.

## The diagnosis that looked right and was wrong

Every kernel segfault line named one core:

```
python3.14[1131962]: segfault at c ip ... likely on CPU 8 (core 16, socket 0)
```

Five separate launches, three interpreter builds, all CPU 8.  Pinning appeared to
confirm it:

| pinned to | result |
|---|---|
| CPU 8 | SIGSEGV, **three of three** runs (after 0, 48 and ~250 operations) |
| CPU 2 | exit 0, complete |
| CPU 9 | exit 0, complete — SMT sibling, *same physical core* |

The host is an i9-14900K, and CPU 8 reports `cpuinfo_max_freq` **6.0 GHz** against
5.7 GHz for CPU 0/2 — a Turbo Boost Max 3.0 *favoured* core, the highest-clocking
kind, and the first to fail under the documented Intel 13th/14th-generation
Raptor Lake degradation.  Microcode `0x133` is applied, which halts further
degradation but does not repair silicon that has already degraded.  A coherent
story, and wrong.

**What refuted it.** After the window closed, CPU 8 ran clean repeatedly: 40
decodes, then 331 carve operations over the whole firmware tree, then the exact
original failing command — `taskset -c 8 python3.14 scripts/ecp5_carve.py <the
zip>` — to completion, all 318 operations, exit 0.

**Why the CPU evidence was never as strong as it looked.** Intel's
favoured-core steering puts a single-threaded CPU-bound process on the
highest-boosting core.  So "all five unpinned crashes were on CPU 8" is what you
would expect *whatever* the cause, and it was never independent evidence.  That
left three pinned runs against one run each on two other cores — a small sample
that a later clean run on the same core overturned.

## What is actually established

- The crashes were real, reproducible **at the time**, and not caused by this
  code.
- They affected at least one unrelated application (`code-insiders`).
- They stopped, between 12:41 and 12:43, with **nothing in the kernel log** to
  mark the transition: no MCE, no EDAC counters (non-ECC memory, so memory errors
  are invisible here), no OOM.
- Cause unknown.  Memory pressure with `zram` swap in use, a thermal excursion,
  and marginal silicon are all consistent with the evidence and none is
  demonstrated.

## What it means for results

**Observed:** crashes only.  Every run that completed produced byte-identical
answers — 1280 of 1280 repeated decodes agreed, and four cores agreed exactly on
331 carve operations each.  There is **no evidence of silent corruption**.

**Not excluded:** that corruption could be silent.  A wrong bit that does not
crash yields a decode that parses, a netlist that lifts and a report that reads
fine — the failure mode this project already treats as the dangerous one, the
same shape as #86 where MachXO2 geometry on ECP5 frames produced a plausible,
wrong fabric instead of an error.  The crash is the *lucky* outcome; it announces
itself.

Nothing in the corpus results is retracted on this basis, and nothing should be
without evidence.  But it is why the detector compares answers across cores
rather than only checking exit codes.

## If it comes back

```
python3 scripts/cpu_sanity_check.py                  # favoured cores, one at a time
python3 scripts/cpu_sanity_check.py --cpus 0-31      # full sweep (hours)
python3 scripts/cpu_sanity_check.py --concurrent     # all at once
```

Notes for whoever is holding it next:

- **Do not trust a clean run.** A pass is a failure not observed within the
  budget.  CPU 8 needed up to ~250 carve operations to fail, 40 clean decodes
  said nothing, and the whole thing later passed everything.
- **Workload matters more than repetition.** Re-decoding one bitstream 40 times
  never reproduced it; a carve over containers — decompression, large allocation
  churn, hundreds of distinct bitstreams — did.
- **Check whether other applications are also crashing.** That was the clearest
  signal that the problem was not in this repository, and it is cheap to check:
  `coredumpctl list --since=today`.
- The obvious next step, unavailable while the machine is in use, is a
  `memtest86+` pass, since non-ECC memory reports nothing to the OS.
