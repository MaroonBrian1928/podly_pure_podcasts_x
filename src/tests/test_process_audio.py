import tempfile
from pathlib import Path

from podcast_processor import audio as audio_module
from podcast_processor.audio import (
    DEFAULT_CBR_BITRATE,
    DEFAULT_VBR_QUALITY,
    _clip_segments_simple,
    _trim_file_lossless,
    clip_segments_exact,
    clip_segments_with_fade,
    get_audio_bitrate_bps,
    get_audio_duration_ms,
    overlay_beeps_with_ducking,
    split_audio,
    trim_file,
)

TEST_FILE_DURATION = 66_048
TEST_FILE_PATH = "src/tests/data/count_0_99.mp3"


def test_default_encoding_args_use_fallback_or_source_bitrate() -> None:
    assert audio_module._get_encoding_args(use_vbr=True) == {"q:a": DEFAULT_VBR_QUALITY}
    assert audio_module._get_encoding_args(use_vbr=False) == {
        "b:a": DEFAULT_CBR_BITRATE
    }
    assert audio_module._get_encoding_args(
        use_vbr=False, source_bitrate_bps=128_000
    ) == {"b:a": "128000"}


def test_get_duration_ms() -> None:
    assert get_audio_duration_ms(TEST_FILE_PATH) == TEST_FILE_DURATION


def test_get_audio_bitrate_bps() -> None:
    bitrate = get_audio_bitrate_bps(TEST_FILE_PATH)

    assert bitrate is not None
    assert bitrate > 0


def test_get_duration_ms_uses_rust_probe_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "podcast_processor.audio.try_probe_audio_duration_ms", lambda path: 1234
    )

    assert get_audio_duration_ms(TEST_FILE_PATH) == 1234


def test_clip_segment_with_fade_uses_rust_when_enabled(monkeypatch) -> None:
    calls = []

    def fake_cut_audio(**kwargs) -> bool:
        calls.append(kwargs)
        return True

    monkeypatch.setattr("podcast_processor.audio.try_cut_audio", fake_cut_audio)

    clip_segments_with_fade(
        [(3_000, 21_000)],
        5_000,
        TEST_FILE_PATH,
        "/tmp/out.mp3",
        use_vbr=True,
    )

    assert calls[0]["mode"] == "fade"
    assert calls[0]["fade_ms"] == 5_000
    assert calls[0]["encoding"] == "vbr"
    assert calls[0]["vbr_quality"] == DEFAULT_VBR_QUALITY


def test_clip_segment_with_fade_matches_source_bitrate_for_rust(
    monkeypatch,
) -> None:
    calls = []

    def fake_cut_audio(**kwargs) -> bool:
        calls.append(kwargs)
        return True

    monkeypatch.setattr("podcast_processor.audio.try_cut_audio", fake_cut_audio)
    monkeypatch.setattr(
        "podcast_processor.audio.get_audio_bitrate_bps", lambda path: 123_456
    )

    clip_segments_with_fade(
        [(3_000, 21_000)],
        5_000,
        TEST_FILE_PATH,
        "/tmp/out.mp3",
    )

    assert calls[0]["encoding"] == "cbr"
    assert calls[0]["cbr_bitrate_bps"] == 123_456


def test_clip_segment_exact_uses_rust_when_enabled(monkeypatch) -> None:
    calls = []

    def fake_cut_audio(**kwargs) -> bool:
        calls.append(kwargs)
        return True

    monkeypatch.setattr("podcast_processor.audio.try_cut_audio", fake_cut_audio)
    monkeypatch.setattr(
        "podcast_processor.audio.get_audio_bitrate_bps", lambda path: 98_765
    )

    clip_segments_exact([(3_000, 21_000)], TEST_FILE_PATH, "/tmp/out.mp3")

    assert calls[0]["mode"] == "exact"
    assert calls[0]["fade_ms"] == 0
    assert calls[0]["encoding"] == "cbr"
    assert calls[0]["cbr_bitrate_bps"] == 98_765


def test_clip_segment_with_fade() -> None:
    fade_len_ms = 5_000
    ad_start_offset_ms, ad_end_offset_ms = 3_000, 21_000

    with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as temp_file:
        clip_segments_with_fade(
            [(ad_start_offset_ms, ad_end_offset_ms)],
            fade_len_ms,
            TEST_FILE_PATH,
            temp_file.name,
        )

        expected_duration = (
            TEST_FILE_DURATION
            - (ad_end_offset_ms - ad_start_offset_ms)
            + 2 * fade_len_ms
            + 56  # not sure where this fudge comes from
        )
        actual_duration = get_audio_duration_ms(temp_file.name)
        assert actual_duration is not None, "Failed to get audio duration"
        assert abs(actual_duration - expected_duration) <= 60, (
            f"Duration mismatch: expected {expected_duration}ms, got {actual_duration}ms, "
            f"difference: {abs(actual_duration - expected_duration)}ms"
        )


