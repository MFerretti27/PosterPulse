import abc
from dataclasses import dataclass
from typing import Optional
from PIL import Image


@dataclass
class PosterDisplayItem:
    item_id: str
    title: str
    image: Image.Image
    is_playing: bool = False
    user_name: Optional[str] = None


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
