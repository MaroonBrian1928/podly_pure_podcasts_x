from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from podcast_processor.ad_classifier import AdClassifier
from podcast_processor.audio_processor import AudioProcessor
from podcast_processor.ina_client import AudioSegmentResult
from podcast_processor.podcast_downloader import PodcastDownloader
from podcast_processor.podcast_processor import PodcastProcessor
from podcast_processor.processing_status_manager import ProcessingStatusManager
from podcast_processor.transcription_manager import TranscriptionManager
from shared.test_utils import create_standard_test_config


def test_run_ina_analysis_persists_segments_and_updates_model_call(app) -> None:
    with app.app_context():
        processor = PodcastProcessor(
            config=create_standard_test_config(),
            transcription_manager=MagicMock(spec=TranscriptionManager),
            ad_classifier=MagicMock(spec=AdClassifier),
            audio_processor=MagicMock(spec=AudioProcessor),
            status_manager=MagicMock(spec=ProcessingStatusManager),
            db_session=MagicMock(),
            downloader=MagicMock(spec=PodcastDownloader),
        )

        action_calls: list[tuple[str, dict]] = []
        update_calls: list[tuple[str, int, dict]] = []

        def fake_action(name: str, payload: dict, wait: bool = False):
            del wait
            action_calls.append((name, payload))
            if name == "delete_model_calls_for_post_by_model_name":
                return SimpleNamespace(success=True, data={"deleted": 0})
            if name == "upsert_model_call":
                return SimpleNamespace(success=True, data={"model_call_id": 123})
            if name == "replace_audio_segments":
                return SimpleNamespace(success=True, data={"segment_count": 2})
            raise AssertionError(f"Unexpected writer action {name}")

        def fake_update(model: str, model_id: int, payload: dict, wait: bool = False):
            del wait
            update_calls.append((model, model_id, payload))
            return SimpleNamespace(success=True, data={})

        with (
            patch.dict(
                "os.environ",
                {
                    "INA_ENABLED": "true",
                    "INA_BASE_URL": "http://ina.test",
                    "INA_TIMEOUT_SEC": "42",
                },
                clear=False,
            ),
            patch(
                "podcast_processor.podcast_processor.writer_client.action",
                side_effect=fake_action,
            ),
            patch(
                "podcast_processor.podcast_processor.writer_client.update",
                side_effect=fake_update,
            ),
            patch(
                "podcast_processor.podcast_processor.analyze_audio",
                return_value=(
                    [
                        AudioSegmentResult(label="music", start_time=0.0, end_time=1.0),
                        AudioSegmentResult(label="noise", start_time=1.0, end_time=2.0),
                    ],
                    '[{"label":"music"},{"label":"noise"}]',
                ),
            ) as analyze_mock,
        ):
            results = processor._run_ina_analysis(77, "/tmp/test.mp3")

        assert [result.label for result in results] == ["music", "noise"]
        analyze_mock.assert_called_once_with(
            audio_path="/tmp/test.mp3",
            base_url="http://ina.test",
            timeout=42,
        )
        # Stale-row cleanup runs first so the final UPDATE doesn't collide
        # with a prior run's identically-keyed ModelCall row.
        assert action_calls[0] == (
            "delete_model_calls_for_post_by_model_name",
            {"post_id": 77, "model_name": "ina:speech_music_noise"},
        )
        assert action_calls[1][0] == "upsert_model_call"
        assert action_calls[2][0] == "replace_audio_segments"
        assert action_calls[2][1]["post_id"] == 77
        assert action_calls[2][1]["model_call_id"] == 123
        assert action_calls[2][1]["segments"] == [
            {"label": "music", "start_time": 0.0, "end_time": 1.0},
            {"label": "noise", "start_time": 1.0, "end_time": 2.0},
        ]
        assert update_calls == [
            (
                "ModelCall",
                123,
                {
                    "status": "success",
                    "response": '[{"label":"music"},{"label":"noise"}]',
                    "error_message": None,
                    "first_segment_sequence_num": 0,
                    "last_segment_sequence_num": 1,
                },
            )
        ]


