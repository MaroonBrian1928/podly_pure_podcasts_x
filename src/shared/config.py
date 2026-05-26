from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from shared import defaults as DEFAULTS


class ProcessingConfig(BaseModel):
    num_segments_to_input_to_prompt: int
    max_overlap_segments: int = Field(
        default=DEFAULTS.PROCESSING_MAX_OVERLAP_SEGMENTS,
        ge=0,
        description="Maximum number of previously identified segments carried into the next prompt.",
    )

    @model_validator(mode="after")
    def validate_overlap_limits(self) -> ProcessingConfig:
        assert self.max_overlap_segments <= self.num_segments_to_input_to_prompt, (
            "max_overlap_segments must be <= num_segments_to_input_to_prompt"
        )
        return self


class OutputConfig(BaseModel):
    fade_ms: int
    bleep_padding_start_ms: int = Field(
        default=DEFAULTS.OUTPUT_BLEEP_PADDING_START_MS,
        ge=0,
        description="Milliseconds to include before each detected profanity word.",
    )
    bleep_padding_end_ms: int = Field(
        default=DEFAULTS.OUTPUT_BLEEP_PADDING_END_MS,
        ge=0,
        description="Milliseconds to include after each detected profanity word.",
    )
    min_ad_segement_separation_seconds: int
    min_ad_segment_length_seconds: int
    min_confidence: float
    auto_retry_zero_ads_on_parse_error: bool = Field(
        default=DEFAULTS.OUTPUT_AUTO_RETRY_ZERO_ADS_ON_PARSE_ERROR,
        description=(
            "Auto-requeue an LLM-strategy run once when it finishes with "
            "zero ad windows AND at least one classification batch parse "
            "failed. Off by default; only fires for posts where "
            "auto_retry_attempted is not already set."
        ),
    )

    @property
    def min_ad_segment_separation_seconds(self) -> int:
        """Backwards-compatible alias for the misspelled config field."""
        return self.min_ad_segement_separation_seconds

    @min_ad_segment_separation_seconds.setter
    def min_ad_segment_separation_seconds(self, value: int) -> None:
        self.min_ad_segement_separation_seconds = value


WhisperConfigTypes = Literal["remote", "test", "groq"]


class TestWhisperConfig(BaseModel):
    whisper_type: Literal["test"] = "test"


class RemoteWhisperConfig(BaseModel):
    whisper_type: Literal["remote"] = "remote"
    base_url: str = DEFAULTS.WHISPER_REMOTE_BASE_URL
    api_key: str
    language: str = DEFAULTS.WHISPER_REMOTE_LANGUAGE
    model: str = DEFAULTS.WHISPER_REMOTE_MODEL
    timeout_sec: int = DEFAULTS.WHISPER_REMOTE_TIMEOUT_SEC
    chunksize_mb: int = DEFAULTS.WHISPER_REMOTE_CHUNKSIZE_MB
    diarize: bool = DEFAULTS.WHISPER_REMOTE_DIARIZE
    speaker_embeddings: bool = DEFAULTS.WHISPER_REMOTE_SPEAKER_EMBEDDINGS

    @model_validator(mode="after")
    def validate_diarization_options(self) -> RemoteWhisperConfig:
        assert self.diarize or not self.speaker_embeddings, (
            "speaker_embeddings requires diarize=true"
        )
        return self


class GroqWhisperConfig(BaseModel):
    whisper_type: Literal["groq"] = "groq"
    api_key: str
    language: str = DEFAULTS.WHISPER_GROQ_LANGUAGE
    model: str = DEFAULTS.WHISPER_GROQ_MODEL
    max_retries: int = DEFAULTS.WHISPER_GROQ_MAX_RETRIES


