#!/usr/bin/env python3.15t
"""Name carved 802.16 regions with a LOCAL Ollama model (#189 crawl step 2).  Free: no cloud API.

  python3.15t scripts/cycloneiv_clean_region_name.py --blob 802.16-tx [--blob 802.16-rx] --model gpt-oss:20b [--top N] [--only rid,..] [--redo]
Reads tmp/cycloneiv_clean/regions/<blob>/{index.json, <rid>.md, <rid>.json}; writes names/<model>/<rid>.json (raw reply + parsed answer + timing)
and names/<model>/recarve.json (unknown regions > RECARVE_LUT LUTs).  Log tmp/logs/cycloneiv_clean_region_name.log.
Order: most informative first (LFSR/CRC > ROM contents > MAC > carry chains > known-block neighbours); names already given (known blocks + this
model's earlier answers) are passed as neighbour context.  Answers are proposals only: scripts/cycloneiv_clean_region_verify.py gates V.
Ollama: http://localhost:11434 /api/chat, stream, JSON schema, temperature 0, num_ctx 16384.
"""
import argparse
import collections
import json
import logging
import os
import socket
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RG = os.path.join(REPO, "tmp", "cycloneiv_clean", "regions")
URL = os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/chat"
log = logging.getLogger("region_name")
STALL_S = 60              # repo rule for host processes: no token for 60 s after the first = hung -> abort the call
LOAD_S = 300              # first call per model: model load from disk + first prompt eval (18 GB qwen3-coder ~1 min measured class); 5x margin
NUM_CTX = 16384           # fact sheet (<= 150 lines) + neighbours + system prompt ~ 4-6k tokens; 16k leaves room for gpt-oss reasoning
RECARVE_LUT = 300

SYSTEM = """You identify the function of one region of a lifted FPGA netlist: the ground-unit baseband of DJI Lightbridge, an OFDM-class
radio link (ground receives the video downlink, transmits a narrow uplink). Use 802.16e PHY stage vocabulary, but take every size, width,
length and polynomial ONLY from the fact sheet, never from expectations about 802.16e or this product. The region's clock-domain container
name (802.16-rx / 802.16-tx) says NOTHING about direction: decide rx vs tx from the evidence, or use 'glue'/'unknown'.

Stage vocabulary (use these words in names): randomiser / descrambler (PRBS x^15+x^14+1), pilot-prbs (x^11+x^9+1), crc16 / crc8 / crc32,
fec-cc-encoder, viterbi-acs, viterbi-traceback, ctc, rs-encoder, rs-decoder, bit-interleaver, deinterleaver, qam-mapper, demapper,
soft-decision, subcarrier-map, pilot-insert, pilot-extract, ifft, fft, fft-butterfly, twiddle-rom, bitrev-addr, cp-insert, cp-strip,
preamble-correlator, sync-detect, agc, cfo-estimate, cfo-correct (nco/cordic), timing-estimate, channel-estimate, equaliser, fir-filter,
decimator, interpolator, sample-fifo, symbol-buffer, frame-buffer, rate-adapt-fifo, mac-header, frame-timer, hop-control, uplink-framer,
duml-path, video-path, control-regs, glue, unknown.

Name format: 802.16-rx-<stage>[-<detail>] or 802.16-tx-<stage>[-<detail>] (e.g. 802.16-rx-fft-butterfly, 802.16-tx-randomiser), or
glue-<what>, or unknown. Prefer 'unknown' over a guess: a wrong confident name is worse than unknown.

EVIDENCE RULES (a script checks every name against the sheet and DEMOTES it to a plain structural label if the rule fails):
  - randomiser / descrambler / pilot-prbs / crc*: only if the sheet has an "LFSR / CRC groups" entry. No entry = never these names.
  - fft / ifft / twiddle-rom / bitrev-addr: only if the sheet has M9K contents or a MAC.
  - viterbi / rs / ctc / fec / interleaver: only if the sheet has an M9K.
  - frame-timer / counter: only if the sheet has a carry chain.
  - any other function name (mac-header, cp-insert, mapper, framer, ...): only if a neighbour listed as "known block" supports it.
  - A name must be backed by evidence lines COPIED VERBATIM from the sheet. Many regions are plain adders, registers or RAM buffers with no
    visible function: for those say 'unknown' and describe the structure in evidence. Do not reuse one function name for many regions.

predicted_test: ONE concrete deterministic check the verifier can run, exactly one of:
  lfsr_poly=x^A+x^B+1 | crc_poly=x^16+x^12+x^5+1 | rom_shape=cos|sin|ramp|step|decay|bitrev|gf_log | counter_terminal=N |
  fifo=1 | mac_chain=1 | xor_taps=N | sim_vector=<free text>
Only claim an lfsr/crc/rom test that the fact sheet's own LFSR/M9K lines support.
evidence: short quotes of the fact-sheet lines you relied on. confidence: 0..1.
Reply with JSON only."""

