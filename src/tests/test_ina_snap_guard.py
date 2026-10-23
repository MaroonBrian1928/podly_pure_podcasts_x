"""Tests for the deterministic INA snap guard (Variant E+ policy).

The flagship case mirrors a real golden-set false positive (post 2401):
the refiner ended a block at 2212.0, swallowing the host's resumed
question; INA marked the true ad end with a silence gap at
2203.62-2204.36. The guard must land exactly on that gap's end.
"""

from podcast_processor.ina_snap_guard import AcousticSegment, apply_ina_snap_guard


def seg(start: float, end: float, label: str) -> AcousticSegment:
    return AcousticSegment(start=start, end=end, label=label)


def boundary(start: float, end: float) -> dict:
    return {
        "orig_start": start,
        "orig_end": end,
        "refined_start": start,
        "refined_end": end,
        "confidence": 0.85,
    }


def test_snaps_mid_speech_end_to_longest_silence() -> None:
    segments = [
        seg(1986.7, 2203.62, "speech"),
        seg(2203.62, 2204.36, "noEnergy"),  # the true ad end (0.74s)
        seg(2204.36, 2207.7, "speech"),
        seg(2207.7, 2208.28, "noEnergy"),  # micro-pause (0.58s)
        seg(2208.28, 2222.78, "speech"),
    ]
    boundaries = [boundary(1986.7, 2212.0)]

    result, adjustments = apply_ina_snap_guard(boundaries, segments)

    assert len(adjustments) == 1
    adj = adjustments[0]
    assert adj.original_end == 2212.0
    assert adj.snapped_end == 2204.36
    assert result[0]["refined_end"] == 2204.36
    # Start is never touched, and the audit key preserves attribution.
    assert result[0]["refined_start"] == 1986.7
    assert result[0]["ina_snap"] == {
        "original_end": 2212.0,
        "silence_start": 2203.62,
        "silence_end": 2204.36,
    }
    # Inputs are not mutated.
    assert boundaries[0]["refined_end"] == 2212.0
    assert "ina_snap" not in boundaries[0]


def test_no_snap_when_end_already_at_acoustic_edge() -> None:
    segments = [
        seg(100.0, 200.0, "speech"),
        seg(200.0, 201.0, "noEnergy"),
        seg(201.0, 300.0, "speech"),
    ]
    # End coincides with the speech segment's end: not mid-speech.
    result, adjustments = apply_ina_snap_guard([boundary(120.0, 200.0)], segments)
    assert adjustments == []
    assert result[0]["refined_end"] == 200.0


def test_music_veto_protects_sting_anchored_boundary() -> None:
    segments = [
        seg(700.0, 764.0, "speech"),
        seg(764.0, 765.2, "noEnergy"),
        seg(765.2, 773.0, "speech"),  # ad sign-off speech; end inside it
        seg(773.4, 776.0, "music"),  # return sting starts 0.8s after the end
        seg(776.0, 800.0, "speech"),
    ]
    result, adjustments = apply_ina_snap_guard([boundary(743.1, 772.6)], segments)
    assert adjustments == []
    assert result[0]["refined_end"] == 772.6


def test_cluster_veto_protects_shared_break() -> None:
    segments = [
        seg(600.0, 680.0, "speech"),
        seg(680.0, 681.5, "noEnergy"),
        seg(681.5, 720.0, "speech"),
    ]
    boundaries = [boundary(651.0, 685.6), boundary(694.4, 738.3)]
    result, adjustments = apply_ina_snap_guard(boundaries, segments)
    assert adjustments == []
    assert result[0]["refined_end"] == 685.6


def test_subsecond_move_is_ignored() -> None:
    segments = [
        seg(0.0, 99.6, "speech"),
        seg(99.6, 100.4, "noEnergy"),
        seg(100.4, 200.0, "speech"),
    ]
    # Only candidate would move the end by 0.6s: below the minimum move.
    result, adjustments = apply_ina_snap_guard([boundary(10.0, 101.0)], segments)
    assert adjustments == []
    assert result[0]["refined_end"] == 101.0


def test_start_boundary_is_never_snapped() -> None:
    segments = [
        seg(0.0, 50.0, "speech"),
        seg(50.0, 52.0, "music"),
        seg(52.0, 55.0, "noEnergy"),
        seg(55.0, 120.0, "speech"),
        seg(120.0, 121.0, "noEnergy"),
        seg(121.0, 200.0, "speech"),
    ]
    # Edges sit right after the start; the end is at an edge (no trigger).
    result, adjustments = apply_ina_snap_guard([boundary(51.0, 120.0)], segments)
    assert adjustments == []
    assert result[0]["refined_start"] == 51.0
    assert result[0]["refined_end"] == 120.0


