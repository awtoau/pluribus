"""Pure helpers of scripts/af3_engine_check.py + generator of scripts/cycloneiv_clean_af3_engine.py (#165).  No image; the run test needs the local build."""
import hashlib
import os
import struct
import sys

from conftest import REPO, need

sys.path.insert(0, os.path.join(REPO, "scripts"))
import af3_engine_check as C  # noqa: E402


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


def test_engine_matches_reference_sha1_with_dummy_secret():
    exe = os.path.join(REPO, "tmp", "af3", "obj_ovr", "Vengine")
    nlp = os.path.join(REPO, "tmp", "dji_microcode", "build", "nl.pkl")
    need(exe, nlp)
    import pickle
    nl = pickle.load(open(nlp, "rb"))
    mem0 = C.init_words(nl)
    assert [mem0[0x100 + i] for i in range(5)] == list(C.IV)       # H0..H4 constants at words 256..260
    tr, _ = C.run(3, "a0a1a2a3a4a5a6a7", 1700000)
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
