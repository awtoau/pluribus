"""Package inference (#172): tmp/pkgtest builds (3 packages x speed grades x designs) and the third-party image (env PLURIBUS_DJI_IMAGE).  Skips without the local data."""
import glob
import json
import os
import re

import numpy as np
import pytest

from conftest import REPO, report
from lifters.cycloneiv_clean import pkginfer as PI


@pytest.fixture(scope="module")
def ctx():
    from lifters.cycloneiv_clean import io_decode as ID, io_fields as IF, io_pins as IP, tracer as T
    try:
        io = T.Io()
        dec = IF.Decoder(json.load(open(ID.DECODE_PATH)))
        return IP.PinMap(io, dec), dec
    except Exception as e:  # noqa: BLE001
        pytest.skip(str(e))


CODE = {"CF23": "F484", "DF27": "F672", "DF31": "F896"}


def test_pkgtest_builds(ctx):
    files = sorted(glob.glob(os.path.join(REPO, "tmp", "pkgtest", "*", "bitstream.rbf")))
    if not files:
        pytest.skip("tmp/pkgtest builds missing")
    pm, dec = ctx
    bad, n = [], 0
    for f in files:
        want = CODE[re.search(r"(CF23|DF27|DF31)", f)[1]]
        r = PI.infer(pm, dec, np.fromfile(f, np.uint8))
        n += 1
        if r["package"] != want:
            bad.append((os.path.basename(os.path.dirname(f)), want, r["package"], r["reason"]))
    report("pkginfer_builds", builds=n, wrong=len(bad))
    assert not bad


def test_image(ctx):
    img = os.environ.get("PLURIBUS_DJI_IMAGE")
    if not img or not os.path.exists(img):
        pytest.skip("PLURIBUS_DJI_IMAGE not set")
    import sys
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import cycloneiv_decompress as cd
    pm, dec = ctx
    r = PI.infer(pm, dec, np.frombuffer(bytes(cd.decompress(open(img, "rb").read(), {})), np.uint8))
    report("pkginfer_image", package=r["package"], exact=r["exact"], ground=r["ground_sites"], strict=r["ground_strict"], per=r["per_package"])
    assert r["package"] == "F672" and r["exact"]


def test_refuses_inconsistent_ground_set():
    from lifters.cycloneiv_clean import pkgpad as K
    try:
        pads = sorted(set(K.io_site_pads(K.pads()).values()))
        bonded = PI.bonded_pads(672)
    except Exception as e:  # noqa: BLE001
        pytest.skip(str(e))
    mk = lambda ground: {j: {"site": (0, j), "cls": "unused", "ground": j in ground, "strict": j in ground} for j in pads}
    unb672 = {j for j in pads if j not in bonded}
    assert PI.infer_package(mk(unb672))["package"] == "F672"
    assert PI.infer_package(mk(set()))["package"] == "F896"
    assert PI.infer_package(mk(set(list(unb672)[:-1])))["package"] is None        # one unbonded pad not ground: no package fits
    assert PI.infer_package(mk(unb672 | {next(j for j in pads if j in bonded)}))["package"] is None
