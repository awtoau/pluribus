"""annexb_slice_stats on a generated x264 sample (periodic intra refresh): no vendor data."""
import importlib.util
import os
import shutil
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("annexb_slice_stats", os.path.join(REPO, "scripts", "annexb_slice_stats.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_exp_golomb():
    b = mod.Bits(bytes([0b10100110, 0b01000000]))
    assert [b.ue(), b.ue(), b.ue(), b.ue()] == [0, 1, 2, 3]


def _have_x264():
    if not shutil.which("ffmpeg"):
        return False
    r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
    return "libx264" in r.stdout


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    if not _have_x264():
        pytest.skip("ffmpeg/libx264 not available")
    out = str(tmp_path_factory.mktemp("annexb") / "ir.h264")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25",
                    "-frames:v", "60", "-c:v", "libx264", "-bf", "0", "-x264-params",
                    "intra-refresh=1:keyint=20:aud=1:slices=3:annexb=1:repeat-headers=1", "-f", "h264", out], check=True)
    return out


def test_bitstream_pass(sample):
    aus, nal_hist, sei_hist, spss = mod.bitstream_pass(open(sample, "rb").read())
    assert len(aus) == 60
    assert nal_hist[9] == 60 and nal_hist[5] >= 1
    assert all(len(a["slices"]) == 3 for a in aus)
    assert 6 in sei_hist  # recovery point SEI
    sp = next(iter(spss.values()))
    assert (sp["mb_w"], sp["mb_h"]) == (20, 15)
    assert aus[0]["idr"] and aus[0]["sps"]


def test_mbmap_finds_rolling_column(sample):
    if not shutil.which("ffmpeg"):
        pytest.skip("no ffmpeg")
    spss = mod.bitstream_pass(open(sample, "rb").read())[3]
    res = mod.mbmap_pass(sample, spss)
    summary = mod.summarise_mb(res)
    assert summary["frames"] >= 55
    assert summary["cols"]["runs"] >= 1  # x264 intra-refresh is a moving intra column
