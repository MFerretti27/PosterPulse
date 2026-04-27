import io
import logging
import os
import random
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests  # type: ignore[import]
from dotenv import load_dotenv  # type: ignore[import]
from PIL import Image, ImageTk  # type: ignore[import]
import tkinter as tk


logger = logging.getLogger(__name__)


@dataclass
class Settings:
    jellyfin_url: str
    api_token: str
    refresh_seconds: int
    background_color: str
    fullscreen: bool
    fade_speed: int  # 1 (slowest) to 10 (fastest)
    selected_movies: List[str]

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        jellyfin_url = os.getenv("JELLYFIN_URL", "").strip().rstrip("/")
        api_token = os.getenv("JELLYFIN_API_TOKEN", "").strip()

        if not jellyfin_url:
            raise ValueError("JELLYFIN_URL is required")
        if not api_token:
            raise ValueError("JELLYFIN_API_TOKEN is required")

        refresh_seconds = int(os.getenv("REFRESH_SECONDS", "30"))
        background_color = os.getenv("BACKGROUND_COLOR", "black")
        fullscreen = os.getenv("FULLSCREEN", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        fade_speed = max(1, min(10, int(os.getenv("FADE_SPEED", "5"))))
        selected_movies = [
            title.strip()
            for title in os.getenv("SELECT_MOVIES", "").split(",")
            if title.strip()
        ]

        return cls(
            jellyfin_url=jellyfin_url,
            api_token=api_token,
            refresh_seconds=refresh_seconds,
            background_color=background_color,
            fullscreen=fullscreen,
            fade_speed=fade_speed,
            selected_movies=selected_movies,
        )


class JellyfinClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.jellyfin_url
        self.user_id: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({"X-Emby-Token": settings.api_token})

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
    # Crossfade tuning: macOS timer resolution floors at ~15 ms per frame, so
    # reducing FADE_INTERVAL_MS alone won't speed things up past a point.
    # Both FADE_STEPS and FADE_INTERVAL_MS scale down with higher speeds so
    # the total frame count (and thus wall time) genuinely shrinks:
    #   speed 1  → 30 steps × 200 ms = ~6 s
    #   speed 5  → 16 steps × 30 ms  = ~0.5 s
    #   speed 10 → 4 steps  × 15 ms  = ~0.06 s (nearly instant)

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        s = settings.fade_speed  # 1–10
        # Steps: 30 at speed 1, down to 4 at speed 10 (fewer frames = faster)
        self.FADE_STEPS = max(4, 32 - s * 3)
        # Interval: 200 ms at speed 1, 15 ms at speed 10 (OS timer floor ~15 ms)
        self.FADE_INTERVAL_MS = max(15, 215 - s * 20)
        self.client = JellyfinClient(settings)
        self.last_item_id: Optional[str] = None
        self.active_rotation_index = 0
        self._current_canvas: Optional[Image.Image] = None

        self.root = tk.Tk()
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

    def _on_black_canvas(self, image: Image.Image) -> Image.Image:
        """Paste *image* centred on a full-screen black canvas."""
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        canvas = Image.new("RGB", (screen_w, screen_h), "black")
        x = (screen_w - image.width) // 2
        y = (screen_h - image.height) // 2
        canvas.paste(image, (x, y))
        return canvas

    def _do_fade(self, old: Image.Image, new: Image.Image, step: int, on_done) -> None:
        alpha = step / self.FADE_STEPS
        frame = Image.blend(old, new, alpha)
        self._tk_image = ImageTk.PhotoImage(frame)
        self.label.configure(image=self._tk_image)
        if step < self.FADE_STEPS:
            self.root.after(
                self.FADE_INTERVAL_MS,
                lambda: self._do_fade(old, new, step + 1, on_done),
            )
        else:
            on_done()

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
        def schedule_next() -> None:
            self.root.after(self.settings.refresh_seconds * 1000, self.refresh_once)

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
                    selected_movies=self.settings.selected_movies,
                )
                if self.settings.selected_movies:
                    status_text = f"No active sessions. Selected-movie poster: {title}"
                else:
                    status_text = f"No active movie sessions. Random poster: {title}"
                self._hide_top_banner()
                logger.info("random movie poster grabbed: %s", title)

            fitted = self._fit_to_screen(image)
            new_canvas = self._on_black_canvas(fitted)
            old_canvas = self._current_canvas or Image.new("RGB", new_canvas.size, "black")
            self._current_canvas = new_canvas
            self.status.configure(text=status_text)
            self.last_item_id = item_id
            self._do_fade(old_canvas, new_canvas, 1, schedule_next)
            return
        except Exception as exc:
            logger.exception("Poll failed: %s", exc)
            self.status.configure(text=f"Error: {exc}")

        schedule_next()

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
