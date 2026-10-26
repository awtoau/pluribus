#!/usr/bin/env python3
"""Block until FILE has >= N lines matching REGEX, then print the count (agent wait helper).

Polls every 10 s (batch jobs take minutes; a poll costs nothing).  No expiry: the caller's monitor
deadline bounds the wait.

  python3 scripts/wait_for_lines.py FILE REGEX N
"""
import re
import sys
import threading
from pathlib import Path


def main():
    path, rx, n = Path(sys.argv[1]), re.compile(sys.argv[2]), int(sys.argv[3])
    while True:
        lines = path.read_text(errors="replace").splitlines() if path.exists() else []
        hit = sum(1 for ln in lines if rx.search(ln))
        if hit >= n:
            print(f"{hit} matching lines in {path.name}")
            return 0
        threading.Event().wait(10)


if __name__ == "__main__":
    sys.exit(main())
