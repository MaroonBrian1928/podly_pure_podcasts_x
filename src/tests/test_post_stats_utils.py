from app.routes.post_stats_utils import (
    build_edited_timeline_ad_markers,
    build_edited_timeline_bleep_windows,
)


def test_build_edited_timeline_ad_markers_uses_processed_splice_points() -> None:
    assert build_edited_timeline_ad_markers(
        [
            (10.0, 20.0),
            (40.0, 50.0),
        ]
    ) == [
        {
            "edited_start_time": 10.0,
            "edited_end_time": 10.0,
            "original_start_time": 10.0,
            "original_end_time": 20.0,
            "removed_duration_seconds": 10.0,
        },
        {
            "edited_start_time": 30.0,
            "edited_end_time": 30.0,
            "original_start_time": 40.0,
            "original_end_time": 50.0,
            "removed_duration_seconds": 10.0,
        },
    ]


def test_build_edited_timeline_bleep_windows_shift_and_clip_removed_audio() -> None:
    assert build_edited_timeline_bleep_windows(
        [
            (5.0, 6.0),
            (19.0, 31.0),
            (45.0, 46.0),
            (60.0, 62.0),
        ],
        [
            (20.0, 30.0),
            (40.0, 50.0),
        ],
        display_pad_start_seconds=0.15,
        display_pad_end_seconds=0.2,
    ) == [
        {
            "edited_start_time": 5.0,
            "edited_end_time": 6.0,
            "original_start_time": 5.0,
            "original_end_time": 6.0,
            "display_edited_start_time": 5.15,
            "display_edited_end_time": 5.8,
            "display_original_start_time": 5.15,
            "display_original_end_time": 5.8,
        },
        {
            "edited_start_time": 19.0,
            "edited_end_time": 20.0,
            "original_start_time": 19.0,
            "original_end_time": 20.0,
            "display_edited_start_time": 19.15,
            "display_edited_end_time": 19.8,
            "display_original_start_time": 19.15,
            "display_original_end_time": 19.8,
        },
        {
            "edited_start_time": 20.0,
            "edited_end_time": 21.0,
            "original_start_time": 30.0,
            "original_end_time": 31.0,
            "display_edited_start_time": 20.15,
            "display_edited_end_time": 20.8,
            "display_original_start_time": 30.15,
            "display_original_end_time": 30.8,
        },
        {
            "edited_start_time": 40.0,
            "edited_end_time": 42.0,
            "original_start_time": 60.0,
            "original_end_time": 62.0,
            "display_edited_start_time": 40.15,
            "display_edited_end_time": 41.8,
            "display_original_start_time": 60.15,
            "display_original_end_time": 61.8,
        },
    ]
