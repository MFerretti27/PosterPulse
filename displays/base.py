import abc
from dataclasses import dataclass

from PIL import Image  # pyright: ignore[reportMissingImports]


@dataclass
class PosterDisplayItem:
    item_id: str
    title: str
    image: Image.Image
    is_playing: bool = False
    user_name: str | None = None
    connection_lost: bool = False
    playback_progress: float | None = None


class BaseDisplay(abc.ABC):
    """Abstract base class for PosterPulse display backends."""

    @abc.abstractmethod
    def run(self) -> None:
        """Start the display main loop."""
        raise NotImplementedError

    @abc.abstractmethod
    def cleanup(self) -> None:
        """Perform any teardown or release of hardware resources."""
        raise NotImplementedError
