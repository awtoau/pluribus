"""Pluribus — shared database helpers.

Two connection helpers:
  connect_pg8000()  — pure Python (pg8000), NoGIL-safe, for reach.py workers
  connect()         — psycopg2, for all other scripts (load, build, reach2, fuzz)

Shared constants and utilities:
  die(msg)          — print FATAL and sys.exit(1)
  EFB_JF            — {int → port_name} map for EFB JF ports
  JF_RE             — compiled regex matching JF<n> wire names
"""

import os
import re
import sys

# ── Connection parameters (shared across both drivers) ────────────────────────
_DB   = os.environ.get("PGDATABASE",   "fpga_re")
_USR  = os.environ.get("PGUSER",       os.environ.get("USER", "dan"))
_SOCK = os.environ.get("PGUNIXSOCKET", "/run/postgresql/.s.PGSQL.5432")
_DSN  = os.environ.get("PLURIBUS_DSN", f"dbname={_DB} user={_USR}")


def connect_pg8000():
    """pg8000 native connection — pure Python, safe in python3.14t NoGIL workers."""
    import pg8000.native
    return pg8000.native.Connection(database=_DB, user=_USR, unix_sock=_SOCK)


def connect():
    """psycopg2 connection — for single-threaded scripts (load, build, reach2, fuzz)."""
    import psycopg2
    return psycopg2.connect(_DSN)


# ── Shared utilities ──────────────────────────────────────────────────────────

def die(msg):
    """Print FATAL message and exit 1. Never returns."""
    print(f"\nFATAL: {msg}", file=sys.stderr)
    sys.exit(1)


# EFB JF port index → canonical port name
EFB_JF = {0: "JTCK", 1: "JTDI", 2: "JUPDATE", 3: "JRSTN",
           4: "JSHIFTDR", 5: "JTDO", 6: "JF6", 7: "JF7"}

# Matches wire names like "JF0" .. "JF7" in arc lists
JF_RE = re.compile(r'^JF(\d)$')
