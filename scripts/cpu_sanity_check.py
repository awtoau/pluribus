#!/usr/bin/env python3
"""Find CPU cores that crash, or silently compute WRONG answers.

WHY THIS EXISTS
---------------
`scripts/ecp5_carve.py` died mid-scan on a 23 MB firmware zip with three
different fatal errors on three interpreter builds:

    PyMutex_Unlock: unlocking mutex that is not locked   (3.15t)
    _PyEval_EvalFrameDefault: Executing a cache.         (3.14t)
    Segmentation fault in update_crc16                   (3.14, 3.15, 3.15t)

plus, once, `'int' object is not an iterator` raised out of a loop that only
does integer shifts over a `bytes` object.  Pure-Python arithmetic cannot do
any of that, and the crash point moved between runs of the SAME binary on the
SAME input.  Every kernel segfault line named the same core:

    python3.14[1131962]: segfault ... likely on CPU 8 (core 16, socket 0)

Pinning appeared to settle it.  Same interpreter, same input, 318 operations:

    taskset -c 8  ->  SIGSEGV (three of three runs, after 0, 48 and ~250 ops)
    taskset -c 2  ->  exit 0, complete
    taskset -c 9  ->  exit 0, complete       (SMT sibling of 8, same core 16)

THAT CONCLUSION WAS WRONG, and the correction is the reason this file explains
itself at length.  Once the crash window closed, CPU 8 ran 40 decodes, then 331
carve operations over the whole firmware tree, then the exact original failing
command, all clean.  The apparent CPU attribution had a mundane explanation:
Intel's favoured-core steering places a single-threaded CPU-bound process on the
highest-boosting core -- CPU 8 here, 6.0 GHz against 5.7 -- so "every unpinned
crash was on CPU 8" is expected whatever the cause, and was never independent
evidence.  What remained was three pinned runs against one apiece elsewhere, and
a later clean run on the same core overturned it.

The crashes were real; the cause is unidentified and is NOT known to be a core.
See docs/hardware-cpu-fault.md.  Treat this script as a detector for "is the
machine currently computing correctly", not as proof about any particular CPU.

THE CRASH IS THE LUCKY FAILURE MODE
-----------------------------------
A core that segfaults announces itself.  A core that returns one wrong BIT and
keeps going does not -- it produces a decode that parses, a netlist that lifts,
and a report that reads fine.  That is the exact failure this project treats as
the dangerous one: #86 was MachXO2 geometry applied to ECP5 frames, and the
carver's own note warns that naming a part from the IDCODE alone "does not fail
loudly -- it produces a plausible, wrong fabric".  A degraded core is that
hazard in hardware, underneath every claim the engine makes.

So this script measures BOTH: it counts crashes AND it compares answers.

METHOD
------
Both workloads are the real engine, not a synthetic benchmark, because what
broke is specific code:

  `carve`  -- scan a firmware container end to end (`ecp5_carve.scan_blob`):
              unzip, ungzip, then decode every bitstream found.  This is the
              reproducer.  DEFAULT.
  `decode` -- re-decode one bitstream `--repeats` times.  Fast, and useful for a
              quick check, but it does NOT reproduce: CPU 8 ran 40 clean decodes
              of a 358 KB design while failing the carve three times out of
              three.  Repetition is not what provokes the fault; the carve's
              mix of decompression, large allocation churn and hundreds of
              different bitstreams is.

Both are deterministic, so the answer is checkable and not merely present: the
same container must always yield the same set of carves, and the same bytes the
same CRAM.  Workers print a SHA-256 per unit of work, unbuffered, so a worker
killed by a signal still reports how far it got.  The reference is a majority
vote across CPUs rather than a stored constant -- no trusted baseline is needed,
and one bad core cannot outvote the rest.

CPUs are tested ONE AT A TIME by default.  The reasoning is weaker than it first
appeared and is stated honestly: an all-cores-busy sweep found nothing (32 CPUs,
1280 decodes, unanimous), but so did every sequential run once the window closed,
so that clean sweep is not evidence that load hides the fault.  Sequential is
kept as the default for two defensible reasons -- it lets each core reach its
single-core boost, which is the condition the original crashes occurred under,
and it attributes a failure to one CPU instead of leaving thermals as a
confound.  `--concurrent` trades that attribution for speed.

    python3 scripts/cpu_sanity_check.py [--cpus 8,9,10] [--workload decode]
                                        [--container FILE] [--repeats N]

With no `--cpus`, only the highest-boosting cores are tested: those are the
Turbo Boost Max favoured cores, the ones that degrade first, and a full 32-CPU
carve sweep would take hours.  Pass `--cpus` explicitly to widen it.

Logs to ./tmp/logs/cpu_sanity_check.log; JSON to tmp/cpu_sanity_check.json.

A clean sweep is NOT proof of health -- it is a failure not observed within the
budget.  A dirty sweep is proof of a fault.
"""
import argparse
import concurrent.futures
import glob
import hashlib
import json
import logging
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))

