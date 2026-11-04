import io
import logging
import os
import random
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests  # type: ignore[import]
from dotenv import load_dotenv  # type: ignore[import]
from PIL import Image  # type: ignore[import]

from displays.base import BaseDisplay, PosterDisplayItem

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    jellyfin_url: str
    api_token: str
    display_type: str = "regular"  # "regular" or "eink"
    refresh_seconds: int = 30
    background_color: str = "black"
    fullscreen: bool = True
    fade_speed: int = 8  # 1 (slowest) to 10 (fastest)
    selected_movies: List[str] = field(default_factory=list)
    idle_refresh_minutes: int = 30

    # E-Ink specific settings (optimized for Waveshare 7.3" PhotoPainter)
    eink_width: int = 800
    eink_height: int = 480
    eink_rotation: int = 0  # 0, 90, 180, 270 (180 if orientation is reversed in frame)
    eink_preview_path: Optional[str] = "eink_preview.png"
    eink_pwr_pin: int = 27  # BCM 27 on Waveshare PhotoPainter PCB

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        jellyfin_url = os.getenv("JELLYFIN_URL", "").strip().rstrip("/")
        api_token = os.getenv("JELLYFIN_API_TOKEN", "").strip()

        if not jellyfin_url:
            raise ValueError("JELLYFIN_URL is required")
        if not api_token:
            raise ValueError("JELLYFIN_API_TOKEN is required")

        display_type = os.getenv("DISPLAY_TYPE", "regular").strip().lower()
        if display_type in {"e-ink", "epaper", "epd", "photopainter"}:
            display_type = "eink"
        elif display_type in {"screen", "hdmi", "monitor", "gui", "tkinter"}:
            display_type = "regular"

        refresh_seconds = int(os.getenv("REFRESH_SECONDS", "30"))
        background_color = os.getenv("BACKGROUND_COLOR", "black")
        fullscreen = os.getenv("FULLSCREEN", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        fade_speed = max(1, min(10, int(os.getenv("FADE_SPEED", "8"))))
        selected_movies = [
            title.strip()
            for title in os.getenv("SELECT_MOVIES", "").split(",")
            if title.strip()
        ]

        eink_width = int(os.getenv("EINK_WIDTH", "800"))
        eink_height = int(os.getenv("EINK_HEIGHT", "480"))
        eink_rotation = int(os.getenv("EINK_ROTATION", "0"))
        idle_refresh_minutes = int(
            os.getenv(
                "IDLE_REFRESH_MINUTES",
                os.getenv("EINK_IDLE_REFRESH_MINUTES", "30"),
            )
        )
        raw_preview = os.getenv("EINK_PREVIEW_PATH", "eink_preview.png")
        eink_preview_path: Optional[str] = raw_preview if raw_preview.strip() else None
        eink_pwr_pin = int(os.getenv("EINK_PWR_PIN", "27"))

        return cls(
            jellyfin_url=jellyfin_url,
            api_token=api_token,
            display_type=display_type,
            refresh_seconds=refresh_seconds,
            background_color=background_color,
            fullscreen=fullscreen,
            fade_speed=fade_speed,
            selected_movies=selected_movies,
            idle_refresh_minutes=idle_refresh_minutes,
            eink_width=eink_width,
            eink_height=eink_height,
            eink_rotation=eink_rotation,
            eink_preview_path=eink_preview_path,
            eink_pwr_pin=eink_pwr_pin,
        )


class JellyfinClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.jellyfin_url
        self.user_id: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": (
                    'MediaBrowser Client="PosterPulse", Device="Poster Display", '
                    'DeviceId="poster-pulse", Version="1.0", '
                    f'Token="{settings.api_token}"'
                )
            }
        )

    @staticmethod
    def _response_preview(response: requests.Response) -> str:
        body = response.text.strip()
        if len(body) > 220:
            body = f"{body[:220]}..."
        return body or "<empty body>"

    def _get(
        self, url: str, *, params: Optional[dict] = None, timeout: int = 10
    ) -> requests.Response:
        response = self.session.get(url, params=params, timeout=timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Jellyfin HTTP {response.status_code} for {response.url}. Response: {self._response_preview(response)}"
            ) from exc
        return response

    def resolve_user_id(self) -> str:
        if self.user_id:
            return self.user_id

        # /Users/Me works with session tokens; API keys need /Users list.
        try:
            response = self._get(f"{self.base_url}/Users/Me", timeout=10)
            resolved = response.json().get("Id")
            if resolved:
                self.user_id = resolved
                return resolved
        except RuntimeError:
            pass

        users = self._get(f"{self.base_url}/Users", timeout=10).json()
        resolved = next((u["Id"] for u in users if u.get("Id")), None)
        if not resolved:
            raise RuntimeError("Could not resolve a Jellyfin user id.")
        self.user_id = resolved
        return resolved

    def get_random_poster_image(
        self,
        max_width: int,
        max_height: int,
        last_item_id: Optional[str] = None,
        selected_movies: Optional[List[str]] = None,
    ):
        user_id = self.resolve_user_id()

        items_url = f"{self.base_url}/Users/{user_id}/Items"
        params = {
            "Recursive": "true",
            "IncludeItemTypes": "Movie",
            "Fields": "PrimaryImageAspectRatio",
            "HasPrimaryImage": "true",
            "Limit": "500",
        }

        response = self._get(items_url, params=params, timeout=15)
        payload = response.json()
        items = payload.get("Items", [])

        if not items:
            raise RuntimeError("No movies with posters were found in Jellyfin")

        if selected_movies:
            wanted_titles = {title.casefold() for title in selected_movies}
            filtered_items = [
                item
                for item in items
                if str(item.get("Name", "")).strip().casefold() in wanted_titles
            ]
            if not filtered_items:
                raise RuntimeError(
                    "SELECT_MOVIES is set, but none of those movie titles were found with posters."
                )
            items = filtered_items

        # Avoid showing the same poster twice in a row when possible.
        candidates = [item for item in items if item.get("Id") != last_item_id] or items
        chosen = random.choice(candidates)
        item_id = chosen["Id"]

        image = self.get_item_poster_image(
            item_id=item_id, max_width=max_width, max_height=max_height
        )
        return item_id, chosen.get("Name", "Unknown Title"), image

    def get_active_movie_sessions(self) -> List[Dict[str, str]]:
        sessions_url = f"{self.base_url}/Sessions"
        response = self._get(
            sessions_url, params={"ActiveWithinSeconds": "3600"}, timeout=15
        )
        sessions = response.json()
        active_movies: List[Dict[str, str]] = []

        for session in sessions:
            now_playing = session.get("NowPlayingItem") or {}
            if now_playing.get("Type") != "Movie":
                continue

            item_id = now_playing.get("Id")
            if not item_id:
                continue

            active_movies.append(
                {
                    "session_id": str(session.get("Id", "unknown-session")),
                    "item_id": str(item_id),
                    "title": str(now_playing.get("Name", "Unknown Title")),
                    "user_name": str(session.get("UserName", "Unknown User")),
                }
            )

        return active_movies

    def get_item_poster_image(
        self, item_id: str, max_width: int, max_height: int
    ) -> Image.Image:
        image_url = f"{self.base_url}/Items/{item_id}/Images/Primary"
        image_params = {
            "MaxWidth": str(max_width),
            "MaxHeight": str(max_height),
            "Quality": "90",
        }

        image_response = self._get(image_url, params=image_params, timeout=20)
        return Image.open(io.BytesIO(image_response.content)).convert("RGB")


