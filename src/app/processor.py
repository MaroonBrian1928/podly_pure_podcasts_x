from __future__ import annotations

from typing import TYPE_CHECKING

from app.runtime_config import config

if TYPE_CHECKING:
    from podcast_processor.podcast_processor import PodcastProcessor


class ProcessorSingleton:
    """Singleton class to manage the PodcastProcessor instance."""

    _instance: PodcastProcessor | None = None

    @classmethod
    def get_instance(cls) -> PodcastProcessor:
        """Get or create the PodcastProcessor instance."""
        if cls._instance is None:
            from podcast_processor.podcast_processor import PodcastProcessor

            cls._instance = PodcastProcessor(config)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        cls._instance = None


def get_processor() -> PodcastProcessor:
    """Get the PodcastProcessor instance."""
    return ProcessorSingleton.get_instance()