# CPU 8 crashed after 0, 48 and roughly 250 carve operations in three pinned
# runs, so a single carve pass (318 operations on the container used here) sits
# above the largest observed failure count and is the natural unit.  The decode
# workload needs a repeat count instead, and 40 keeps it under a minute -- but
# note 40 clean decodes on CPU 8 proved nothing, which is why carve is default.
DEFAULT_REPEATS = {"carve": 1, "decode": 40}


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


def find_bitstream(log):
    """A decodable .bit to use as the workload.

    Prefers the commercial carves and the ECP5 corpus, both gitignored, then any
    Diamond build under tmp/.  Order is by descending likelihood of being
    present rather than by design size: the workload only has to be long enough
    to run the hot loop for a while, and every ECP5 bitstream is.
    """
    for pat in ("corpus/commercial/*.bit", "corpus/ecp5/*.bit",
                "corpus/diamond/*/*/*.bit", "tmp/**/*.bit"):
        hits = sorted(glob.glob(os.path.join(REPO, pat), recursive=True))
        if hits:
            log.info("workload: %s (from %s)", os.path.relpath(hits[0], REPO),
                     pat)
            return hits[0]
    sys.exit("no .bit found for the workload; pass --bitstream FILE explicitly "
             "(corpus/ is gitignored, so a fresh checkout has none)")


def find_container(log):
    """Firmware to carve.  A directory is walked, exactly as ecp5_carve does.

    Defaults to the whole corpus/vendor-firmware/ tree because that IS the run
    that failed, and because size is a poor proxy for how much work a container
    holds: a 154 MB AppImage yields 6 bitstreams in 25 seconds, while a 23 MB zip
    yields 318 over four minutes.  Duration at boost is what provokes the fault,
    so picking "the biggest file" tests the machine for a quarter of a minute and
    proves nothing.
    """
    tree = os.path.join(REPO, "corpus", "vendor-firmware")
    if os.path.isdir(tree) and any(os.scandir(tree)):
        n = sum(len(fs) for _r, _d, fs in os.walk(tree))
        log.info("carve container: %s (%d file(s), walked)",
                 os.path.relpath(tree, REPO), n)
        return tree
    sys.exit("no firmware under corpus/vendor-firmware/; pass --container "
             "FILE|DIR, or use --workload decode")


def favoured_cpus(log):
    """CPUs with the highest `cpuinfo_max_freq`, plus their SMT siblings.

    Turbo Boost Max 3.0 nominates a couple of cores to boost higher than the
    rest -- here 6.0 GHz against 5.7 -- and those are the ones that degrade
    first, so they are where to look before spending hours on all 32.  Siblings
    are included because a defect in a physical core need not present on both
    of its threads: CPU 8 failed three of three runs while CPU 9, on the same
    physical core, passed.
    """
    freqs = {}
    for cpu in sorted(os.sched_getaffinity(0)):
        f = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/cpuinfo_max_freq"
        try:
            with open(f) as fh:
                freqs[cpu] = int(fh.read().strip())
        except OSError:
            continue
    if not freqs:
        log.info("no cpufreq data; testing every online CPU")
        return sorted(os.sched_getaffinity(0))
    top = max(freqs.values())
    picked = sorted(c for c, f in freqs.items() if f == top)
    log.info("highest-boosting CPUs at %.1f GHz: %s (of %d with cpufreq data)",
             top / 1e6, _mask(picked), len(freqs))
    return picked


def cram_digest(pb):
    """Fingerprint of a decoded bitstream.

    Covers the configuration memory and the header fields a wrong answer would
    most plausibly corrupt.  Frame order is fixed by the geometry, so this is
    stable across runs by construction.
    """
    h = hashlib.sha256()
    for row in pb.cram:
        h.update(row)
    h.update(repr((pb.idcode, pb.usercode, pb.ctrl0, pb.frames_read,
                   pb.num_frames, len(pb.records))).encode())
    return h.hexdigest()


def worker_decode(repeats, path, device):
    """Decode one bitstream `repeats` times, printing a hash per decode."""
    import native_bitstream as nb
    geom = nb.geometry_for(device)
    with open(path, "rb") as fh:
        raw = fh.read()
    stripped = nb.strip_bit_header(raw)
    for _ in range(repeats):
        pb = nb.parse(stripped, geom=geom)
        # Unbuffered: a worker killed by a signal must still have reported
        # every decode it completed, since how far it got is the measurement.
        print(cram_digest(pb), flush=True)


