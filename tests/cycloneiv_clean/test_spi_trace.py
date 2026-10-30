"""cycloneiv_clean_spi_trace.py (#165): hand-built toy SPI slave (MOSI chain, 3-bit address register, two write registers, one readback slice)."""
import importlib.util
import os
import types

from conftest import REPO

spec = importlib.util.spec_from_file_location("spi_trace", os.path.join(REPO, "scripts", "cycloneiv_clean_spi_trace.py"))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def lut(name, pins, fn):
    pins = pins + ["1'b0"] * (4 - len(pins))
    init = 0
    for idx in range(16):
        v = [(idx >> b) & 1 for b in range(4)]
        init |= (fn(*v) & 1) << idx
    return dict(name=name, init=init, pins=pins, mode="datac", cin=None)


def build():
    L, F = [], []

    def ff(name, d, **kw):
        F.append(dict(name=name, d=d, clk="clk", **kw))

    def buf(name, src):
        L.append(lut(name, [src], lambda a, *_: a))
    buf("lc_k0", "pad_K")
    ff("ff_k0", "lc_k0")
    buf("lc_k1", "ff_k0")
    ff("ff_k1", "lc_k1")
    buf("lc_c0", "pad_C")
    ff("ff_c0", "lc_c0")
    buf("lc_c1", "ff_c0")
    ff("ff_c1", "lc_c1")
    L.append(lut("lc_g", ["ff_c0", "ff_c1"], lambda a, b, *_: a & (1 - b)))                       # frame clear
    L.append(lut("lc_en", ["ff_k0", "ff_k1", "ff_c1", "lc_g"], lambda a, b, c, g: (a & (1 - b) & (1 - c)) | g))
    ff("ff_s0", "pad_M")
    for i in range(1, 5):
        L.append(lut("lc_s%d" % i, ["ff_s%d" % (i - 1), "lc_g"], lambda p, g, *_: p & (1 - g)))
        ff("ff_s%d" % i, "lc_s%d" % i, ena="lc_en")
    buf("lc_ph", "ff_c1")
    ff("ff_ph", "lc_ph")
    buf("lc_ld", "ff_ph")
    ff("ff_ld", "lc_ld")
    for i in range(3):
        buf("lc_a%d" % i, "ff_a%d" % i)
        ff("ff_a%d" % i, "lc_a%d" % i, ena="lc_en", sload="ff_ld", asdata="ff_s%d" % (i + 1))
    for name, val in (("w0", 1), ("w1", 5)):
        L.append(lut("lc_" + name, ["ff_a0", "ff_a1", "ff_a2", "ff_ph"],
                     lambda a, b, c, p, val=val: int(a | b << 1 | c << 2 == val) & p))
        for i in range(3):
            ff("ff_%s_%d" % (name, i), "ff_s%d" % (i + 1), ena="lc_" + name)
    L.append(lut("lc_rb", ["ff_a0", "ff_a2", "ff_w0_0", "ff_w1_0"], lambda a0, a2, r1, r5: a0 & (r5 if a2 else r1)))
    ff("ff_rb0", "lc_rb")
    buf("lc_miso", "ff_rb0")
    # mode register 5 (addr 5 has FFs ff_w1_0/1): bits 0,1 select the radio-side output mux; pass = slave pad MOSI sample, internal = ff_eng
    L.append(lut("lc_mo", ["ff_w1_0", "ff_w1_1", "ff_s0", "ff_eng"], lambda m0, m1, p, e: e if (m1 and not m0) else (p if (m0 and not m1) else 0)))
    ff("ff_eng", "lc_eng")
    buf("lc_eng", "ff_eng")
    ios = [dict(ball="Q", dir="output", drv="lc_miso"), dict(ball="X", dir="output", drv="lc_mo")]
    return types.SimpleNamespace(luts=L, ffs=F, ios=ios)


def test_toy_spi():
    N = S.Net(build())
    R = S.trace(N, "M", "toy", 3, [1, 5])
    assert R["chain"]["length"] == 5 and R["chain"]["clear_gate"] == "lc_g"
    assert R["pads"]["frame_cs"] == ["C"] and R["pads"]["bit_clock"] == ["K"]
    assert R["address_register"]["ffs"] == ["ff_a0", "ff_a1", "ff_a2"]
    assert sorted(R["register_map"]) == ["0x1", "0x5"]
    assert [m["ball"] for m in R["miso"]] == ["Q"]
    assert R["readback_slices"] == ["ff_rb0"] and R["slice_bit"] == {"ff_rb0": 0}
    assert R["readback_leaf_classes"]["rf_only"] > 0
    M = R["master"]
    assert M["found"] and M["mode_register"] == 5
    assert M["outputs"][0]["ball"] == "X" and M["outputs"][0]["modes"]["2"] == "ff_eng"
