import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import progress_ledger as pl  # noqa: E402


def test_headline_excludes_sampled():
    row = {"verified": 10, "measured": 5, "sampled": 1000}
    assert pl.headline_exact(row) == 15
    assert pl.headline_exact({"die_verified": 10, "die_measured": 5, "die_sampled": 1000}) == 15
    assert pl.headline_exact({"die_sampled": 7}) == 0    # old row without exact tiers


def test_metrics_keep_sampled_separate():
    assert "die_headline_exact" in pl.METRICS and "die_sampled" in pl.METRICS
    assert "not in headline" in pl.METRICS["die_sampled"][0]