class PosterCoordinator:
    """Coordinates fetching poster data and managing playback/idle rotation state."""

    def __init__(self, client: JellyfinClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.last_item_id: Optional[str] = None
        self.active_rotation_index = 0

    def fetch_item(
        self, width: int, height: int, allow_idle_poster: bool = True
    ) -> Optional[PosterDisplayItem]:
        active_movies = self.client.get_active_movie_sessions()

        if active_movies:
            selected = active_movies[self.active_rotation_index % len(active_movies)]
            self.active_rotation_index += 1
            item_id = selected["item_id"]
            title = selected["title"]
            user_name = selected["user_name"]
            image = self.client.get_item_poster_image(
                item_id=item_id, max_width=width, max_height=height
            )
            self.last_item_id = item_id

            users_playing = ", ".join(
                f"{movie['user_name']}: {movie['title']}" for movie in active_movies
            )
            logger.info("Active movie sessions (%s): '%s'", users_playing, title)
            return PosterDisplayItem(
                item_id=item_id,
                title=title,
                image=image,
                is_playing=True,
                user_name=user_name,
            )

        if not allow_idle_poster:
            return None

        self.active_rotation_index = 0
        item_id, title, image = self.client.get_random_poster_image(
            max_width=width,
            max_height=height,
            last_item_id=self.last_item_id,
            selected_movies=self.settings.selected_movies,
        )
        self.last_item_id = item_id
        logger.info("Fetched idle poster: '%s'", title)
        return PosterDisplayItem(
            item_id=item_id,
            title=title,
            image=image,
            is_playing=False,
        )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    try:
        settings = Settings.from_env()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    client = JellyfinClient(settings)
    coordinator = PosterCoordinator(client, settings)

    display_app: BaseDisplay
    if settings.display_type == "eink":
        logger.info(
            "Initializing E-Ink display mode (%dx%d, PhotoPainter PWR=BCM %d)",
            settings.eink_width,
            settings.eink_height,
            settings.eink_pwr_pin,
        )
        from displays.eink import EInkDisplay

        display_app = EInkDisplay(
            fetch_content_fn=coordinator.fetch_item,
            width=settings.eink_width,
            height=settings.eink_height,
            rotation=settings.eink_rotation,
            idle_refresh_minutes=settings.idle_refresh_minutes,
            poll_interval_seconds=settings.refresh_seconds,
            preview_path=settings.eink_preview_path,
            pwr_pin=settings.eink_pwr_pin,
        )
    else:
        logger.info("Initializing Regular (HDMI / GUI) display mode")
        from displays.regular import RegularDisplay

        display_app = RegularDisplay(
            fetch_content_fn=coordinator.fetch_item,
            refresh_seconds=settings.refresh_seconds,
            idle_refresh_minutes=settings.idle_refresh_minutes,
            background_color=settings.background_color,
            fullscreen=settings.fullscreen,
            fade_speed=settings.fade_speed,
        )

    try:
        display_app.run()
    except KeyboardInterrupt:
        logger.info("Exiting on user interrupt.")
    finally:
        display_app.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
