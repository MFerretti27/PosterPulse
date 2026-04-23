import io
import logging
import os
import random
import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv
from PIL import Image, ImageTk
import tkinter as tk


logger = logging.getLogger(__name__)


@dataclass
class Settings:
    jellyfin_url: str
    api_token: str
    user_id: Optional[str]
    refresh_seconds: int
    background_color: str
    window_title: str
    fullscreen: bool

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        jellyfin_url = os.getenv("JELLYFIN_URL", "").strip().rstrip("/")
        api_token = os.getenv("JELLYFIN_API_TOKEN", "").strip()
        user_id = os.getenv("JELLYFIN_USER_ID", "").strip() or None

        if not jellyfin_url:
            raise ValueError("JELLYFIN_URL is required")
        if not api_token:
            raise ValueError("JELLYFIN_API_TOKEN is required")

        refresh_seconds = int(os.getenv("REFRESH_SECONDS", "30"))
        background_color = os.getenv("BACKGROUND_COLOR", "black")
        window_title = os.getenv("WINDOW_TITLE", "Jellyfin Poster Display")
        fullscreen = os.getenv("FULLSCREEN", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        return cls(
            jellyfin_url=jellyfin_url,
            api_token=api_token,
            user_id=user_id,
            refresh_seconds=refresh_seconds,
            background_color=background_color,
            window_title=window_title,
            fullscreen=fullscreen,
        )


class JellyfinClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.jellyfin_url
        self.user_id = settings.user_id
        self.session = requests.Session()
        self.session.headers.update({"X-Emby-Token": settings.api_token})

    @staticmethod
    def _looks_like_jellyfin_id(value: str) -> bool:
        # Jellyfin IDs are typically hex strings (sometimes UUID-like with dashes).
        return bool(re.fullmatch(r"[0-9a-fA-F]{32}|[0-9a-fA-F-]{36}", value))

    @staticmethod
    def _response_preview(response: requests.Response) -> str:
        body = response.text.strip()
        if len(body) > 220:
            body = f"{body[:220]}..."
        return body or "<empty body>"

    def _get(self, url: str, *, params: Optional[dict] = None, timeout: int = 10) -> requests.Response:
        response = self.session.get(url, params=params, timeout=timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Jellyfin HTTP {response.status_code} for {response.url}. Response: {self._response_preview(response)}"
            ) from exc
        return response

    def _resolve_user_name_to_id(self, user_name: str) -> Optional[str]:
        url = f"{self.base_url}/Users"
        response = self._get(url, timeout=10)
        users = response.json()
        for user in users:
            if str(user.get("Name", "")).lower() == user_name.lower() and user.get("Id"):
                return user["Id"]
        return None

    def resolve_user_id(self) -> str:
        if self.user_id:
            if not self._looks_like_jellyfin_id(self.user_id):
                resolved_from_name = self._resolve_user_name_to_id(self.user_id)
                if not resolved_from_name:
                    raise ValueError(
                        "JELLYFIN_USER_ID is not a valid user Id and did not match any username. "
                        "Set it to a valid Id, a valid username, or leave it blank for /Users/Me."
                    )
                self.user_id = resolved_from_name
            return self.user_id

        url = f"{self.base_url}/Users/Me"
        response = self._get(url, timeout=10)
        payload = response.json()
        resolved = payload.get("Id")
        if not resolved:
            raise RuntimeError("Unable to resolve user id from /Users/Me")

        self.user_id = resolved
        return resolved

    def get_random_poster_image(self, max_width: int, max_height: int, last_item_id: Optional[str] = None):
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

        # Avoid showing the same poster twice in a row when possible.
        candidates = [item for item in items if item.get("Id") != last_item_id] or items
        chosen = random.choice(candidates)
        item_id = chosen["Id"]

        image = self.get_item_poster_image(item_id=item_id, max_width=max_width, max_height=max_height)
        return item_id, chosen.get("Name", "Unknown Title"), image

    def get_active_movie_sessions(self) -> List[Dict[str, str]]:
        sessions_url = f"{self.base_url}/Sessions"
        response = self._get(sessions_url, params={"ActiveWithinSeconds": "3600"}, timeout=15)
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

    def get_item_poster_image(self, item_id: str, max_width: int, max_height: int) -> Image.Image:
        image_url = f"{self.base_url}/Items/{item_id}/Images/Primary"
        image_params = {
            "MaxWidth": str(max_width),
            "MaxHeight": str(max_height),
            "Quality": "90",
        }

        image_response = self._get(image_url, params=image_params, timeout=20)
        return Image.open(io.BytesIO(image_response.content)).convert("RGB")


class PosterDisplayApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = JellyfinClient(settings)
        self.last_item_id: Optional[str] = None
        self.active_rotation_index = 0

        self.root = tk.Tk()
        self.root.title(settings.window_title)
        self.root.configure(bg=settings.background_color)
        self.root.bind("<Escape>", lambda _event: self.exit_app())

        if settings.fullscreen:
            self.root.attributes("-fullscreen", True)

        self.top_banner = tk.Label(
            self.root,
            text="Currently Playing",
            anchor="center",
            bg="#8B0000",
            fg="white",
            padx=10,
            pady=8,
            font=("Helvetica", 18, "bold"),
        )
        self.banner_visible = False

        self.label = tk.Label(self.root, bg=settings.background_color)
        self.label.pack(fill=tk.BOTH, expand=True)

        self.status = tk.Label(
            self.root,
            text="Loading...",
            anchor="w",
            bg=settings.background_color,
            fg="white",
            padx=10,
            pady=8,
        )
        self.status.pack(fill=tk.X)

        self._tk_image = None

    def exit_app(self) -> None:
        self.root.destroy()

    def _fit_to_screen(self, image: Image.Image) -> Image.Image:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        img_w, img_h = image.size
        scale = min(screen_w / img_w, screen_h / img_h)
        new_size = (max(1, int(img_w * scale)), max(1, int(img_h * scale)))
        return image.resize(new_size, Image.Resampling.LANCZOS)

    def _show_top_banner(self) -> None:
        if not self.banner_visible:
            self.top_banner.place(x=0, y=0, relwidth=1.0)
            self.top_banner.lift()
            self.banner_visible = True

    def _hide_top_banner(self) -> None:
        if self.banner_visible:
            self.top_banner.place_forget()
            self.banner_visible = False

    def refresh_once(self) -> None:
        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            active_movies = self.client.get_active_movie_sessions()

            if active_movies:
                selected = active_movies[self.active_rotation_index % len(active_movies)]
                self.active_rotation_index += 1
                item_id = selected["item_id"]
                title = selected["title"]
                user_name = selected["user_name"]
                image = self.client.get_item_poster_image(item_id=item_id, max_width=screen_w, max_height=screen_h)
                status_text = f"Watching now: {user_name} - {title}"
                self._show_top_banner()
                users_playing = ", ".join(
                    f"{movie['user_name']}: {movie['title']}" for movie in active_movies
                )
                logger.info("Users Playing: %s", users_playing)
            else:
                self.active_rotation_index = 0
                item_id, title, image = self.client.get_random_poster_image(
                    max_width=screen_w,
                    max_height=screen_h,
                    last_item_id=self.last_item_id,
                )
                status_text = f"No active movie sessions. Random poster: {title}"
                self._hide_top_banner()
                logger.info("random movie poster grabbed: %s", title)

            fitted = self._fit_to_screen(image)
            self._tk_image = ImageTk.PhotoImage(fitted)
            self.label.configure(image=self._tk_image)
            self.status.configure(text=status_text)
            self.last_item_id = item_id
        except Exception as exc:
            logger.exception("Poll failed: %s", exc)
            self.status.configure(text=f"Error: {exc}")

        self.root.after(self.settings.refresh_seconds * 1000, self.refresh_once)

    def run(self) -> None:
        self.refresh_once()
        self.root.mainloop()


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

    app = PosterDisplayApp(settings)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
