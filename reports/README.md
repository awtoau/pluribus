# reports/ — generated, self-contained HTML reports (open in a browser)

Local outputs; the `.html` files are gitignored (regenerate, do not edit). No network needed.

| file | what | regenerate |
|---|---|---|
| `geo-explorer.html` | EP4CGX150 die map + known cells of one image + 896-ball package view, one data source | `python3.15t scripts/geo_explorer.py` (writes `tmp/geo/explorer.html`; copy here) |
| `coverage.html` | die coverage over time and by type (ledger `docs/coverage-history.jsonl`) | `python3.15t scripts/coverage_page_build.py reports/coverage.html` |

Open: `code-insiders reports/<file>.html` or `xdg-open`.
| `progress.html` | what we know over time: pairs by family, single-cell pairs, claims, beside die coverage (ledger `docs/progress-history.jsonl`) | `python3.15t scripts/progress_ledger.py` |
