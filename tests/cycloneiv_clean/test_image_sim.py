"""Pure helpers of scripts/cycloneiv_clean_image_sim.py (#165): LFSR / CRC predictors, recurrence check, long-line split.  No image, no simulator."""
import os
import sys

from conftest import REPO

sys.path.insert(0, os.path.join(REPO, "scripts"))
import cycloneiv_clean_image_sim as S  # noqa: E402


def test_crc_step_matches_ccitt_reference():
    # bitwise CRC-16/XMODEM (init 0, poly 0x1021) of "123456789" = 0x31C3
    crc = 0
    for ch in b"123456789":
        for i in range(7, -1, -1):
            crc = S.crc_step(crc, (ch >> i) & 1)
    assert crc == 0x31C3


def test_lfsr_step_and_recurrence():
    # x^15 + x + 1 as the detector reports it: taps [13, 14]; every stage stream satisfies s[t+15] = s[t+1] ^ s[t]
    s = "100101010000000"
    states = [s]
    for _ in range(200):
        states.append(S.lfsr_step(states[-1], [13, 14], False))
    streams = [[int(x[k]) for x in states] for k in range(15)]
    ok, tot = S.recurrence_ok(0b1000000000000011, streams, 15)
    assert tot > 0 and ok == tot
    assert len(set(states)) == len(states)


def test_split_long_breaks_statement_lines(tmp_path):
    src, dst = tmp_path / "a.v", tmp_path / "b.v"
    src.write_text("initial begin " + " ".join(f"m[{i}] = 1'b0;" for i in range(5000)) + " end\nassign `LUT_DELAY lc_1 = I[{1'b1, lc_1, 1'b1, 1'b1}];\n")
    n = S.split_long(str(src), str(dst), ["lc_1"])
    out = dst.read_text()
    assert n == 1 and max(len(l) for l in out.splitlines()) < S.LONG_LINE
    assert "{1'b1, 1'b0, 1'b1, 1'b1}" in out
