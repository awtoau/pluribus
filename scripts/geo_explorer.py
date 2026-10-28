#!/usr/bin/env python3.15t
"""Geo explorer: die map, known cells of one image and package ball grid in ONE self-contained page (tmp/geo/explorer.html).

  python3.15t scripts/geo_explorer.py [--db PATH] [--device EP4CGX150] [--package DF31] [--no-image] [--out FILE]
All views read one payload built by scripts/geo_data.py (schema: docs/geo-data.md), embedded once.  UI sources: scripts/geo_explorer_ui/.
Image layer cache: scripts/geo_image_overlay.py --image <image> (heavy); missing cache = page without the image layer.  Docs: docs/geo-explorer.md.
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "scripts/geo_explorer_ui"
sys.path.insert(0, str(REPO / "scripts"))
import geo_data  # noqa: E402


def page(payload):
    html = (UI / "page.html").read_text().replace("/*__CSS__*/", (UI / "style.css").read_text())
    js = (UI / "app.js").read_text().replace("__DATA__", geo_data.dump(payload).replace("</", "<\\/"))
    return html.replace("/*__JS__*/", js)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db")
    ap.add_argument("--family", default=geo_data.FAMILY, choices=geo_data.geo_devices.FAMILIES)
    ap.add_argument("--device", default=None)
    ap.add_argument("--package", default=None)
    ap.add_argument("--no-image", action="store_true")
    ap.add_argument("--out", default=str(geo_data.GEO / "explorer.html"))
    a = ap.parse_args()
    pl = geo_data.build(a.device, a.package, a.db, not a.no_image, a.family)
    c = geo_data.check(pl, a.db)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = page(pl)
    out.write_text(html)
    print(f"wrote {out}: {c}, image layer {'on' if pl['image'] else 'absent'}, {len(html) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
