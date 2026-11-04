import logging
from typing import Callable, Optional
from PIL import Image, ImageTk
import tkinter as tk

from displays.base import BaseDisplay, PosterDisplayItem

logger = logging.getLogger(__name__)


class RegularDisplay(BaseDisplay):
    """Tkinter-based fullscreen/windowed GUI for regular monitors/TVs (HDMI)."""

    def __init__(
        self,
        fetch_content_fn: Callable[[int, int], Optional[PosterDisplayItem]],
        refresh_seconds: int = 30,
        background_color: str = "black",
        fullscreen: bool = True,
        fade_speed: int = 5,
    ) -> None:
        self.fetch_content_fn = fetch_content_fn
        self.refresh_seconds = refresh_seconds
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

        self.root = tk.Tk()
        self.root.configure(bg=self.background_color)
        self.root.bind("<Escape>", lambda _event: self.exit_app())

        if self.fullscreen:
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

        self.label = tk.Label(self.root, bg=self.background_color)
        self.label.pack(fill=tk.BOTH, expand=True)

        self.status = tk.Label(
            self.root,
            text="Loading...",
            anchor="w",
            bg=self.background_color,
            fg="white",
            padx=10,
            pady=8,
        )
        self.status.pack(fill=tk.X)

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
            self.root.after(self.refresh_seconds * 1000, self.refresh_once)

        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            item = self.fetch_content_fn(screen_w, screen_h)

            if item is None:
                schedule_next()
                return

            if item.is_playing:
                status_text = f"Watching now: {item.user_name or 'User'} - {item.title}"
                self._show_top_banner()
            else:
                status_text = f"Poster: {item.title}"
                self._hide_top_banner()

            fitted = self._fit_to_screen(item.image)
            new_canvas = self._on_black_canvas(fitted)
            old_canvas = self._current_canvas or Image.new(
                "RGB", new_canvas.size, self.background_color
            )
            self._current_canvas = new_canvas
            self.status.configure(text=status_text)
            self._do_fade(old_canvas, new_canvas, 1, schedule_next)
            return
        except Exception as exc:
            logger.exception("Poll failed: %s", exc)
            self.status.configure(text=f"Error: {exc}")

        schedule_next()

    def exit_app(self) -> None:
        self.root.destroy()

    def run(self) -> None:
        self.refresh_once()
        self.root.mainloop()

    def cleanup(self) -> None:
        pass
