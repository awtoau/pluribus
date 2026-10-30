"""Family DBs must agree with schema.py (columns, FKs, indexes); migrate_family_db.py fixes drift (#170)."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import schema  # noqa: E402

LIVE = REPO / "databases" / "cycloneiv" / "gx150.db"
# other family DBs: known drift, migrate when that family is next worked (#170)
OTHERS = ["cyclonev/provenance.db", "ecp5/provenance.db", "gowin/provenance.db",
          "machxo2/provenance.db", "dji_g.db"]


def _drift(path):
    eng = sqlalchemy.create_engine(f"sqlite:///file:{path}?mode=ro&uri=true")
    return schema.drift_report(eng)


@pytest.mark.skipif(not LIVE.exists(), reason="no live cycloneiv DB")
def test_live_cycloneiv_db_matches_schema():
    rep = _drift(LIVE)
    assert rep == {"columns": [], "fks": [], "indexes": []}


@pytest.mark.parametrize("rel", OTHERS)
@pytest.mark.xfail(reason="family DB predates corpus_builds rename; migrate with scripts/migrate_family_db.py (#170)", strict=False)
def test_other_family_dbs_match_schema(rel):
    p = REPO / "databases" / rel
    if not p.exists():
        pytest.skip("absent")
    rep = _drift(p)
    assert rep == {"columns": [], "fks": [], "indexes": []}


def test_migration_is_lossless_and_fixes_stale_fks(tmp_path):
    db = tmp_path / "stale.db"
    eng = sqlalchemy.create_engine(f"sqlite:///{db}")
    schema.metadata.create_all(eng)
    con = sqlite3.connect(db)
    # make it stale: corpus_builds back to postfit_builds, evidence FKs pointing at it
    con.execute("pragma foreign_keys=OFF")
    con.execute("pragma legacy_alter_table=ON")
    con.execute("alter table corpus_builds rename to postfit_builds")
    sql = con.execute("select sql from sqlite_master where name='evidence'").fetchone()[0]
    con.execute("alter table evidence rename to evidence_x")
    con.execute(sql.replace("corpus_builds", "postfit_builds"))
    con.execute("drop table evidence_x")
    con.commit()
    con.close()
    assert _drift(db)["fks"], "fixture must be stale"
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "migrate_family_db.py"),
                        "--db", str(db), "--apply", "--no-backup"],
                       capture_output=True, text=True, env={**os.environ, "PLURIBUS_REPO": str(REPO)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert _drift(db) == {"columns": [], "fks": [], "indexes": []}
