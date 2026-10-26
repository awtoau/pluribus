#!/usr/bin/env python3.15t
"""Replace corpus decomp.bt (mistral-cv) by the native decoder's output so the lift/sim gates run Mistral-binary-free.

Keeps the mistral-cv file as decomp.mistral.bt and logs the .bt line-set diff per design.
  PLURIBUS_CV_CORPUS=cyclonev_e150 python3.15t scripts/cyclonev_corpus_native_bt.py [design ...]
Log: tmp/logs/cyclonev_corpus_native_bt.log
"""
import logging
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import cyclonev_bt_diff as bd  # noqa: E402
import cyclonev_decode as nd  # noqa: E402

CORPUS = REPO / "corpus" / os.environ.get("PLURIBUS_CV_CORPUS", "cyclonev")
log = logging.getLogger("cyclonev_corpus_native_bt")


def main():
    (REPO / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", handlers=[
        logging.StreamHandler(), logging.FileHandler(REPO / "tmp" / "logs" / "cyclonev_corpus_native_bt.log")])
    names = sys.argv[1:] or sorted(p.parent.name for p in CORPUS.glob("*/bitstream.rbf"))
    tot = {}
    for n in names:
        d = CORPUS / n
        mistral = d / "decomp.mistral.bt"
        if not mistral.exists():
            shutil.copyfile(d / "decomp.bt", mistral)
        m = nd.decode((d / "bitstream.rbf").read_bytes(), "auto")
        (d / "decomp.bt").write_text("\n".join(m.bt_lines()) + "\n")
        df = bd.diff(bd.read(str(d / "decomp.bt")), bd.read(str(mistral)))
        s = {k: (len(a), len(b)) for k, (a, b, _, _) in df.items() if a or b}
        log.info("%s: native vs mistral-cv differing lines (only_native, only_mistral) %s", n, s or "none")
        for k, v in s.items():
            t = tot.setdefault(k, [0, 0])
            t[0] += v[0]; t[1] += v[1]
    log.info("TOTAL %s over %d designs", tot, len(names))


if __name__ == "__main__":
    main()
