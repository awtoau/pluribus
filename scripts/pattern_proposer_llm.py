#!/usr/bin/env python3.15t
"""Claude-API pattern PROPOSER (cost-guarded). The model proposes; deterministic code checks; nothing it
says becomes a claim.

  python3.15t scripts/pattern_proposer_llm.py --subject M9K:init:w1            # DRY RUN: prints prompt + token estimate
  python3.15t scripts/pattern_proposer_llm.py --subject M9K:init:w1 --execute  # one paid call (needs the SDK + key)
  python3.15t scripts/pattern_proposer_llm.py --smoke --execute                # trivial prompt, reports cost

Flow: evidence rows -> compact table (training split) -> Claude returns JSON candidates
{kind, params, scope, predictions} -> every candidate is re-fitted/verified by scripts/pattern_matchers.py
against ALL held-out evidence -> only a candidate with zero refutations is written as an EXPECTATION
(matcher id llm-proposer-v1, law.checked_by = the deterministic matcher). Never a claim.

Guards: --max-calls (default 1), --max-output-tokens (default 4096), dry run by default, --execute required,
every call appended to tmp/logs/pattern_proposer_llm_calls.jsonl (prompt hash, usage, cost). Key: read from
~/.config/awto/secrets.yaml, section `anthropic`, key `password` (the name only is ever logged). Models:
claude-opus-5-5 (default) or --cheap -> claude-sonnet-5-5. Prompt caching: the stable system prompt carries
cache_control; the volatile table goes last.
Log: tmp/logs/pattern_proposer_llm.log
"""
import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
from sqlalchemy import select

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import db                                   # noqa: E402
import schema as S                          # noqa: E402
import pattern_matchers as PM               # noqa: E402

log = logging.getLogger("pattern_proposer_llm")
CALLS_LOG = REPO / "tmp/logs/pattern_proposer_llm_calls.jsonl"
SECRETS = Path.home() / ".config/awto/secrets.yaml"
SECRET_SECTION, SECRET_KEY = "anthropic", "password"
MODELS = {"default": "claude-opus-5-5", "cheap": "claude-sonnet-5-5"}
PRICE = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00)}   # $/MTok in, out (claude-api skill, 2026-10)
MATCHER_ID, MATCHER_VERSION = "llm-proposer-v1", 1

SYSTEM = """You are a pattern proposer for FPGA bitstream reverse engineering.
You receive a table of MEASURED specimen results: each row maps an index (or coordinate) to a configuration
cell address (frame, v) inside one device. Propose candidate laws that reproduce the table exactly and would
extend to indices not in the table. Output ONLY a JSON object, no prose:
{"candidates": [{"kind": "bit-linear" | "per-column-offset" | "tile-translate",
                 "params": {...},          // bit-linear: {"frame": [c0, c_b0, c_b1, ...], "v": [c0, c_b0, ...]} integer coefficients over index bits
                 "scope": "where the law should apply (text)",
                 "predictions": {"<index>": [frame, v], ...},   // for EVERY index listed under 'predict for'
                 "confidence": 0.0-1.0, "reasoning": "one line"}]}
Rules: integers only; a law that does not reproduce every training row is useless; prefer the simplest law;
if no law fits, return {"candidates": []}."""


def api_key():
    """Key value from secrets.yaml; only the key NAME is logged. Returns None (with a reason) when absent."""
    if not SECRETS.exists():
        return None, f"{SECRETS} missing"
    try:
        import yaml
    except ImportError:
        return None, "pyyaml not installed"
    sec = yaml.safe_load(SECRETS.read_text()) or {}
    if SECRET_SECTION not in sec:
        return None, f"no [{SECRET_SECTION}] section in secrets.yaml"
    v = (sec[SECRET_SECTION] or {}).get(SECRET_KEY)
    if not v:
        return None, f"secrets.yaml [{SECRET_SECTION}] has no '{SECRET_KEY}' key"
    log.info("api key: secrets.yaml [%s].%s (value not shown)", SECRET_SECTION, SECRET_KEY)
    return str(v), None


