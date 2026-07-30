#!/usr/bin/env python3
"""Run DuckDuckGo-lite searches through the awto-playwrong headed-Chrome engine.

Usage: pw_search.py "query one" "query two" ...
Logs to ./tmp/logs/pw_search.log relative to /mnt/2tb/git/pluribus.
"""
import sys, json, re, html, urllib.parse, urllib.request, os, logging

BASE = "http://127.0.0.1:8731"
LOGDIR = "/mnt/2tb/git/pluribus/tmp/logs"
os.makedirs(LOGDIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(os.path.join(LOGDIR, "pw_search.log")),
              logging.StreamHandler(sys.stdout)],
)


def post(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def strip_tags(s):
    s = re.sub(r"<[^>]*>", "", s)
    return html.unescape(s).strip()


def search(q):
    url = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote_plus(q)
    post("/goto", {"url": url})
    d = post("/text", {})
    body = d.get("html", "")
    if "Select all squares" in body or "confirm this search" in body:
        logging.warning("captcha for %r, attempting solve", q)
        post("/solve", {"tries": 20})
        d = post("/text", {})
        body = d.get("html", "")
    # DDG lite results: rows with class result-link and result-snippet
    links = re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*class="result-link"[^>]*>(.*?)</a>', body, re.S)
    snips = re.findall(r'class="result-snippet"[^>]*>(.*?)</td>', body, re.S)
    out = []
    for i, (href, title) in enumerate(links):
        snip = strip_tags(snips[i]) if i < len(snips) else ""
        href = html.unescape(href)
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            href = urllib.parse.unquote(m.group(1))
        out.append((strip_tags(title), href, snip))
    return out


def main():
    for q in sys.argv[1:]:
        print("=" * 100)
        print("QUERY:", q)
        try:
            res = search(q)
        except Exception as e:
            logging.error("query %r failed: %s", q, e)
            continue
        if not res:
            print("  (no parsed results)")
        for t, u, s in res[:14]:
            print(f"  - {t}\n    {u}\n    {s[:260]}")
        logging.info("query %r -> %d results", q, len(res))


if __name__ == "__main__":
    main()
