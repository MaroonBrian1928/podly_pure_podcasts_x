import logging
import shutil
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from groq import Groq
from openai import OpenAI
from pydantic import BaseModel

from podcast_processor.audio import split_audio
from shared.config import GroqWhisperConfig, RemoteWhisperConfig


class WordTimestamp(BaseModel):
    word: str
    start: float | None = None
    end: float | None = None
    score: float | None = None


class Segment(BaseModel):
    start: float
    end: float
    text: str
    speaker_label: str | None = None
    words: list[WordTimestamp] | None = None


class Transcriber(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @abstractmethod
    def transcribe(
        self, audio_file_path: str, *, include_word_timestamps: bool = False
    ) -> list[Segment]:
        pass


class LocalTranscriptSegment(BaseModel):
    id: int
    seek: int
    start: float
    end: float
    text: str
    tokens: list[int]
    temperature: float
    avg_logprob: float
    compression_ratio: float
    no_speech_prob: float

    def to_segment(self) -> Segment:
        return Segment(start=self.start, end=self.end, text=self.text)


class TestWhisperTranscriber(Transcriber):
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    @property
    def model_name(self) -> str:
        return "test_whisper"

    def transcribe(
        self, audio_file_path: str, *, include_word_timestamps: bool = False
    ) -> list[Segment]:
        del audio_file_path
        del include_word_timestamps
        self.logger.info("Using test whisper")
        return [
            Segment(start=0, end=1, text="This is a test"),
            Segment(start=1, end=2, text="This is another test"),
        ]


class LocalWhisperTranscriber(Transcriber):
    def __init__(self, logger: logging.Logger, whisper_model: str):
        self.logger = logger
        self.whisper_model = whisper_model

    @property
    def model_name(self) -> str:
        return f"local_{self.whisper_model}"

    @staticmethod
    def convert_to_pydantic(
        transcript_data: list[Any],
    ) -> list[LocalTranscriptSegment]:
        return [LocalTranscriptSegment(**item) for item in transcript_data]

    @staticmethod
    def local_seg_to_seg(local_segments: list[LocalTranscriptSegment]) -> list[Segment]:
        return [seg.to_segment() for seg in local_segments]

    def transcribe(
        self, audio_file_path: str, *, include_word_timestamps: bool = False
    ) -> list[Segment]:
        del include_word_timestamps
        # Import whisper only when needed to avoid CUDA dependencies during module import
        try:
            import whisper
        except ImportError as e:
            self.logger.error(f"Failed to import whisper: {e}")
            raise ImportError(
                "whisper library is required for LocalWhisperTranscriber"
            ) from e

        self.logger.info("Using local whisper")
        models = whisper.available_models()
        self.logger.info(f"Available models: {models}")

        model = whisper.load_model(name=self.whisper_model)

        self.logger.info("Beginning transcription")
        start = time.time()
        result = model.transcribe(audio_file_path, fp16=False, language="English")
        end = time.time()
        elapsed = end - start
        self.logger.info(f"Transcription completed in {elapsed}")
        segments = result["segments"]
        typed_segments = self.convert_to_pydantic(segments)

        return self.local_seg_to_seg(typed_segments)


class OpenAIWhisperTranscriber(Transcriber):
    def __init__(self, logger: logging.Logger, config: RemoteWhisperConfig):
        self.logger = logger
        self.config = config

        self.openai_client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout_sec,
        )

    @property
    def model_name(self) -> str:
        return self.config.model  # e.g. "whisper-1"

    def transcribe(
        self, audio_file_path: str, *, include_word_timestamps: bool = False
    ) -> list[Segment]:
        self.logger.info(
            "[WHISPER_REMOTE] Starting remote whisper transcription for: %s",
            audio_file_path,
        )
        audio_chunk_path = audio_file_path + "_parts"

        chunks = split_audio(
            Path(audio_file_path),
            Path(audio_chunk_path),
            self.config.chunksize_mb * 1024 * 1024,
        )

        self.logger.info("[WHISPER_REMOTE] Processing %d chunks", len(chunks))
        all_segments: list[Segment] = []

        for idx, chunk in enumerate(chunks):
            chunk_path, offset = chunk
            self.logger.info(
                "[WHISPER_REMOTE] Processing chunk %d/%d: %s",
                idx + 1,
                len(chunks),
                chunk_path,
            )
            segments = self.get_segments_for_chunk(
                str(chunk_path),
                include_word_timestamps=include_word_timestamps,
            )
            self.logger.info(
                "[WHISPER_REMOTE] Chunk %d/%d complete: %d segments",
                idx + 1,
                len(chunks),
                len(segments),
            )
            all_segments.extend(self.add_offset_to_segments(segments, offset))

        shutil.rmtree(audio_chunk_path)
        self.logger.info(
            "[WHISPER_REMOTE] Transcription complete: %d total segments",
            len(all_segments),
        )
        return all_segments

    @staticmethod
    def add_offset_to_segments(
        segments: list[Segment], offset_ms: int
    ) -> list[Segment]:
        offset_sec = float(offset_ms) / 1000.0
        for segment in segments:
            segment.start += offset_sec
            segment.end += offset_sec
            if segment.words:
                for word in segment.words:
                    if word.start is not None:
                        word.start += offset_sec
                    if word.end is not None:
                        word.end += offset_sec

        return segments

    def build_transcription_request_kwargs(
        self,
        audio_file: Any,
        *,
        include_word_timestamps: bool = False,
    ) -> dict[str, Any]:
        request_kwargs: dict[str, Any] = {
            "model": self.config.model,
            "file": audio_file,
            "timestamp_granularities": (
                ["segment", "word"] if include_word_timestamps else ["segment"]
            ),
            "language": self.config.language,
            "response_format": "verbose_json",
        }

        extra_body: dict[str, Any] = {}
        if include_word_timestamps:
            extra_body["align"] = True

        if self.config.diarize:
            extra_body["align"] = True
            extra_body["diarize"] = True
            if self.config.speaker_embeddings:
                extra_body["speaker_embeddings"] = True

        if extra_body:
            request_kwargs["extra_body"] = extra_body

        return request_kwargs

    @staticmethod
    def _get_segment_field(segment: Any, field_name: str) -> Any | None:
        if isinstance(segment, dict):
            return segment.get(field_name)
        return getattr(segment, field_name, None)

    @classmethod
    def _get_word_entries(cls, segment: Any) -> list[Any]:
        words = cls._get_segment_field(segment, "words")
        if isinstance(words, list):
            return words

        word_segments = cls._get_segment_field(segment, "word_segments")
        if isinstance(word_segments, list):
            return word_segments

        return []

    @classmethod
    def _parse_word(cls, word: Any) -> WordTimestamp | None:
        text = cls._get_segment_field(word, "word")
        if text is None:
            return None

        start = cls._get_segment_field(word, "start")
        end = cls._get_segment_field(word, "end")
        score = cls._get_segment_field(word, "score")

        return WordTimestamp(
            word=str(text),
            start=float(start) if start is not None else None,
            end=float(end) if end is not None else None,
            score=float(score) if score is not None else None,
        )

    @classmethod
    def _get_speaker_label(cls, segment: Any) -> str | None:
        for field_name in ("speaker_label", "speaker", "speaker_id"):
            value = cls._get_segment_field(segment, field_name)
            if value is None:
                continue

            speaker_label = str(value).strip()
            if speaker_label:
                return speaker_label

        return None

    @classmethod
    def _parse_segment(cls, segment: Any) -> Segment:
        start = cls._get_segment_field(segment, "start")
        end = cls._get_segment_field(segment, "end")
        text = cls._get_segment_field(segment, "text")

        if start is None or end is None or text is None:
            raise ValueError(
                "Remote transcription segment is missing one of required fields: "
                "start, end, text"
            )

        parsed_words = [
            parsed_word
            for parsed_word in (
                cls._parse_word(word) for word in cls._get_word_entries(segment)
            )
            if parsed_word is not None
        ]

        return Segment(
            start=float(start),
            end=float(end),
            text=str(text),
            speaker_label=cls._get_speaker_label(segment),
            words=parsed_words or None,
        )

    @classmethod
    def extract_segments_from_transcription(cls, transcription: Any) -> list[Segment]:
        segment_payloads: Any | None = None
        if isinstance(transcription, dict):
            segment_payloads = transcription.get("segments")
        else:
            segment_payloads = getattr(transcription, "segments", None)
            if segment_payloads is None and hasattr(transcription, "to_dict"):
                serialized = transcription.to_dict()
                if isinstance(serialized, dict):
                    segment_payloads = serialized.get("segments")

        if segment_payloads is None:
            return []

        if isinstance(segment_payloads, dict):
            nested_segments = segment_payloads.get("segments")
            if nested_segments is None:
                raise ValueError(
                    "Remote transcription segments dict is missing nested 'segments' list"
                )
            segment_payloads = nested_segments

        if not isinstance(segment_payloads, list):
            raise ValueError(
                f"Remote transcription segments must be a list, got {type(segment_payloads).__name__}"
            )

        return [cls._parse_segment(segment) for segment in segment_payloads]

    def get_segments_for_chunk(
        self,
        chunk_path: str,
        *,
        include_word_timestamps: bool = False,
    ) -> list[Segment]:
        with open(chunk_path, "rb") as f:
            self.logger.info(
                "[WHISPER_API_CALL] Sending chunk to API: %s (timeout=%ds diarize=%s speaker_embeddings=%s include_word_timestamps=%s)",
                chunk_path,
                self.config.timeout_sec,
                self.config.diarize,
                self.config.speaker_embeddings,
                include_word_timestamps,
            )

            transcription = self.openai_client.audio.transcriptions.create(
                **self.build_transcription_request_kwargs(
                    f,
                    include_word_timestamps=include_word_timestamps,
                ),
            )

            self.logger.debug(
                "Got transcription response type: %s",
                type(transcription).__name__,
            )

            segments = self.extract_segments_from_transcription(transcription)

            self.logger.debug("Got %d segments", len(segments))

            return segments