def worker_carve(repeats, container):
    """Scan a firmware container `repeats` times, hashing each bitstream found.

    Prints one hash per carve rather than one per pass, so a worker that dies
    part way through still shows how many bitstreams it got through -- which is
    the number that distinguished CPU 8 (0, 48, ~250) from a clean pass (318).
    """
    import logging as _logging
    import ecp5_carve as ec
    quiet = _logging.getLogger("cpu_sanity_check.carve")
    quiet.addHandler(_logging.NullHandler())
    quiet.propagate = False
    idcodes = ec._ecp5_idcodes(ec._idcode_table())
    if os.path.isdir(container):
        paths = sorted(os.path.join(r, f)
                       for r, _d, fs in os.walk(container) for f in fs)
    else:
        paths = [container]
    for _ in range(repeats):
        for path in paths:
            with open(path, "rb") as fh:
                data = fh.read()
            for rec in ec.scan_blob(data, os.path.basename(path), idcodes,
                                    quiet, families=ec.ALL_FAMILIES):
                h = hashlib.sha256(rec.get("_payload") or b"").hexdigest()
                # Identity as well as content: a carve landing at the wrong
                # offset or claiming the wrong device is as wrong as bad bytes.
                print(hashlib.sha256(
                    f"{rec.get('origin')}|{rec['start']}|{rec['length']}|"
                    f"{rec.get('family')}|{rec.get('device')}|{h}".encode()
                ).hexdigest(), flush=True)


def worker(args):
    """Pin to a CPU and run the chosen workload."""
    os.sched_setaffinity(0, {args.cpu})
    if args.workload == "carve":
        worker_carve(args.repeats, args.container)
    else:
        worker_decode(args.repeats, args.bitstream, args.device)
    return 0


def run_one(cpu, args, path, device):
    """Spawn a pinned worker.  Returns a result dict; never raises."""
    cmd = [sys.executable, os.path.abspath(__file__), "--worker",
           "--cpu", str(cpu), "--repeats", str(args.repeats),
           "--workload", args.workload, "--bitstream", path,
           "--device", device, "--container", args.container]
    p = subprocess.run(cmd, capture_output=True, text=True)
    hashes = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]
    return {"cpu": cpu, "returncode": p.returncode, "completed": len(hashes),
            "hashes": hashes, "stderr": p.stderr.strip()[-400:]}