def evidence_table(conn, subject, hold_frac=0.2, seed=1):
    """-> (train {index: [f, v]}, held {index: [f, v]}, parent evidence ids)."""
    if not subject.startswith("M9K:init:w"):
        db.die("only M9K:init:w<w> subjects are wired to the evidence table today (extend evidence_table)")
    w = int(subject.rsplit("w", 1)[1])
    m, names = PM.m9k_index_map_from_evidence(conn, "cycloneiv", "EP4CGX150", w)
    if m is None:
        db.die(f"no evidence rows for {subject}; run claims_register.py --family cycloneiv first")
    ev_ids = [r[0] for r in conn.execute(select(S.evidence.c.id).where(S.evidence.c.name.in_(names)))]
    idx = sorted(int(k) for k in m)
    rng = np.random.default_rng(seed)
    hold = set(rng.choice(idx, size=max(1, int(len(idx) * hold_frac)), replace=False).tolist())
    train = {str(i): m[str(i)] for i in idx if i not in hold}
    held = {str(i): m[str(i)] for i in idx if i in hold}
    return train, held, ev_ids


def build_prompt(subject, train, held, max_rows=256):
    rows = sorted(train.items(), key=lambda kv: int(kv[0]))
    if len(rows) > max_rows:   # spread the sample over the index range so every bit of the index is exercised
        step = len(rows) / max_rows
        rows = [rows[int(i * step)] for i in range(max_rows)]
    table = "\n".join(f"{k} {f} {v}" for k, (f, v) in rows)
    predict_for = " ".join(sorted(held, key=int)[:64])
    user = (f"subject: {subject}\ndevice: EP4CGX150 (Cyclone IV GX); address = (frame, v), v in 0..6367\n"
            f"columns: index frame v\n{table}\n\npredict for: {predict_for}\n")
    return user


def estimate_tokens(text):
    return len(text) // 4 + 1   # coarse; the real count comes back in usage


def cost_usd(model, in_tok, out_tok, cached=0):
    pi, po = PRICE[model]
    return (in_tok - cached) * pi / 1e6 + cached * pi * 0.1 / 1e6 + out_tok * po / 1e6


