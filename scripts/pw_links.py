#!/usr/bin/env python3
"""Fetch a page via the playwrong headed-Chrome engine and print download links.

Usage: pw_links.py <url> [extra-regex-extension ...]
Logs to ./tmp/logs/pw_links.log relative to /mnt/2tb/git/pluribus.
"""
import json
import logging
import os
import re
import sys
import urllib.request

BASE = "http://127.0.0.1:8731"
LOGDIR = "/mnt/2tb/git/pluribus/tmp/logs"
os.makedirs(LOGDIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(os.path.join(LOGDIR, "pw_links.log")),
              logging.StreamHandler(sys.stdout)],
)

DEFAULT_EXTS = ["AppImage", "exe", "dmg", "zip", "rar", "bin", "tar.gz", "7z",
                "jed", "bit", "rbf", "rpd", "svf", "u2p", "uf2"]


def post(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def main():
    if len(sys.argv) < 2:
        print("usage: pw_links.py <url> [ext ...]", file=sys.stderr)
        return 1
    url = sys.argv[1]
    exts = sys.argv[2:] or DEFAULT_EXTS
    post("/goto", {"url": url})
    body = post("/text", {}).get("html", "")
    if "Select all squares" in body or "confirm this search" in body:
        logging.warning("challenge detected, solving")
        post("/solve", {"tries": 20})
        body = post("/text", {}).get("html", "")
    alt = "|".join(re.escape(e) for e in exts)
    pat = r'(?:https?:)?//[^\s"\'<>]*?\.(?:' + alt + r')\b'
    hits = sorted(set(re.findall(pat, body, re.I)))
    logging.info("%s -> %d download links", url, len(hits))
    for h in hits:
        print(h)
    if not hits:
        text = re.sub(r"<[^>]*>", " ", body)
        text = re.sub(r"\s+", " ", text)
        print("--- no links; page text excerpt ---")
        print(text[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