def classify(results, log):
    """Majority-vote the correct answer, then judge each CPU against it.

    The expected amount of work is taken as the most work any CPU completed,
    not a configured constant: a carve pass yields as many hashes as the
    container holds bitstreams, which is not known ahead of time.  A CPU that
    stopped early therefore stands out without needing the count declared.
    """
    tally = {}
    for r in results:
        for h in r["hashes"]:
            tally[h] = tally.get(h, 0) + 1
    if not tally:
        sys.exit("no CPU produced a single result; the workload itself is "
                 "broken, not the CPUs")
    # For `carve` each unit of work has its OWN digest, so a set is expected and
    # cross-CPU comparison is per-position; for `decode` every digest is the
    # same.  Comparing sorted multisets covers both without special-casing.
    expected = max(len(r["hashes"]) for r in results)
    ref_lists = {}
    for r in results:
        if len(r["hashes"]) == expected:
            key = tuple(sorted(r["hashes"]))
            ref_lists[key] = ref_lists.get(key, 0) + 1
    reference = max(ref_lists, key=lambda k: ref_lists[k]) if ref_lists else ()
    log.info("reference: %d result(s) per CPU, %d of %d full-length CPU(s) "
             "agree exactly", expected, max(ref_lists.values(), default=0),
             sum(ref_lists.values()))
    if len(ref_lists) > 1:
        log.error("CPUs DISAGREE on a deterministic workload: %d distinct "
                  "full-length answers", len(ref_lists))
    refset = set(reference)
    for r in results:
        # Anything this CPU produced that no agreeing CPU produced is a wrong
        # answer -- corruption that did not crash, the dangerous case.
        r["wrong"] = len([h for h in r["hashes"] if h not in refset])
        r["short"] = len(r["hashes"]) < expected
        # A signal kill reports as a negative returncode; distinguish it from a
        # clean non-zero exit, which would be our own error path rather than the
        # CPU misbehaving.
        r["crashed"] = r["returncode"] < 0
        r["signal"] = -r["returncode"] if r["crashed"] else None
        if r["wrong"]:
            r["verdict"] = "WRONG ANSWERS"
        elif r["crashed"]:
            r["verdict"] = f"CRASHED (signal {r['signal']})"
        elif r["returncode"] != 0 or r["short"]:
            r["verdict"] = f"INCOMPLETE (rc={r['returncode']})"
        else:
            r["verdict"] = "ok"
    return reference


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workload", choices=("carve", "decode"), default="carve",
                    help="carve a container (reproduces; default) or re-decode "
                         "one bitstream (fast, does NOT reproduce)")
    ap.add_argument("--repeats", type=int, default=0,
                    help="units of work per CPU (default: 1 carve pass, or "
                         "40 decodes)")
    ap.add_argument("--cpus", default="",
                    help="comma-separated CPUs (default: highest-boosting only)")
    ap.add_argument("--bitstream", default="", help="decode workload .bit")
    ap.add_argument("--container", default="",
                    help="carve workload firmware container")
    ap.add_argument("--device", default="",
                    help="device for the geometry (default: from the IDCODE)")
    ap.add_argument("--concurrent", action="store_true",
                    help="test all CPUs at once.  HIDES this fault -- see the "
                         "module docstring; kept only to demonstrate that")
    ap.add_argument("--json", default=os.path.join(REPO, "tmp",
                                                   "cpu_sanity_check.json"))
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--cpu", type=int, default=0, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if not args.repeats:
        args.repeats = DEFAULT_REPEATS[args.workload]

    if args.worker:
        sys.exit(worker(args))

    log = setup_logging("cpu_sanity_check")
    path = args.bitstream or find_bitstream(log)
    device = args.device
    if not device:
        from ecp5_corpus_test import identify
        device, family, idc, how = identify(path)
        if not device:
            sys.exit(f"cannot identify {path}: {how}; pass --device explicitly")
        log.info("workload device %s (%s, idcode 0x%08x, via %s)", device,
                 family, idc or 0, how)
    if args.workload == "carve" and not args.container:
        args.container = find_container(log)

    cpus = ([int(c) for c in args.cpus.split(",") if c.strip()]
            or favoured_cpus(log))
    log.info("%s workload, %d unit(s) per CPU, %d CPU(s): %s",
             args.workload, args.repeats, len(cpus), _mask(cpus))
    if args.concurrent:
        log.warning("--concurrent: all CPUs at once drops every core to "
                    "all-core turbo, which HID this fault entirely (32 CPUs, "
                    "1280 decodes, unanimous).  Expect a false clean.")
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(cpus)) as ex:
            futs = [ex.submit(run_one, c, args, path, device) for c in cpus]
            results = [f.result() for f in futs]
    else:
        # One at a time, so the CPU under test reaches its single-core boost
        # with the rest of the machine idle.  That is the provoking condition.
        results = [run_one(c, args, path, device) for c in cpus]
    results.sort(key=lambda r: r["cpu"])

    reference = classify(results, log)

    bad = [r for r in results if r["verdict"] != "ok"]
    expected = max(r["completed"] for r in results)
    log.info("---- per-CPU ----")
    for r in results:
        line = (f"  CPU {r['cpu']:>3}  {r['completed']:>4}/{expected} "
                f"{args.workload} op(s)  {r['verdict']}")
        (log.error if r["verdict"] != "ok" else log.info)(line)
        if r["verdict"] != "ok" and r["stderr"]:
            log.error("        %s", r["stderr"].replace("\n", " | ")[-300:])

    good = [r["cpu"] for r in results if r["verdict"] == "ok"]
    with open(args.json, "w") as fh:
        json.dump({"reference_ops": len(reference), "repeats": args.repeats,
                   "workload": args.workload, "container": args.container,
                   "bitstream": os.path.relpath(path, REPO), "device": device,
                   "concurrent": args.concurrent,
                   "bad_cpus": [r["cpu"] for r in bad], "good_cpus": good,
                   "results": [{k: v for k, v in r.items() if k != "hashes"}
                               for r in results]}, fh, indent=2, sort_keys=True)
    log.info("results -> %s", args.json)

    if not bad:
        log.info("no fault observed on %d CPU(s) (%s). That is a failure not "
                 "seen in this budget, NOT proof of health -- the 2026-07-30 "
                 "crashes took up to ~250 carve operations to appear, 40 clean "
                 "decodes said nothing, and they later stopped on their own "
                 "(docs/hardware-cpu-fault.md).", len(cpus), _mask(cpus))
        return 0
    log.error("%d of %d CPU(s) FAULTY: %s", len(bad), len(results),
              [r["cpu"] for r in bad])
    log.error("run pluribus off them until the CPU is dealt with, e.g.")
    log.error("    taskset -c %s python3.15t scripts/<stage>.py ...",
              _mask(good))
    log.error("a core that returns wrong answers without crashing corrupts "
              "results silently, so treat anything computed on %s as suspect",
              [r["cpu"] for r in bad])
    return 1


def _mask(cpus):
    """Compact taskset list, e.g. [0,1,2,5] -> '0-2,5'."""
    out, i = [], 0
    while i < len(cpus):
        j = i
        while j + 1 < len(cpus) and cpus[j + 1] == cpus[j] + 1:
            j += 1
        out.append(str(cpus[i]) if j == i else f"{cpus[i]}-{cpus[j]}")
        i = j + 1
    return ",".join(out)


if __name__ == "__main__":
    sys.exit(main())
