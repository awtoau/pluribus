"""Clean pipeline on the third-party EP4CGX150 image (scripts/cycloneiv_clean_image.py, #165).  Skips when PLURIBUS_DJI_IMAGE is unset or the
file is absent.  Only counts are asserted: no ground truth exists, so these are integrity and impossibility checks, not correctness."""
import os
import sys

import pytest

from conftest import REPO, need, report

sys.path.insert(0, os.path.join(REPO, "scripts"))
IMAGE = os.environ.get("PLURIBUS_DJI_IMAGE", "")


@pytest.fixture(scope="module")
def image_run():
    if not IMAGE or not os.path.isfile(IMAGE):
        pytest.skip("PLURIBUS_DJI_IMAGE not set or file absent")
    need(os.path.join(REPO, "databases", "cycloneiv", "sof2rbf_mask.npz"), os.path.join(REPO, "databases", "cycloneiv", "io_decode.json"))
    import cycloneiv_clean_image as I
    before = os.stat(IMAGE)
    try:
        res = I.run(IMAGE, 0)
    except (FileNotFoundError, SystemExit) as e:                # missing local vendor data
        pytest.skip(str(e))
    after = os.stat(IMAGE)
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "image must stay read-only"
    assert not os.path.exists(I.PLANE), "derived plane is removed by the script"
    return res


def test_container_integrity(image_run):
    c = image_run["container"]
    assert c["header_crc_ok"] and c["compressed"]
    assert c["cram_frame_crc_pass"] == c["cram_frame_crc_total"] == 6154
    assert c["frames_after_chain_valid"] == 0
    assert c["cram_bits"] == 39_040_976
    report("image_container", **{k: c[k] for k in ("cram_frame_crc_pass", "cram_frame_crc_total", "frame_bytes", "periphery_frames")})


def test_no_impossible_counts(image_run):
    lg = image_run["logic"]
    assert not lg["impossible_luts"] and not lg["impossible_ffs"]
    assert lg["labs_with_lut"] <= lg["labs_total"]
    assert image_run["io"]["cff_primary_replica_disagreements"] == 0
    report("image_logic", luts=lg["luts_nonzero_init"], ffs=lg["les_ff_claimed"], labs=lg["labs_with_lut"])


def test_sanity_counts_reported(image_run):
    r = image_run["routing"]
    # conflicts / undriven / loops are reported as faults, not asserted to be zero (the decode is not a pass on them)
    for v in r["variants"].values():
        assert v["fanin_conflict_nodes"] <= v["dst_nodes"]
    assert r["undriven_used_nodes"] <= r["nets_roots"]
    report("image_sanity", fanin_conflict_nodes=r["variants"][r["headline_variant"]]["fanin_conflict_nodes"],
           undriven=r["undriven_used_nodes"], loops=r["loops"]["scc_gt1"])
