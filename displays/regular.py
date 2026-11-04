import logging
import time
from typing import Callable, Optional
from PIL import Image, ImageDraw, ImageFont, ImageTk # pyright: ignore[reportMissingImports]
import tkinter as tk

from displays.base import BaseDisplay, PosterDisplayItem

logger = logging.getLogger(__name__)


class RegularDisplay(BaseDisplay):
    """Tkinter-based fullscreen/windowed GUI for regular monitors/TVs (HDMI)."""

    def __init__(
        self,
        fetch_content_fn: Callable[[int, int, bool], Optional[PosterDisplayItem]],
        refresh_seconds: int = 30,
        idle_refresh_minutes: int = 30,
        background_color: str = "black",
        fullscreen: bool = True,
        fade_speed: int = 5,
    ) -> None:
        self.fetch_content_fn = fetch_content_fn
        self.refresh_seconds = refresh_seconds
        self.idle_refresh_seconds = max(60, idle_refresh_minutes * 60)
        self.background_color = background_color
        self.fullscreen = fullscreen
        self.fade_speed = max(1, min(10, fade_speed))

        # Fade speed tuning:
        # Steps: 30 at speed 1, down to 4 at speed 10
        self.fade_steps = max(4, 32 - self.fade_speed * 3)
        # Interval: 200 ms at speed 1, 15 ms at speed 10
        self.fade_interval_ms = max(15, 215 - self.fade_speed * 20)

        self._current_canvas: Optional[Image.Image] = None
        self._tk_image: Optional[ImageTk.PhotoImage] = None
        self._last_displayed_id: Optional[str] = None
        self._last_was_playing = False
        self._last_refresh_time = 0.0
        self._pending_advances = 0
        self._fade_in_progress = False
        self._refresh_after_id: Optional[str] = None
        self._connection_lost = False

        self.root = tk.Tk()
        self.root.configure(bg=self.background_color)
        self.root.bind("<Escape>", lambda _event: self.exit_app())
        self.root.bind("<Button-1>", self._on_screen_tap)

        if self.fullscreen:
            self.root.attributes("-fullscreen", True)

        self._top_banner_width = 64
        self._top_banner_image = self._make_banner_image("Currently Playing")
        self.top_banner = tk.Label(
            self.root, image=self._top_banner_image, bg="#8B0000", borderwidth=0
        )
        self.banner_visible = False

        self.label = tk.Label(self.root, bg=self.background_color)
        self.label.place(x=0, y=0, relwidth=1.0, relheight=1.0)

        self.status = tk.Label(
            self.root,
            text="Loading...",
            anchor="w",
            bg=self.background_color,
            fg="white",
            padx=10,
            pady=8,
        )
        self.status.place_forget()

    def _on_black_canvas(self, image: Image.Image) -> Image.Image:
        """Paste image centered on full-screen canvas."""
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        canvas = Image.new("RGB", (screen_w, screen_h), self.background_color)
        x = (screen_w - image.width) // 2
        y = (screen_h - image.height) // 2
        canvas.paste(image, (x, y))
        return canvas

    def _do_fade(
        self, old: Image.Image, new: Image.Image, step: int, on_done: Callable[[], None]
    ) -> None:
        alpha = step / self.fade_steps
        frame = Image.blend(old, new, alpha)
        self._tk_image = ImageTk.PhotoImage(frame)
        self.label.configure(image=self._tk_image)
        if step < self.fade_steps:
            self.root.after(
                self.fade_interval_ms,
                lambda: self._do_fade(old, new, step + 1, on_done),
            )
        else:
            on_done()

    def _fit_to_screen(self, image: Image.Image) -> Image.Image:
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        # Keep poster long axis aligned with screen's long axis
        screen_long_horizontal = screen_w >= screen_h
        img_w, img_h = image.size
        image_long_horizontal = img_w >= img_h
        if image_long_horizontal != screen_long_horizontal:
            image = image.rotate(90, expand=True)
            img_w, img_h = image.size

        # Scale to cover the full display, then center-crop without distorting.
        scale = max(screen_w / img_w, screen_h / img_h)
        new_size = (max(1, int(img_w * scale)), max(1, int(img_h * scale)))
        resized = image.resize(new_size, Image.Resampling.LANCZOS)
        left = (resized.width - screen_w) // 2
        top = (resized.height - screen_h) // 2
        return resized.crop((left, top, left + screen_w, top + screen_h))

    def _show_top_banner(self) -> None:
        if not self.banner_visible:
            self.top_banner.place(
                x=0, y=0, width=self._top_banner_width, relheight=1.0
            )
            self.top_banner.lift()
            self.banner_visible = True

    def _make_banner_image(self, text: str) -> ImageTk.PhotoImage:
        """Create a full-height red vertical banner with centered text."""
        screen_height = self.root.winfo_screenheight()
        font = ImageFont.load_default(size=26)
        draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        bounds = draw.textbbox((0, 0), text, font=font)
        banner = Image.new("RGB", (screen_height, self._top_banner_width), "#8B0000")
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        ImageDraw.Draw(banner).text(
            (
                (screen_height - text_width) // 2 - bounds[0],
                (self._top_banner_width - text_height) // 2 - bounds[1],
            ),
            text,
            fill="white",
            font=font,
        )
        return ImageTk.PhotoImage(banner.rotate(90, expand=True))

    def _set_banner_text(self, text: str) -> None:
        self._top_banner_image = self._make_banner_image(text)
        self.top_banner.configure(image=self._top_banner_image)

    def _hide_top_banner(self) -> None:
        if self.banner_visible:
            self.top_banner.place_forget()
            self.banner_visible = False

    def refresh_once(self) -> None:
        self._refresh_after_id = None

        def schedule_next() -> None:
            self._fade_in_progress = False
            if self._pending_advances:
                self.refresh_once()
            else:
                self._refresh_after_id = self.root.after(
                    self.refresh_seconds * 1000, self.refresh_once
                )

        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            now = time.monotonic()
            manual_advance = self._pending_advances > 0
            if manual_advance:
                self._pending_advances -= 1
            allow_idle_poster = (
                manual_advance
                or self._connection_lost
                or self._last_displayed_id is None
                or self._last_was_playing
                or now - self._last_refresh_time >= self.idle_refresh_seconds
            )
            item = self.fetch_content_fn(screen_w, screen_h, allow_idle_poster)
            recovered = self._connection_lost
            self._connection_lost = False

            if item is None:
                if recovered:
                    self._hide_top_banner()
                schedule_next()
                return

            should_render = (
                manual_advance or recovered or self._last_displayed_id is None
            )
            if item.is_playing != self._last_was_playing:
                should_render = True
            elif item.is_playing and item.item_id != self._last_displayed_id:
                should_render = True
            elif (
                not item.is_playing
                and now - self._last_refresh_time >= self.idle_refresh_seconds
            ):
                should_render = True

            if not should_render:
                schedule_next()
                return

            if item.is_playing:
                self._set_banner_text("Currently Playing")
                self._show_top_banner()
                self.status.place_forget()
            else:
                self._hide_top_banner()
                self.status.place_forget()

            fitted = self._fit_to_screen(item.image)
            new_canvas = self._on_black_canvas(fitted)
            old_canvas = self._current_canvas or Image.new(
                "RGB", new_canvas.size, self.background_color
            )
            self._current_canvas = new_canvas
            self._last_displayed_id = item.item_id
            self._last_was_playing = item.is_playing
            self._last_refresh_time = now
            self._fade_in_progress = True
            self._do_fade(old_canvas, new_canvas, 1, schedule_next)
            return
        except Exception as exc:
            logger.exception("Poll failed: %s", exc)
            self._connection_lost = True
            self._set_banner_text("Connection Lost")
            self._show_top_banner()
            self.status.place_forget()

        schedule_next()

    def _on_screen_tap(self, _event: object) -> None:
        """Advance to another poster when the screen is clicked or tapped."""
        self._pending_advances += 1
        if not self._fade_in_progress:
            if self._refresh_after_id is not None:
                self.root.after_cancel(self._refresh_after_id)
                self._refresh_after_id = None
            self.refresh_once()

    def exit_app(self) -> None:
        self.root.destroy()

    def run(self) -> None:
        self.refresh_once()
        self.root.mainloop()

    def cleanup(self) -> None:
        pass
