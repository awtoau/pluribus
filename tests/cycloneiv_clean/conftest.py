"""Shared helpers: repo on sys.path, oracle report log (tmp/logs/cycloneiv_clean_oracles.log), skip on missing local data."""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
LOG = os.path.join(REPO, "tmp", "logs", "cycloneiv_clean_oracles.log")
VA = os.path.join(REPO, "vendor-analysis", "altera")


def report(name, **kv):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = f"{name} {json.dumps(kv, sort_keys=True)}"
    with open(LOG, "a") as f:
        f.write(line + "\n")
    print(line)


def need(*paths):
    for p in paths:
        if not os.path.exists(p):
            pytest.skip(f"local data missing: {os.path.relpath(p, REPO)}")


@pytest.fixture(scope="session")
def tables():
    from lifters.cycloneiv_clean import plane as P
    try:
        return P.load_tables()
    except P.TablesMissing as e:
        pytest.skip(str(e))


@pytest.fixture(scope="session")
def routing():
    from lifters.cycloneiv_clean import ddb
    try:
        return ddb.Routing()
    except ddb.DdbMissing as e:
        pytest.skip(str(e))


@pytest.fixture(scope="session")
def asm():
    from lifters.cycloneiv_clean import ddb
    try:
        return ddb.Asm()
    except ddb.DdbMissing as e:
        pytest.skip(str(e))