class Config(BaseModel):
    llm_api_key: str | None = Field(default=None)
    llm_model: str = Field(default=DEFAULTS.LLM_DEFAULT_MODEL)
    openai_base_url: str | None = None
    openai_max_tokens: int = DEFAULTS.OPENAI_DEFAULT_MAX_TOKENS
    openai_timeout: int = DEFAULTS.OPENAI_DEFAULT_TIMEOUT_SEC
    # Optional: Rate limiting controls
    llm_max_concurrent_calls: int = Field(
        default=DEFAULTS.LLM_DEFAULT_MAX_CONCURRENT_CALLS,
        description="Maximum concurrent LLM calls to prevent rate limiting",
    )
    llm_max_retry_attempts: int = Field(
        default=DEFAULTS.LLM_DEFAULT_MAX_RETRY_ATTEMPTS,
        description="Maximum retry attempts for failed LLM calls",
    )
    llm_max_input_tokens_per_call: int | None = Field(
        default=DEFAULTS.LLM_MAX_INPUT_TOKENS_PER_CALL,
        description="Maximum input tokens per LLM call to stay under API limits",
    )
    # Token-based rate limiting
    llm_enable_token_rate_limiting: bool = Field(
        default=DEFAULTS.LLM_ENABLE_TOKEN_RATE_LIMITING,
        description="Enable client-side token-based rate limiting",
    )
    llm_max_input_tokens_per_minute: int | None = Field(
        default=DEFAULTS.LLM_MAX_INPUT_TOKENS_PER_MINUTE,
        description="Override default tokens per minute limit for the model",
    )
    enable_boundary_refinement: bool = Field(
        default=DEFAULTS.ENABLE_BOUNDARY_REFINEMENT,
        description="Enable LLM-based ad boundary refinement for improved precision (consumes additional LLM tokens)",
    )
    enable_word_level_boundary_refinder: bool = Field(
        default=DEFAULTS.ENABLE_WORD_LEVEL_BOUNDARY_REFINDER,
        description=(
            "Enable intra-segment ad boundary refinement. Uses saved word "
            "timestamps when available and falls back to segment-level heuristics."
        ),
    )
    llm_service_tier: str = Field(
        default=DEFAULTS.LLM_SERVICE_TIER,
        description=(
            "litellm service_tier passed to providers that support it "
            "(OpenAI, Gemini). Values: 'default' (unset), 'flex' (cheaper, "
            "slower, may 429/503 -- the wrapper retries with backoff and "
            "falls back to standard on exhaustion), 'priority' (faster, "
            "pricier), 'auto'. Ignored for providers without service tiers."
        ),
    )
    enable_llm_chapter_fallback_tagging: bool = Field(
        default=DEFAULTS.ENABLE_LLM_CHAPTER_FALLBACK_TAGGING,
        description=(
            "When enabled, LLM processing will preserve embedded chapters or "
            "generate fallback chapter tags from description/transcript."
        ),
    )
    developer_mode: bool = Field(
        default=False,
        description="Enable developer mode features like test feeds",
    )
    output: OutputConfig
    processing: ProcessingConfig
    server: str | None = Field(
        default=None,
        deprecated=True,
        description="deprecated in favor of request-aware URL generation",
    )
    background_update_interval_minute: int | None = (
        DEFAULTS.APP_BACKGROUND_UPDATE_INTERVAL_MINUTE
    )
    post_cleanup_retention_days: int | None = Field(
        default=DEFAULTS.APP_POST_CLEANUP_RETENTION_DAYS,
        description="Number of days to retain processed post data before cleanup. None disables cleanup.",
    )
    # removed job_timeout
    whisper: RemoteWhisperConfig | TestWhisperConfig | GroqWhisperConfig | None = Field(
        default=None,
        discriminator="whisper_type",
    )
    remote_whisper: bool | None = Field(
        default=False,
        deprecated=True,
        description="deprecated in favor of [Remote|Local]WhisperConfig",
    )
    whisper_model: str | None = Field(
        default=None,
        deprecated=True,
        description="deprecated in favor of RemoteWhisperConfig",
    )
    automatically_whitelist_new_episodes: bool = (
        DEFAULTS.APP_AUTOMATICALLY_WHITELIST_NEW_EPISODES
    )
    number_of_episodes_to_whitelist_from_archive_of_new_feed: int = (
        DEFAULTS.APP_NUM_EPISODES_TO_WHITELIST_FROM_ARCHIVE_OF_NEW_FEED
    )
    enable_public_landing_page: bool = DEFAULTS.APP_ENABLE_PUBLIC_LANDING_PAGE
    user_limit_total: int | None = DEFAULTS.APP_USER_LIMIT_TOTAL
    autoprocess_on_download: bool = DEFAULTS.APP_AUTOPROCESS_ON_DOWNLOAD
    cost_rate_per_hour: float = DEFAULTS.APP_COST_RATE_PER_HOUR

    @model_validator(mode="before")
    @classmethod
    def reject_local_whisper_config(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        whisper = data.get("whisper")
        if isinstance(whisper, dict) and whisper.get("whisper_type") == "local":
            raise ValueError(
                "WHISPER_TYPE=local is no longer supported. Run a dedicated "
                "OpenAI-compatible transcription service and configure "
                "WHISPER_TYPE=remote with WHISPER_REMOTE_BASE_URL."
            )
        return data

    def redacted(self) -> Config:
        return self.model_copy(
            update={
                "llm_api_key": "X" * 10,
            },
            deep=True,
        )

    @model_validator(mode="after")
    def validate_whisper_config(self) -> Config:
        new_style = self.whisper is not None

        if new_style:
            self.whisper_model = None
            self.remote_whisper = None
            return self

        # if we have old style, change to the equivalent new style
        if self.remote_whisper:
            assert self.llm_api_key is not None, (
                "must supply api key to use remote whisper"
            )
            self.whisper = RemoteWhisperConfig(
                api_key=self.llm_api_key,
                base_url=self.openai_base_url or "https://api.openai.com/v1",
            )
        elif "remote_whisper" not in self.model_fields_set and (
            "whisper_model" not in self.model_fields_set or self.whisper_model is None
        ):
            self.whisper = GroqWhisperConfig(api_key="")
        else:
            raise ValueError(
                "Old-style local Whisper config is no longer supported. "
                "Use whisper={whisper_type='remote', ...} or set "
                "remote_whisper=true with remote credentials."
            )

        self.whisper_model = None
        self.remote_whisper = None

        return self
