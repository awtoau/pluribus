# reports/ — generated, self-contained HTML reports (open in a browser)

Local outputs; the `.html` files are gitignored (regenerate, do not edit). No network needed.

| file | what | regenerate |
|---|---|---|
| `geo-explorer.html` | EP4CGX150 die map + known cells of one image + 896-ball package view, one data source | `python3.15t scripts/geo_explorer.py` (writes `tmp/geo/explorer.html`; copy here) |
| `coverage.html` | the ONE progress page: what we know (pairs, single cells, claims; `docs/progress-history.jsonl`) plus die coverage over time and by type (`docs/coverage-history.jsonl`) | `python3.15t scripts/progress_ledger.py` (appends a row, rebuilds the page) |

Open: `code-insiders reports/<file>.html` or `xdg-open`.