def test_clip_segment_with_fade_beginning() -> None:
    fade_len_ms = 5_000
    ad_start_offset_ms, ad_end_offset_ms = 0, 18_000

    with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as temp_file:
        clip_segments_with_fade(
            [(ad_start_offset_ms, ad_end_offset_ms)],
            fade_len_ms,
            TEST_FILE_PATH,
            temp_file.name,
        )

        expected_duration = (
            TEST_FILE_DURATION
            - (ad_end_offset_ms - ad_start_offset_ms)
            + 2 * fade_len_ms
            + 56  # not sure where this fudge comes from
        )
        actual_duration = get_audio_duration_ms(temp_file.name)
        assert actual_duration is not None, "Failed to get audio duration"
        assert abs(actual_duration - expected_duration) <= 60, (
            f"Duration mismatch: expected {expected_duration}ms, got {actual_duration}ms, "
            f"difference: {abs(actual_duration - expected_duration)}ms"
        )


def test_clip_segment_with_fade_end() -> None:
    fade_len_ms = 5_000
    ad_start_offset_ms, ad_end_offset_ms = (
        TEST_FILE_DURATION - 18_000,
        TEST_FILE_DURATION,
    )

    with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as temp_file:
        clip_segments_with_fade(
            [(ad_start_offset_ms, ad_end_offset_ms)],
            fade_len_ms,
            TEST_FILE_PATH,
            temp_file.name,
        )

        expected_duration = (
            TEST_FILE_DURATION
            - (ad_end_offset_ms - ad_start_offset_ms)
            + 2 * fade_len_ms
            + 56  # not sure where this fudge comes from
        )
        actual_duration = get_audio_duration_ms(temp_file.name)
        assert actual_duration is not None, "Failed to get audio duration"
        assert abs(actual_duration - expected_duration) <= 60, (
            f"Duration mismatch: expected {expected_duration}ms, got {actual_duration}ms, "
            f"difference: {abs(actual_duration - expected_duration)}ms"
        )


def test_overlay_beeps_with_ducking_preserves_duration() -> None:
    with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as temp_file:
        overlay_beeps_with_ducking(
            [(3_000, 3_600), (10_000, 10_400)],
            TEST_FILE_PATH,
            temp_file.name,
        )

        actual_duration = get_audio_duration_ms(temp_file.name)
        assert actual_duration is not None, "Failed to get audio duration"
        assert abs(actual_duration - TEST_FILE_DURATION) <= 100, (
            f"Duration mismatch: expected {TEST_FILE_DURATION}ms, got {actual_duration}ms, "
            f"difference: {abs(actual_duration - TEST_FILE_DURATION)}ms"
        )


def test_overlay_beeps_with_ducking_handles_equal_length_windows() -> None:
    with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as temp_file:
        overlay_beeps_with_ducking(
            [(3_000, 3_400), (10_000, 10_400), (20_000, 20_400)],
            TEST_FILE_PATH,
            temp_file.name,
        )

        actual_duration = get_audio_duration_ms(temp_file.name)
        assert actual_duration is not None, "Failed to get audio duration"
        assert abs(actual_duration - TEST_FILE_DURATION) <= 100, (
            f"Duration mismatch: expected {TEST_FILE_DURATION}ms, got {actual_duration}ms, "
            f"difference: {abs(actual_duration - TEST_FILE_DURATION)}ms"
        )


def test_overlay_beeps_with_ducking_uses_rust_when_enabled(monkeypatch) -> None:
    calls = []

    def fake_bleep_audio(**kwargs) -> bool:
        calls.append(kwargs)
        return True

    monkeypatch.setattr("podcast_processor.audio.try_bleep_audio", fake_bleep_audio)

    overlay_beeps_with_ducking(
        [(3_000, 3_600)],
        TEST_FILE_PATH,
        "/tmp/out.mp3",
        use_vbr=True,
    )

    assert calls[0]["windows_ms"] == [(3_000, 3_600)]
    assert calls[0]["encoding"] == "vbr"
    assert calls[0]["vbr_quality"] == DEFAULT_VBR_QUALITY


