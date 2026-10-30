"""Shared loader for the hard-block score functions (scripts/cycloneiv_clean_hardblocks_score.py); skips when local data is missing."""
import importlib.util
import os

import pytest

from conftest import REPO

CORPUS = os.path.join(REPO, "corpus", "cycloneiv")


def score_module(*builds):
    for b in builds:
        if not os.path.exists(os.path.join(CORPUS, b, "bitstream.rbf")):
            pytest.skip(f"local data missing: corpus/cycloneiv/{b}")
    spec = importlib.util.spec_from_file_location("hb_score", os.path.join(REPO, "scripts", "cycloneiv_clean_hardblocks_score.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m
