"""synthgen off-page guard: an export transform that clips content must
raise at generation time, never silently emit a self-contradictory answer
key (the rendered PDF drops clipped entities while inventory/expected_changes
still assume them — Constitution V requires the key to match the render)."""

from __future__ import annotations

import pytest

from synthgen import make_pair


def test_offpage_export_offset_raises(tmp_path):
    # offset (100, 80) clips several entities; the first reported offender is
    # the outer wall rect crossing the right page edge (x1 = 880 > 842).
    with pytest.raises(ValueError, match=r"off-page in v2"):
        make_pair(
            "floorplan", ["remove"], tmp_path / "p", seed=7,
            export_offset=(100.0, 80.0), export_scale=1.0,
        )
    # nothing half-written: no PDFs, no answer key
    assert not (tmp_path / "p" / "v1.pdf").exists()
    assert not (tmp_path / "p" / "v2.pdf").exists()
    assert not (tmp_path / "p" / "answer-key.json").exists()


def test_guard_names_the_offending_entity(tmp_path):
    # +40pt clips ONLY the note (bbox top 562.4 -> 602.4 > 595; the
    # next-highest entity tops out at 540 -> 580), so the error must name it
    # and the exceeded bound.
    with pytest.raises(ValueError, match=r"NOTE: ALL WALLS.*y1=.*> page height"):
        make_pair(
            "floorplan", [], tmp_path / "p", seed=7,
            export_offset=(0.0, 40.0), export_scale=1.0,
        )


def test_onpage_fixtures_still_generate(tmp_path):
    """pair02's offset/scale and every preset stay within bounds."""
    make_pair(
        "floorplan", [], tmp_path / "pair02", seed=7,
        export_offset=(34.0, 21.0), export_scale=1.02,
    )
    assert (tmp_path / "pair02" / "answer-key.json").exists()
    for preset in ("floorplan", "site", "unrelated"):
        make_pair(preset, [], tmp_path / preset, seed=7)
        assert (tmp_path / preset / "answer-key.json").exists()