SCHEMA = {"type": "object", "required": ["name", "confidence", "evidence", "predicted_test", "neighbours_to_visit"],
          "properties": {"name": {"type": "string"}, "confidence": {"type": "number"},
                         "evidence": {"type": "array", "items": {"type": "string"}},
                         "predicted_test": {"type": "string"},
                         "neighbours_to_visit": {"type": "array", "items": {"type": "string"}}}}


GATES = [   # (name keywords, required fact-sheet feature)
    (("randomiser", "descrambler", "pilot-prbs", "crc"), lambda fs: bool(fs["lfsr"]), "no LFSR/CRC group"),
    (("fft", "twiddle", "bitrev"), lambda fs: fs["counts"]["mac"] > 0 or any(m["contents"] and "all-zero" not in m["contents"][0] for m in fs["m9k"]),
     "no MAC or ROM contents"),
    (("viterbi", "rs-", "ctc", "fec", "interleaver"), lambda fs: fs["counts"]["m9k"] > 0, "no M9K"),
    (("frame-timer", "counter"), lambda fs: bool(fs["carry_chains"]), "no carry chain"),
]
NEUTRAL = ("glue", "unknown", "frame-buffer", "symbol-buffer", "sample-fifo", "rate-adapt-fifo", "control-regs", "duml-path", "video-path")


def structure_label(fs):
    c = fs["counts"]
    if c["mac"]:
        return f"mac{c['mac']}"
    if c["m9k"]:
        return f"mem{c['m9k']}"
    if fs["carry_chains"]:
        return f"adder{len(fs['carry_chains'])}"
    return "logic"


def gate_name(name, fs):
    """-> (gated name, reason or ''). Function names need a matching feature in the sheet; otherwise a structural label."""
    n = (name or "unknown").lower()
    if n == "unknown" or n.startswith(("glue", "unknown")) or any(k in n for k in NEUTRAL[3:]):
        return name, ""
    for keys, ok, why in GATES:
        if any(k in n for k in keys):
            return (name, "") if ok(fs) else (f"struct-{structure_label(fs)}", f"{name}: {why}")
    known = any(not e["peer"].startswith(("802.16", "unknown", "unassigned")) for e in fs["cut_in"] + fs["cut_out"])
    return (name, "") if known else (f"struct-{structure_label(fs)}", f"{name}: no feature and no known neighbour")


def info_score(fs):
    s = 100 * len(fs["lfsr"])
    s += sum(80 for m in fs["m9k"] if m["contents"] and "all-zero" not in m["contents"][0])
    s += 10 * fs["counts"]["mac"] + 5 * fs["counts"]["m9k"] + 3 * len(fs["carry_chains"])
    s += 5 * sum(1 for e in fs["cut_in"] + fs["cut_out"] if not e["peer"].startswith(("802.16", "unknown", "unassigned")))
    return s


def neighbour_block(fs, names, index):
    hl = {r["id"]: r["headline"] for r in index["regions"]}
    rows = []
    for side, lab in (("cut_in", "from"), ("cut_out", "to")):
        for e in fs[side][:10]:
            p = e["peer"]
            if p in names:
                d = f"named '{names[p]}' (proposed)"
            elif p.startswith("802.16") or p.startswith("unknown"):
                d = f"unnamed: {hl.get(p, '?')[:110]}"
            else:
                d = "known block"
            rows.append(f"- {lab} {p}: {e['bits']} bits; {d}")
    return "\n".join(rows)


