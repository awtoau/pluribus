"""Provenance framework: claims / evidence / expectations / unknowns / corpus (docs/provenance-schema.md).

- tiers.py     closed vocabulary, weakest-link rule
- scopes.py    scope definitions -> numpy index arrays (bulk without per-bit rows)
- queries.py   blast-radius and status queries (SQLAlchemy Core)
- feedback.py  refute / confirm / conflict / supersede, audit fan-out, append-only events
- corpus.py    gate ingestion, headline, done criterion, park / reopen
"""
