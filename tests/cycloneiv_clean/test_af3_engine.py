"""Pure helpers of scripts/af3_engine_check.py + generator of scripts/cycloneiv_clean_af3_engine.py (#165).
The run tests regenerate nl.pkl + engine.v + Vengine fresh from PLURIBUS_DJI_IMAGE every call (#181 pt 1,
3) -- a cached tmp/ build proves nothing about the current decoder, only that it matches itself."""
import hashlib
import os
import re
import struct
import subprocess
import sys

import pytest

from conftest import REPO, need

sys.path.insert(0, os.path.join(REPO, "scripts"))
import af3_engine_check as C  # noqa: E402

IMAGE = os.environ.get("PLURIBUS_DJI_IMAGE", "")
OUT = os.path.join(REPO, "tmp", "af3_engine_test")


def test_sha1_compress_equals_hashlib_for_one_block():
    msg = b"abc"
    blk = msg + b"\x80" + b"\x00" * (64 - len(msg) - 1 - 8) + struct.pack(">Q", 8 * len(msg))
    words = struct.unpack(">16I", blk)
    assert b"".join(struct.pack(">I", x) for x in C.sha1_compress(words, 1)) == hashlib.sha1(msg).digest()
    raw = C.sha1_compress(words, 0)
    assert [(x + y) & 0xFFFFFFFF for x, y in zip(raw, C.IV)] == C.sha1_compress(words, 1)


def test_word_wire_is_a_permutation_of_36_positions():
    pos = {(t, p) for t, p in C.WORD_WIRE.values()}
    assert len(pos) == 32 and all(t in (0, 1) and 0 <= p < 18 for t, p in pos)


@pytest.fixture(scope="module")
def fresh_engine():
    """Fresh nl.pkl (cycloneiv_clean_image_build.py, --no-rtl) + fresh engine.v (af3_engine.py extract)
    + fresh obj/obj_ovr Vengine builds, all from current HEAD against PLURIBUS_DJI_IMAGE.  Skips cleanly
    when the image isn't available (conftest.need pattern) instead of falling back to any cached tmp/ build."""
    if not IMAGE or not os.path.isfile(IMAGE):
        pytest.skip("PLURIBUS_DJI_IMAGE not set or file absent")
    os.makedirs(OUT, exist_ok=True)
    nlp = os.path.join(OUT, "nl.pkl")
    r = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "cycloneiv_clean_image_build.py"), IMAGE, "--out", OUT, "--no-rtl"],
                        capture_output=True, text=True)
    if r.returncode:
        pytest.skip(f"image_build failed: {(r.stdout + r.stderr)[-2000:]}")
    need(nlp)
    r = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "cycloneiv_clean_af3_engine.py"), "extract", "--nl", nlp],
                        capture_output=True, text=True)
    assert r.returncode == 0, f"af3_engine.py extract failed against a fresh nl.pkl: {(r.stdout + r.stderr)[-2000:]}"
    for obj, gens in (("obj", []), ("obj_ovr", ["OVR=1"])):
        r = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "cycloneiv_clean_af3_engine.py"), "build", "--obj", obj, *(f"-G{g}" for g in gens)],
                            capture_output=True, text=True)
        assert r.returncode == 0, f"verilator build ({obj}) failed: {(r.stdout + r.stderr)[-2000:]}"
    return nlp


def test_engine_matches_reference_sha1_with_dummy_secret(fresh_engine):
    import pickle
    nl = pickle.load(open(fresh_engine, "rb"))
    mem0 = C.init_words(nl)
    assert [mem0[0x100 + i] for i in range(5)] == list(C.IV)       # H0..H4 constants at words 256..260
    tr, _ = C.run(3, "a0a1a2a3a4a5a6a7", 1700000, obj="obj_ovr")
    ev = C.parse(tr)
    start = next(c for c, ad, v in ev if ad == 0x104 and c > 1550000)
    mem = {i: mem0[i] for i in range(0x100, 0x120)}
    for c, ad, v in ev:
        if c >= start:
            break
        mem[ad] = v
    sec = bytes.fromhex("a0a1a2a3a4a5a6a7")
    mem[0x110], mem[0x11C] = struct.unpack(">I", sec[:4])[0], struct.unpack(">I", sec[4:])[0]
    state = {}
    for c, ad, v in ev:
        if 0x100 <= ad <= 0x104 and c >= start:
            state[ad] = v
    assert [state[0x100 + i] for i in range(5)] == C.sha1_compress([mem[0x110 + i] for i in range(16)], 0)


def test_unmodified_engine_key_words_and_authentication_match(fresh_engine):
    _, out = C.run(3, "0111878979465213", 1700000, obj="obj")
    words = dict(re.findall(r"ENGINE-WORD (W0|W12)=([0-9a-f]{8})", out))
    assert words == {"W0": "01118789", "W12": "79465213"}

    # ff_6_90_6 is ffvec bit 42: set only when all five returned MAC words match.
    final = int("".join(re.search(r"FINAL-FF ((?:[0-9a-f]{8} ?)+)", out)[1].split()), 16)
    assert (final >> 42) & 1 == 1