class GroqTranscriptionSegment(BaseModel):
    start: float
    end: float
    text: str


class GroqWhisperTranscriber(Transcriber):
    def __init__(self, logger: logging.Logger, config: GroqWhisperConfig):
        self.logger = logger
        self.config = config
        self.client = Groq(
            api_key=config.api_key,
            max_retries=config.max_retries,
        )

    @property
    def model_name(self) -> str:
        return f"groq_{self.config.model}"

    def transcribe(
        self, audio_file_path: str, *, include_word_timestamps: bool = False
    ) -> list[Segment]:
        del include_word_timestamps
        self.logger.info(
            "[WHISPER_GROQ] Starting Groq whisper transcription for: %s",
            audio_file_path,
        )
        audio_chunk_path = audio_file_path + "_parts"

        # 12MB seems to cause instability in Groq
        chunks = split_audio(
            Path(audio_file_path), Path(audio_chunk_path), 6 * 1024 * 1024
        )

        self.logger.info("[WHISPER_GROQ] Processing %d chunks", len(chunks))
        all_segments: list[GroqTranscriptionSegment] = []

        for idx, chunk in enumerate(chunks):
            chunk_path, offset = chunk
            self.logger.info(
                "[WHISPER_GROQ] Processing chunk %d/%d: %s",
                idx + 1,
                len(chunks),
                chunk_path,
            )
            segments = self.get_segments_for_chunk(str(chunk_path))
            self.logger.info(
                "[WHISPER_GROQ] Chunk %d/%d complete: %d segments",
                idx + 1,
                len(chunks),
                len(segments),
            )
            all_segments.extend(self.add_offset_to_segments(segments, offset))

        shutil.rmtree(audio_chunk_path)
        self.logger.info(
            "[WHISPER_GROQ] Transcription complete: %d total segments",
            len(all_segments),
        )
        return self.convert_segments(all_segments)

    @staticmethod
    def convert_segments(segments: list[GroqTranscriptionSegment]) -> list[Segment]:
        return [
            Segment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
            )
            for seg in segments
        ]

    @staticmethod
    def add_offset_to_segments(
        segments: list[GroqTranscriptionSegment], offset_ms: int
    ) -> list[GroqTranscriptionSegment]:
        offset_sec = float(offset_ms) / 1000.0
        for segment in segments:
            segment.start += offset_sec
            segment.end += offset_sec

        return segments

    def get_segments_for_chunk(self, chunk_path: str) -> list[GroqTranscriptionSegment]:
        retries = self.config.max_retries if self.config.max_retries is not None else 0
        max_attempts = retries + 1
        for attempt in range(1, max_attempts + 1):
            self.logger.info(
                "[GROQ_API_CALL] Sending chunk to Groq API: %s (attempt %d/%d)",
                chunk_path,
                attempt,
                max_attempts,
            )
            try:
                transcription = self.client.audio.transcriptions.create(
                    file=Path(chunk_path),
                    model=self.config.model,
                    response_format="verbose_json",  # Ensure segments are included
                    language=self.config.language,
                )
            except Exception as exc:
                self.logger.warning(
                    "[GROQ_API_CALL] Attempt %d/%d failed for %s: %s",
                    attempt,
                    max_attempts,
                    chunk_path,
                    exc,
                )
                if attempt == max_attempts:
                    raise
                time.sleep(1.5**attempt)
                continue

            self.logger.info(
                "[GROQ_API_CALL] Received response from Groq API for: %s (attempt %d/%d)",
                chunk_path,
                attempt,
                max_attempts,
            )

            if transcription.segments is None:  # type: ignore [attr-defined]
                self.logger.warning(
                    "[GROQ_API_CALL] No segments found in transcription for %s",
                    chunk_path,
                )
                return []

            groq_segments = [
                GroqTranscriptionSegment(
                    start=seg["start"], end=seg["end"], text=seg["text"]
                )
                for seg in transcription.segments  # type: ignore [attr-defined]
            ]

            self.logger.info(
                "[GROQ_API_CALL] Got %d segments from chunk (attempt %d/%d)",
                len(groq_segments),
                attempt,
                max_attempts,
            )
            return groq_segments

        # unreachable, but satisfies type checker
        return []