def test_trim_file_uses_stream_copy_for_transcription_chunks(monkeypatch) -> None:
    output_calls = []

    class FakeFfmpegStream:
        def output(self, *args, **kwargs):
            output_calls.append((args, kwargs))
            return self

        def overwrite_output(self):
            return self

        def run(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        audio_module.ffmpeg,
        "input",
        lambda *args, **kwargs: FakeFfmpegStream(),
    )

    trim_file(Path("input.mp3"), Path("chunk.mp3"), 1_000, 2_500)

    assert output_calls == [
        (
            ("chunk.mp3",),
            {
                "ss": 1.0,
                "t": 1.5,
                "acodec": "copy",
                "vn": None,
            },
        )
    ]


def test_trim_file_lossless_uses_pcm_wav_intermediate(monkeypatch) -> None:
    output_calls = []

    class FakeFfmpegStream:
        def output(self, *args, **kwargs):
            output_calls.append((args, kwargs))
            return self

        def overwrite_output(self):
            return self

        def run(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        audio_module.ffmpeg,
        "input",
        lambda *args, **kwargs: FakeFfmpegStream(),
    )

    _trim_file_lossless(Path("input.mp3"), Path("segment.wav"), 1_000, 2_500)

    assert output_calls == [
        (
            ("segment.wav",),
            {
                "ss": 1.0,
                "t": 1.5,
                "acodec": "pcm_s16le",
                "vn": None,
            },
        )
    ]


def test_clip_segments_simple_uses_lossless_intermediates(monkeypatch) -> None:
    segment_calls = []
    concat_inputs = []
    concat_outputs = []

    def fake_trim_file_lossless(in_path, out_path, start_ms, end_ms) -> None:
        segment_calls.append((in_path, out_path, start_ms, end_ms))
        out_path.write_bytes(b"wav")

    class FakeFfmpegStream:
        def output(self, *args, **kwargs):
            concat_outputs.append((args, kwargs))
            return self

        def overwrite_output(self):
            return self

        def run(self, *args, **kwargs):
            return None

    def fake_ffmpeg_input(*args, **kwargs):
        concat_inputs.append((args, kwargs))
        return FakeFfmpegStream()

    monkeypatch.setattr(
        audio_module,
        "_trim_file_lossless",
        fake_trim_file_lossless,
    )
    monkeypatch.setattr(audio_module.ffmpeg, "input", fake_ffmpeg_input)

    _clip_segments_simple(
        [(1_000, 2_000)],
        "input.mp3",
        "output.mp3",
        5_000,
        {"b:a": DEFAULT_CBR_BITRATE},
    )

    assert [(call[2], call[3]) for call in segment_calls] == [
        (0, 1_000),
        (2_000, 5_000),
    ]
    assert [call[1].suffix for call in segment_calls] == [".wav", ".wav"]
    assert concat_inputs[0][1] == {"format": "concat", "safe": 0}
    assert concat_outputs == [
        (("output.mp3",), {"acodec": "libmp3lame", "b:a": DEFAULT_CBR_BITRATE})
    ]


def test_split_audio() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        split_audio(Path(TEST_FILE_PATH), temp_dir_path, 38_000)

        expected = {
            "0.mp3": (6_384, 38_108),
            "1.mp3": (6_384, 38_252),
            "2.mp3": (6_384, 38_108),
            "3.mp3": (6_384, 38_108),
            "4.mp3": (6_384, 38_252),
            "5.mp3": (6_384, 38_252),
            "6.mp3": (6_384, 38_252),
            "7.mp3": (6_384, 38_108),
            "8.mp3": (6_384, 38_108),
            "9.mp3": (6_384, 38_252),
            "10.mp3": (2_784, 16_508),
        }

        for split in temp_dir_path.iterdir():
            assert split.name in expected
            duration_ms, filesize = expected[split.name]
            actual_duration = get_audio_duration_ms(str(split))
            assert actual_duration is not None, (
                f"Failed to get audio duration for {split}"
            )
            assert abs(actual_duration - duration_ms) <= 100, (
                f"Duration mismatch for {split}. Expected {duration_ms}ms, got {actual_duration}ms, "
                f"difference: {abs(actual_duration - duration_ms)}ms"
            )
            assert abs(filesize - split.stat().st_size) <= 500, (
                f"filesize <> 500 bytes for {split}. found {split.stat().st_size}, expected {filesize}"
            )


def test_split_audio_uses_rust_when_enabled(monkeypatch) -> None:
    expected = [(Path("/tmp/chunks/0.mp3"), 0), (Path("/tmp/chunks/1.mp3"), 1000)]

    monkeypatch.setattr(
        "podcast_processor.audio.try_split_audio",
        lambda **kwargs: expected,
    )

    assert split_audio(Path(TEST_FILE_PATH), Path("/tmp/chunks"), 38_000) == expected
