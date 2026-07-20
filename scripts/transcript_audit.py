#!/usr/bin/env python3
"""Extract the reviewable content from a Claude Code session transcript.

A session .jsonl is dominated by tool results (tens of MB).  For auditing
"was everything we discussed actually tracked?", only two things matter:

  * genuine HUMAN messages  — what was asked / promised
  * assistant PROSE         — what was claimed / concluded

Everything else (tool calls, tool results, system reminders, hook noise) is
dropped.  Writes a compact digest to tmp/ for review.

Usage:
  python3 scripts/transcript_audit.py <transcript.jsonl> [--out tmp/audit.md]
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Injected wrappers that are NOT the human speaking.
_NOISE = (
    "<system-reminder>", "<task-notification>", "[SYSTEM NOTIFICATION",
    "<ide_opened_file>", "<ide_selection>", "<command-name>",
    "Caveat: The messages below", "This session is being continued",
)


def _text_blocks(content):
    """Yield text from a message content field (str or list-of-blocks)."""
    if isinstance(content, str):
        yield content
        return
    if not isinstance(content, list):
        return
    for b in content:
        if isinstance(b, dict) and b.get("type") == "text":
            yield b.get("text", "")


def _is_human(text):
    """True if this looks like the user actually typing, not an injection."""
    t = text.strip()
    if not t:
        return False
    return not any(t.startswith(n) or n in t[:200] for n in _NOISE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--out", default="tmp/transcript_audit.md")
    ap.add_argument("--max-assistant", type=int, default=600,
                    help="truncate each assistant prose block to N chars")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    humans, prose = [], []
    for i, ln in enumerate(open(args.transcript, errors="replace")):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        typ = d.get("type")
        msg = d.get("message") or {}
        if typ == "user":
            # skip tool_result-only turns
            content = msg.get("content")
            if isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content):
                continue
            for t in _text_blocks(content):
                if _is_human(t):
                    humans.append((i, t.strip()))
        elif typ == "assistant":
            for t in _text_blocks(msg.get("content")):
                t = t.strip()
                if len(t) > 80:            # skip one-liner chatter
                    prose.append((i, t[:args.max_assistant]))

    with out.open("w") as fh:
        fh.write(f"# Transcript audit — {args.transcript}\n\n")
        fh.write(f"human messages: {len(humans)} | assistant prose blocks: {len(prose)}\n\n")
        fh.write("## HUMAN MESSAGES (the asks — authoritative)\n\n")
        for i, t in humans:
            fh.write(f"### line {i}\n{t}\n\n")
        fh.write("\n## ASSISTANT PROSE (claims / conclusions, truncated)\n\n")
        for i, t in prose:
            fh.write(f"--- line {i} ---\n{t}\n\n")

    print(f"humans={len(humans)} prose={len(prose)} -> {out}")
    print(f"digest size: {out.stat().st_size/1e6:.2f} MB")


if __name__ == "__main__":
    sys.exit(main())