def chat(model, system, user, limit_s, think):
    body = dict(model=model, stream=True, format=SCHEMA, messages=[dict(role="system", content=system), dict(role="user", content=user)],
                options=dict(temperature=0, num_ctx=NUM_CTX))
    if think is not None:
        body["think"] = think
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0, first, out, thinking, stats = time.time(), None, [], 0, {}
    with urllib.request.urlopen(req, timeout=LOAD_S) as r:      # socket timeout LOAD_S until the first token, STALL_S after
        for line in r:
            now = time.time()
            if first is None:
                first = now - t0
                try:
                    r.fp.raw._sock.settimeout(STALL_S)
                except AttributeError:
                    pass
            if now - t0 > limit_s:
                raise TimeoutError(f"overall limit {limit_s:.0f}s exceeded after {now - t0:.0f}s (first token at {first:.1f}s)")
            j = json.loads(line)
            m = j.get("message") or {}
            out.append(m.get("content") or "")
            thinking += len(m.get("thinking") or "")
            if j.get("done"):
                stats = {k: j.get(k) for k in ("total_duration", "prompt_eval_count", "eval_count", "eval_duration")}
    return "".join(out), dict(first_token_s=round(first or 0, 2), wall_s=round(time.time() - t0, 2), thinking_chars=thinking, **stats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blob", action="append", required=True)
    ap.add_argument("--model", default="gpt-oss:20b")
    ap.add_argument("--top", type=int, default=0, help="only the N most informative regions per blob (0 = all)")
    ap.add_argument("--only", default="", help="comma list of region ids")
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--tag", default="", help="suffix for the output folder (e.g. v2) so a new prompt never overwrites an earlier pass")
    ap.add_argument("--think", default="auto", help="gpt-oss reasoning level low|medium|high; 'auto' = low for gpt-oss, off otherwise")
    a = ap.parse_args()
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_region_name.log"))])
    think = ("low" if a.model.startswith("gpt-oss") else None) if a.think == "auto" else (None if a.think == "off" else a.think)
    mtag = a.model.replace(":", "_").replace("/", "_") + (f"-{a.tag}" if a.tag else "")
    limit = LOAD_S
    walls = []
    for blob in a.blob:
        index = json.load(open(os.path.join(RG, blob, "index.json")))
        od = os.path.join(RG, blob, "names", mtag)
        os.makedirs(od, exist_ok=True)
        facts = {r["id"]: json.load(open(os.path.join(RG, blob, f"{r['id']}.json"))) for r in index["regions"]}
        order = sorted(facts, key=lambda rid: (-info_score(facts[rid]), rid))
        if a.only:
            order = [r for r in order if r in set(a.only.split(","))]
        elif a.top:
            order = order[:a.top]
        names = {}
        for fn in os.listdir(od):
            if fn.startswith(blob) and fn.endswith(".json"):
                ans = (json.load(open(os.path.join(od, fn))).get("answer") or {})
                if ans.get("name"):
                    names[fn[:-5]] = ans["name"]
        recarve = []
        n_done = n_err = 0
        for k, rid in enumerate(order, 1):
            path = os.path.join(od, f"{rid}.json")
            if os.path.exists(path) and not a.redo:
                continue
            md = open(os.path.join(RG, blob, f"{rid}.md")).read()
            user = f"{md}\n## Neighbours\n{neighbour_block(facts[rid], names, index)}\n\nName this region. JSON only."
            rec = dict(rid=rid, model=a.model, think=think, prompt_chars=len(SYSTEM) + len(user))
            try:
                raw, st = chat(a.model, SYSTEM, user, limit, think)
                rec.update(st, raw=raw)
                walls.append(st["wall_s"])
                limit = max(60.0, 3 * max(walls))          # overall per-call limit = 3x the slowest measured call
                try:
                    ans = json.loads(raw)
                    rec["json_valid"] = isinstance(ans, dict) and all(f in ans for f in SCHEMA["required"])
                    rec["answer"] = ans if isinstance(ans, dict) else None
                except json.JSONDecodeError:
                    rec["json_valid"], rec["answer"] = False, None
            except (TimeoutError, socket.timeout, OSError) as e:
                rec.update(error=f"{type(e).__name__}: {e}", json_valid=False, answer=None)
                n_err += 1
                log.error("%s %s: %s (limit %.0fs)", a.model, rid, rec["error"], limit)
            json.dump(rec, open(path, "w"), indent=1)
            n_done += 1
            ans = rec.get("answer") or {}
            if ans.get("name"):
                ans["model_name"] = ans["name"]
                ans["name"], why = gate_name(ans["name"], facts[rid])
                ans["gate_demoted"] = why
                json.dump(rec, open(path, "w"), indent=1)
                names[rid] = ans["name"]
                if ans["name"] == "unknown" and facts[rid]["counts"]["lut"] > RECARVE_LUT:
                    recarve.append(rid)
            log.info("%s [%d/%d] %s -> %s (%.2f) test=%s  %.1fs", a.model, k, len(order), rid, ans.get("name"), ans.get("confidence") or 0,
                     ans.get("predicted_test"), rec.get("wall_s") or -1)
        json.dump(recarve, open(os.path.join(od, "recarve.json"), "w"))
        log.info("%s %s: %d called, %d errors, recarve %d", blob, a.model, n_done, n_err, len(recarve))


if __name__ == "__main__":
    main()