def test_run_ina_analysis_marks_model_call_failed_when_analysis_errors(app) -> None:
    with app.app_context():
        processor = PodcastProcessor(
            config=create_standard_test_config(),
            transcription_manager=MagicMock(spec=TranscriptionManager),
            ad_classifier=MagicMock(spec=AdClassifier),
            audio_processor=MagicMock(spec=AudioProcessor),
            status_manager=MagicMock(spec=ProcessingStatusManager),
            db_session=MagicMock(),
            downloader=MagicMock(spec=PodcastDownloader),
        )

        action_calls: list[tuple[str, dict]] = []

        def fake_action(name: str, payload: dict, wait: bool = False):
            del wait
            action_calls.append((name, payload))
            if name == "delete_model_calls_for_post_by_model_name":
                return SimpleNamespace(success=True, data={"deleted": 0})
            if name == "upsert_model_call":
                return SimpleNamespace(success=True, data={"model_call_id": 456})
            if name == "mark_model_call_failed":
                return SimpleNamespace(success=True, data={"updated": True})
            raise AssertionError(f"Unexpected writer action {name}")

        with (
            patch.dict(
                "os.environ",
                {
                    "INA_ENABLED": "true",
                    "INA_BASE_URL": "http://ina.test",
                },
                clear=False,
            ),
            patch(
                "podcast_processor.podcast_processor.writer_client.action",
                side_effect=fake_action,
            ),
            patch(
                "podcast_processor.podcast_processor.analyze_audio",
                side_effect=RuntimeError("ina boom"),
            ),
        ):
            try:
                processor._run_ina_analysis(88, "/tmp/test.mp3")
            except RuntimeError as exc:
                assert str(exc) == "ina boom"
            else:
                raise AssertionError("Expected INA analysis failure to propagate")

        assert action_calls[0][0] == "delete_model_calls_for_post_by_model_name"
        assert action_calls[1][0] == "upsert_model_call"
        assert action_calls[2] == (
            "mark_model_call_failed",
            {
                "model_call_id": 456,
                "error_message": "ina boom",
                "status": "failed_permanent",
            },
        )


def test_run_ina_analysis_surfaces_writer_update_failure(app) -> None:
    """When the final ModelCall UPDATE fails (e.g. unique-index collision on
    a stale row), the failure must propagate so the placeholder gets marked
    failed_permanent — not be silently swallowed, which would leave the row
    stuck at status="pending" and the post permanently "still processing".
    """
    with app.app_context():
        processor = PodcastProcessor(
            config=create_standard_test_config(),
            transcription_manager=MagicMock(spec=TranscriptionManager),
            ad_classifier=MagicMock(spec=AdClassifier),
            audio_processor=MagicMock(spec=AudioProcessor),
            status_manager=MagicMock(spec=ProcessingStatusManager),
            db_session=MagicMock(),
            downloader=MagicMock(spec=PodcastDownloader),
        )

        action_calls: list[tuple[str, dict]] = []

        def fake_action(name: str, payload: dict, wait: bool = False):
            del wait
            action_calls.append((name, payload))
            if name == "delete_model_calls_for_post_by_model_name":
                return SimpleNamespace(success=True, data={"deleted": 0})
            if name == "upsert_model_call":
                return SimpleNamespace(success=True, data={"model_call_id": 999})
            if name == "replace_audio_segments":
                return SimpleNamespace(success=True, data={"segment_count": 1})
            if name == "mark_model_call_failed":
                return SimpleNamespace(success=True, data={"updated": True})
            raise AssertionError(f"Unexpected writer action {name}")

        def fake_update(model: str, model_id: int, payload: dict, wait: bool = False):
            del model, model_id, payload, wait
            return SimpleNamespace(
                success=False,
                error="UNIQUE constraint failed: model_call...",
                data=None,
            )

        with (
            patch.dict(
                "os.environ",
                {"INA_ENABLED": "true", "INA_BASE_URL": "http://ina.test"},
                clear=False,
            ),
            patch(
                "podcast_processor.podcast_processor.writer_client.action",
                side_effect=fake_action,
            ),
            patch(
                "podcast_processor.podcast_processor.writer_client.update",
                side_effect=fake_update,
            ),
            patch(
                "podcast_processor.podcast_processor.analyze_audio",
                return_value=(
                    [AudioSegmentResult(label="music", start_time=0.0, end_time=1.0)],
                    "[]",
                ),
            ),
        ):
            try:
                processor._run_ina_analysis(101, "/tmp/test.mp3")
            except RuntimeError:
                pass
            else:
                raise AssertionError(
                    "Expected writer UPDATE failure to propagate as RuntimeError"
                )

        # Cleanup, upsert, replace_audio_segments, then the final failure
        # branch marks the call failed_permanent.
        action_names = [name for name, _ in action_calls]
        assert action_names == [
            "delete_model_calls_for_post_by_model_name",
            "upsert_model_call",
            "replace_audio_segments",
            "mark_model_call_failed",
        ]
