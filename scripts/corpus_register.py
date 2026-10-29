"""Register vendor corpus builds in corpus_builds (the DB index of corpus/<family>/*).

Derived index: every run DELETEs the family's rows and reinserts from a full rescan of
corpus/<family>/*/design.toml + build outputs (always-rebuild rule).  design.toml is the
on-disk source of truth; this table makes it queryable so builds are reused, not regenerated.

  python3.15t scripts/corpus_register.py --family cycloneiv

Log: tmp/logs/corpus_register.log
"""
import argparse
import datetime
import hashlib
import logging
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import db                      # noqa: E402
import schema                  # noqa: E402
from sqlalchemy import delete, insert  # noqa: E402

log = logging.getLogger("corpus_register")

VERSION_RE = re.compile(r"(Quartus [^\n]*? Version [^\n;]+?)(?:  |\t|$)", re.M)


def toolchain_of(d: Path):
    for rpt in ("fit.rpt", "map.rpt"):
        p = d / rpt
        if p.exists():
            head = p.read_text(errors="replace")[:2000]
            m = VERSION_RE.search(head)
            if m:
                return m.group(1).strip()
    return None


def register(family: str, root=None):
    """root: alternative corpus tree (a rebuild); its fit.rpt Quartus version wins over design.toml's tool_version."""
    alt = root is not None
    root = Path(root) if alt else REPO / "corpus" / family
    if not root.is_dir():
        db.die(f"no corpus dir {root}")
    rows = []
    for d in sorted(root.iterdir()):
        toml_p = d / "design.toml"
        if not d.is_dir() or not toml_p.exists():
            continue
        t = tomllib.loads(toml_p.read_text())
        src = {}
        for f in sorted((d / "src").glob("*")) if (d / "src").is_dir() else []:
            src[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
        outs = [f for f in ("bitstream.rbf", "postfit.vo", "routing.rcf") if (d / f).exists()]
        built = None
        if outs:
            built = datetime.datetime.fromtimestamp(
                max((d / f).stat().st_mtime for f in outs), tz=datetime.timezone.utc)
        rows.append(dict(
            design=d.name, family=family,
            device=t.get("device", ""), top=t.get("top", "top"),
            toolchain=(toolchain_of(d) or t.get("tool_version")) if alt else (t.get("tool_version") or toolchain_of(d)),
            src_sha256=src, qsf=t.get("qsf", []),
            purpose=t.get("purpose"), exercises=t.get("exercises", []),
            built_at=built, out_dir=str(d.relative_to(REPO)) if d.is_relative_to(REPO) else str(d),
            status="ok" if "bitstream.rbf" in outs else "fail:no-bitstream",
        ))
    schema.init()
    with db.engine().begin() as conn:
        conn.execute(delete(schema.corpus_builds).where(schema.corpus_builds.c.family == family))
        if rows:
            conn.execute(insert(schema.corpus_builds), rows)
    ok = sum(1 for r in rows if r["status"] == "ok")
    tc = sum(1 for r in rows if r["toolchain"])
    log.info("%s: %d builds registered (%d ok, %d with toolchain)", family, len(rows), ok, tc)
    return len(rows)


def main():
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(REPO / "tmp/logs/corpus_register.log")])
    ap = argparse.ArgumentParser()
    ap.add_argument("--family", required=True)
    ap.add_argument("--root", default=None, help="alternative corpus tree (default corpus/<family>)")
    args = ap.parse_args()
    register(args.family, args.root)


if __name__ == "__main__":
    main()
