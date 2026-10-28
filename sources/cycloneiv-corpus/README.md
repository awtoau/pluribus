# Cyclone IV third-party image corpus (binaries gitignored)

- Manifest: `manifest.json` (URL, commit/tag, licence, SHA-256, size, analysis). Table: `docs/cycloneiv-corpus.md`.
- Rebuild: `python3.15t scripts/cycloneiv_corpus_fetch.py --fetch --analyze`; check: `--verify`.
- Good copy: SHA-256 equals the manifest; `--analyze` reports valid CRAM CRCs; frame signature per `docs/cycloneiv-corpus.md`.
- One directory per image; `.derived.rbf` = `quartus_cpf` conversion of the `.sof` beside it.
