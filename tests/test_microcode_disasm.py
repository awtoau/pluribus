"""Synthetic sequencer round trip for the generic microcode disassembler (#165)."""
import importlib.util
import os

p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "cycloneiv_clean_microcode_disasm.py")
spec = importlib.util.spec_from_file_location("microcode_disasm", p)
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)

FMT = {"width": 18, "opfield": "op", "target": ["tgt"],
       "fields": [{"name": "op", "hi": 15, "lo": 12}, {"name": "tgt", "hi": 7, "lo": 0}, {"name": "cnt", "hi": 11, "lo": 0}],
       "ops": {"0xd": {"mn": "WAIT", "show": ["cnt"]}, "0x2": {"mn": "JMP", "show": ["tgt"]}}}


def test_roundtrip_and_stats():
    prog = [(0xD, {"cnt": 4}), (0xD, {"cnt": 3}), (0x2, {"tgt": 1})]
    words = [D.pack(dict(v, op=o), FMT) for o, v in prog]
    assert words == [0xD004, 0xD003, 0x2001]
    lst = D.listing(words, FMT, base=256)
    assert "WAIT" in lst[0] and "cnt=0x4" in lst[0] and "JMP" in lst[2] and lst[2].startswith("0102")
    st = D.stats(words, FMT, base=256)
    assert st["ops"] == [(2, 1), (0xD, 2)] and st["targets"]["tgt"]["n"] == 3


def test_selftest():
    D.selftest()