def call_claude(model, user, max_output_tokens, key):
    try:
        import anthropic
    except ImportError:
        db.die("anthropic SDK not installed on this interpreter (pip install anthropic); dry run only")
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=model, max_tokens=max_output_tokens,
        output_config={"effort": "medium"},
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    u = resp.usage
    rec = {"model": model, "request_id": getattr(resp, "_request_id", None), "stop_reason": resp.stop_reason,
           "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
           "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
           "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0}
    rec["cost_usd"] = cost_usd(model, u.input_tokens + rec["cache_read"] + rec["cache_write"], u.output_tokens, rec["cache_read"])
    return text, rec


def parse_candidates(text):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        return []
    try:
        return json.loads(text[start:end + 1]).get("candidates", [])
    except json.JSONDecodeError as e:
        log.error("model output is not JSON: %s", e)
        return []


def check_candidates(cands, train, held, ev_ids, subject):
    """Deterministic gate: refit each candidate's kind on the training rows, verify against ALL held-out rows,
    and compare the model's own predictions. Accept only zero refutations on both."""
    accepted = []
    for i, c in enumerate(cands):
        kind = c.get("kind")
        if kind != "bit-linear":
            log.info("candidate %d: kind %r not checkable yet -> rejected", i, kind)
            continue
        mt = PM.BitLinearLaw()
        cand = mt.propose({"subject": subject, "index_to_cell": train, "parents": ev_ids,
                           "scope": {"space": "cell-param", "kind": "keys", "definition": {"keys": [subject]}}})[0]
        res = PM.verify_all(mt, cand, {int(k): v for k, v in held.items()})
        model_pred = c.get("predictions") or {}
        wrong_pred = [k for k, v in model_pred.items() if k in held and list(held[k]) != list(v)]
        params_match = (c.get("params", {}).get("frame") == cand.law["frame"] and c.get("params", {}).get("v") == cand.law["v"])
        log.info("candidate %d: refit %s; held-out %s; model predictions wrong %d/%d; params %s",
                 i, cand.fit, {k: v for k, v in res.items() if k != "refutations"}, len(wrong_pred), len(model_pred),
                 "identical to refit" if params_match else "differ from refit (model's own law not used)")
        if res["refuted"] == 0 and cand.fit["hits"] == cand.fit["total"] and not wrong_pred:
            cand.law["proposed_by"] = {"matcher": MATCHER_ID, "reasoning": c.get("reasoning"), "confidence": c.get("confidence")}
            accepted.append(cand)
    return accepted


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/pattern_proposer_llm.log")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subject", default="M9K:init:w1")
    ap.add_argument("--execute", action="store_true", help="make the paid call (default: dry run)")
    ap.add_argument("--cheap", action="store_true", help="claude-sonnet-5-5 instead of claude-opus-5-5")
    ap.add_argument("--max-calls", type=int, default=1)
    ap.add_argument("--max-output-tokens", type=int, default=4096)
    ap.add_argument("--max-input-tokens", type=int, default=20000)
    ap.add_argument("--smoke", action="store_true", help="trivial 3-row prompt to prove the key/SDK path; reports cost")
    ap.add_argument("--register", action="store_true", help="write accepted candidates as expectations into the DB")
    a = ap.parse_args()
    model = MODELS["cheap" if a.cheap else "default"]
    commit = PM.__dict__.get("git_head", lambda: "unknown")()

    if a.smoke:
        train = {"0": [1111, 2805], "1": [1111, 2803], "2": [1111, 2801]}
        held, ev_ids = {"3": [1111, 2799]}, []
    else:
        S.init()
        with db.engine().connect() as conn:
            train, held, ev_ids = evidence_table(conn, a.subject)
    user = build_prompt(a.subject, train, held)
    in_est = estimate_tokens(SYSTEM) + estimate_tokens(user)
    log.info("model %s; prompt ~%d input tokens (%d train rows, %d held-out); max output %d; est. cost $%.4f",
             model, in_est, len(train), len(held), a.max_output_tokens, cost_usd(model, in_est, a.max_output_tokens))
    if in_est > a.max_input_tokens:
        db.die(f"prompt estimate {in_est} tokens > --max-input-tokens {a.max_input_tokens}")
    if not a.execute:
        print("=== DRY RUN (pass --execute to call the API) ===")
        print("--- system ---\n" + SYSTEM + "\n--- user ---\n" + user)
        print(f"estimated input tokens {in_est}, max output {a.max_output_tokens}, est. cost <= ${cost_usd(model, in_est, a.max_output_tokens):.4f}")
        return 0
    key, why = api_key()
    if key is None:
        db.die(f"no API key: {why}")
    if a.max_calls < 1:
        db.die("--max-calls < 1")
    text, rec = call_claude(model, user, a.max_output_tokens, key)
    rec.update(ts=PM.F.now().isoformat(timespec="seconds"), subject=a.subject, prompt_sha256=hashlib.sha256(user.encode()).hexdigest()[:16],
               smoke=a.smoke)
    with open(CALLS_LOG, "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    log.info("call: %s", rec)
    cands = parse_candidates(text)
    log.info("model returned %d candidate(s)", len(cands))
    accepted = check_candidates(cands, train, held, ev_ids, a.subject)
    log.info("accepted after deterministic check: %d", len(accepted))
    if accepted and a.register and not a.smoke:
        with db.engine().begin() as conn:
            ids = PM.register_expectations(conn, PM.BitLinearLaw(), accepted, "cycloneiv", "EP4CGX150", commit,
                                           pattern_prefix="llm-proposed", checked_by=PM.BitLinearLaw.id)
            # the expectation rows cite the proposer as matcher for queryability
            for eid in ids:
                conn.execute(S.expectations.update().where(S.expectations.c.id == eid).values(matcher_id=MATCHER_ID)) if \
                    conn.execute(select(S.matchers.c.id).where(S.matchers.c.id == MATCHER_ID)).fetchone() else None
        log.info("registered expectations %s (matcher %s, checked by %s)", ids, MATCHER_ID, PM.BitLinearLaw.id)
    print(json.dumps({"call": rec, "candidates": len(cands), "accepted": len(accepted)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
