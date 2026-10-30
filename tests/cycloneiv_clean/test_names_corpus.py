"""names_table.json covers every element type string of the corpus RCFs, one enum per type, no two types on one enum (#165, #169)."""
import glob
import os
import re
from concurrent.futures import ThreadPoolExecutor

from conftest import REPO, need

from lifters.cycloneiv_clean import names

PAT = re.compile(rb"\b([A-Z][A-Z0-9_]*):X\d+Y\d+S\d+I\d+\b")


def test_every_corpus_rcf_type_resolves_once():
    files = sorted(glob.glob(os.path.join(REPO, "corpus", "cycloneiv", "*", "routing.rcf")))
    need(files[0] if files else os.path.join(REPO, "corpus", "cycloneiv", "none", "routing.rcf"))
    with ThreadPoolExecutor(8) as ex:
        seen = set().union(*ex.map(lambda p: {t.decode() for t in PAT.findall(open(p, "rb").read())}, files))
    enums = names.enums()
    assert seen <= set(enums), sorted(seen - set(enums))
    by = {}
    for t in seen:
        by.setdefault(enums[t], []).append(t)
    assert all(len(v) == 1 for v in by.values()), {k: v for k, v in by.items() if len(v) > 1}
    for t, e in {"DSP_BUFFER": 286, "DSP_CONTROL_INPUT": 380, "PLL_CLKIN": 335, "PLL_FBOUT": 359, "PLL_FEEDBACK_IN": 336}.items():
        assert enums[t] == e      # source: libddb_dstr debug table index (hdr record names MAC_BUFFER / MAC_SEC_INPUT / PLL_*)