def test_undershoot_end_is_never_shrunk_further() -> None:
    # The refiner already ended early (916.7; the ad runs to ~919.9 and
    # its only silence sits past the end). Candidates must lie inside
    # the block, so nothing can shrink this end further.
    segments = [
        seg(743.1, 918.0, "speech"),
        seg(918.0, 919.9, "noEnergy"),
        seg(919.9, 1000.0, "speech"),
    ]
    result, adjustments = apply_ina_snap_guard([boundary(743.1, 916.7)], segments)
    assert adjustments == []
    assert result[0]["refined_end"] == 916.7


def test_no_segments_or_no_boundaries_is_a_noop() -> None:
    result, adjustments = apply_ina_snap_guard([boundary(0.0, 100.0)], [])
    assert adjustments == []
    assert result[0]["refined_end"] == 100.0

    result, adjustments = apply_ina_snap_guard([], [seg(0.0, 10.0, "speech")])
    assert result == []
    assert adjustments == []


def test_only_qualifying_block_adjusts_among_many() -> None:
    segments = [
        seg(0.0, 300.0, "speech"),
        seg(300.0, 302.0, "noEnergy"),
        seg(302.0, 500.0, "speech"),
    ]
    boundaries = [boundary(10.0, 100.0), boundary(200.0, 305.0)]
    result, adjustments = apply_ina_snap_guard(boundaries, segments)
    assert len(adjustments) == 1
    assert adjustments[0].block_index == 1
    assert result[0]["refined_end"] == 100.0
    assert result[1]["refined_end"] == 302.0


# --- Deferral to the sting anchor -------------------------------------
# These segments mirror post 2397's composition failure: the refiner
# ended the block at 753.6, the sting tier anchored the end to 742.76,
# and the snap guard then shrank it further to the in-ad silence ending
# at 735.08. The end 742.76 sits mid-speech with that silence a valid
# snap candidate (7.68s back), so without deferral the guard fires.


def composition_segments() -> list[AcousticSegment]:
    return [
        seg(600.0, 734.3, "speech"),
        seg(734.3, 735.08, "noEnergy"),  # in-ad silence
        seg(735.08, 760.0, "speech"),
    ]


def sting_end_entry() -> dict:
    return {"role": "end", "score": 0.99, "onset": 743.76, "original_end": 753.6}


def sting_start_entry() -> dict:
    return {
        "role": "start",
        "score": 0.98,
        "onset": 598.0,
        "original_start": 605.0,
    }


def test_composition_case_snaps_without_sting_anchor() -> None:
    # Control: the same boundary with no sting audit key snaps to the
    # in-ad silence -- the candidate the deferral must suppress.
    result, adjustments = apply_ina_snap_guard(
        [boundary(600.0, 742.76)], composition_segments()
    )
    assert len(adjustments) == 1
    assert result[0]["refined_end"] == 735.08


def test_sting_end_anchor_defers_snap() -> None:
    b = boundary(600.0, 742.76)
    b["sting_anchor"] = sting_end_entry()

    result, adjustments = apply_ina_snap_guard([b], composition_segments())

    assert adjustments == []
    assert result[0]["refined_end"] == 742.76
    assert "ina_snap" not in result[0]


def test_sting_start_anchor_does_not_defer_end_snap() -> None:
    # Only the START was sting-anchored (post 2409's composition): the
    # end stays fully eligible and snaps as usual.
    b = boundary(600.0, 742.76)
    b["sting_anchor"] = sting_start_entry()

    result, adjustments = apply_ina_snap_guard([b], composition_segments())

    assert len(adjustments) == 1
    assert result[0]["refined_end"] == 735.08
    assert result[0]["ina_snap"]["original_end"] == 742.76


def test_sting_anchor_list_with_end_entry_defers() -> None:
    # Both edges moved: the audit value is a list of two dicts, and the
    # END entry in it still defers the end.
    b = boundary(600.0, 742.76)
    b["sting_anchor"] = [sting_start_entry(), sting_end_entry()]

    result, adjustments = apply_ina_snap_guard([b], composition_segments())

    assert adjustments == []
    assert result[0]["refined_end"] == 742.76
    assert "ina_snap" not in result[0]


def test_sting_anchor_list_start_only_does_not_defer() -> None:
    b = boundary(600.0, 742.76)
    b["sting_anchor"] = [sting_start_entry()]

    result, adjustments = apply_ina_snap_guard([b], composition_segments())

    assert len(adjustments) == 1
    assert result[0]["refined_end"] == 735.08
