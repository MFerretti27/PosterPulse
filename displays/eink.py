import logging
import signal
import time
from collections.abc import Callable

from PIL import Image, ImageDraw, ImageFont  # pyright: ignore[reportMissingImports]

from displays.base import BaseDisplay, PosterDisplayItem
from displays.waveshare import epd7in3e, epdconfig

logger = logging.getLogger(__name__)


class EInkDisplay(BaseDisplay):
    """Headless E-Paper display backend for Waveshare 7.3inch PhotoPainter (epd7in3e)."""

    def __init__(
        self,
        fetch_content_fn: Callable[[int, int, bool], PosterDisplayItem | None],
        width: int = 800,
        height: int = 480,
        rotation: int = 0,
        idle_refresh_minutes: int = 15,
        poll_interval_seconds: int = 15,
        preview_path: str | None = "eink_preview.png",
        pwr_pin: int = 27,
    ) -> None:
        self.fetch_content_fn = fetch_content_fn
        self.width = width
        self.height = height
        self.rotation = rotation
        self.idle_refresh_seconds = max(60, idle_refresh_minutes * 60)
        self.poll_interval_seconds = max(5, poll_interval_seconds)
        self.preview_path = preview_path
        self.pwr_pin = pwr_pin

        self.running = False
        self.last_displayed_id: str | None = None
        self.last_refresh_time: float = 0.0
        self.last_was_playing: bool = False
        self.connection_lost = False
        self.last_display_connection_lost = False
        self.last_good_item: PosterDisplayItem | None = None
        self.hardware_update_failed = False

        # Initialize hardware driver
        self.is_hardware_available = False
        self.epd: epd7in3e.EPD | None = None
        self._init_driver()

    def _init_driver(self) -> None:
        try:
            # Configure custom pins (PhotoPainter uses BCM 27 for PWR)
            epdconfig.implementation.pwr_pin = self.pwr_pin
            epdconfig.implementation.module_init()
            self.epd = epd7in3e.EPD(config=epdconfig.implementation)

            # Check if spi and gpio are real hardware (not mock)
            if (
                epdconfig.implementation.gpio_lib != "mock"
                and epdconfig.implementation.spi is not None
            ):
                self.is_hardware_available = True
                logger.info(
                    "Waveshare e-Paper hardware initialized successfully (PWR pin: BCM %d).",
                    self.pwr_pin,
                )
            else:
                logger.info(
                    "Running in preview/mock mode (hardware SPI/GPIO not available). "
                    "Rendered frames will be saved to '%s'.",
                    self.preview_path,
                )
        except (ImportError, OSError, RuntimeError, ValueError, AttributeError) as exc:
            logger.warning(
                "Failed to initialize e-Paper hardware (%s). Operating in preview mode.",
                exc,
            )
            self.is_hardware_available = False

    def _prepare_image(self, item: PosterDisplayItem) -> Image.Image:
        """Scale, center, rotate, and format the poster for 800x480 e-Paper."""
        # Create base canvas (black background looks great on e-ink)
        canvas = Image.new("RGB", (self.width, self.height), (0, 0, 0))

        img = item.image.copy()
        img_w, img_h = img.size

        # Align long axis: if canvas is landscape (800 > 480) and poster is portrait,
        # rotate poster 90 deg so it fills the screen, or fit in center.
        canvas_landscape = self.width >= self.height
        image_landscape = img_w >= img_h

        if canvas_landscape != image_landscape:
            img = img.rotate(90, expand=True)
            img_w, img_h = img.size

        # Scale to cover the full panel, then center-crop any overflow so no
        # black margins are left around the poster.
        scale = max(self.width / img_w, self.height / img_h)
        new_w = max(1, int(img_w * scale))
        new_h = max(1, int(img_h * scale))
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        paste_x = (self.width - new_w) // 2
        paste_y = (self.height - new_h) // 2
        canvas.paste(resized, (paste_x, paste_y))

        # Show a red vertical status banner for playback or lost connectivity.
        if item.is_playing or item.connection_lost:
            banner_width = 42
            # Build the label in landscape, then rotate it counter-clockwise
            # into a vertical strip on the display's short side.
            banner = Image.new("RGB", (self.height, banner_width), (180, 0, 0))
            draw = ImageDraw.Draw(banner)
            label_text = "CONNECTION LOST" if item.connection_lost else "NOW PLAYING"
            try:
                font = ImageFont.load_default(size=24)
            except TypeError:
                font = ImageFont.load_default()

            text_bounds = draw.textbbox((0, 0), label_text, font=font)
            text_width = text_bounds[2] - text_bounds[0]
            text_height = text_bounds[3] - text_bounds[1]
            text_x = (banner.width - text_width) // 2 - text_bounds[0]
            text_y = (banner.height - text_height) // 2 - text_bounds[1]
            draw.text((text_x, text_y), label_text, fill=(255, 255, 255), font=font)
            vertical_banner = banner.rotate(90, expand=True)
            canvas.paste(vertical_banner, (0, 0))

        # Apply user-specified rotation (e.g. 180 deg for reversed frames)
        if self.rotation != 0:
            canvas = canvas.rotate(self.rotation, expand=True)

        return canvas

    def _dither_and_quantize(self, image: Image.Image) -> Image.Image:
        """Quantize RGB image to 6-color palette with Floyd-Steinberg dithering."""
        pal_image = epd7in3e.EPD.create_palette_image()
        return image.convert("RGB").quantize(
            palette=pal_image, dither=Image.Dither.FLOYDSTEINBERG
        )

    def render_item(self, item: PosterDisplayItem) -> bool:
        """Render the poster item to the e-ink screen or preview image."""
        logger.info(
            "Rendering poster to e-Paper: '%s' (playing: %s)",
            item.title,
            item.is_playing,
        )
        prepared = self._prepare_image(item)

        # Save preview image if configured (always helpful for visual verification)
        if self.preview_path:
            try:
                # Convert quantized image back to RGB for easy preview viewing
                quantized = self._dither_and_quantize(prepared)
                preview_rgb = quantized.convert("RGB")
                preview_rgb.save(self.preview_path)
                logger.info("Saved e-Paper preview image to: %s", self.preview_path)
            except (OSError, ValueError) as exc:
                logger.warning("Could not save preview image: %s", exc)

        # Output to physical e-Paper display if hardware is present
        if self.is_hardware_available and self.epd is not None:
            try:
                logger.info("Waking e-Paper display and sending image...")
                self.epd.init()
                self.epd.display(prepared)
                logger.info("e-Paper refresh complete. Entering deep sleep.")
                self.epd.sleep()
            except (OSError, RuntimeError):
                logger.exception("Hardware e-Paper update failed")
                self.hardware_update_failed = True
                return False

            self.hardware_update_failed = False
        self.last_displayed_id = item.item_id
        self.last_refresh_time = time.time()
        self.last_was_playing = item.is_playing
        self.last_display_connection_lost = item.connection_lost
        if not item.connection_lost:
            self.last_good_item = item
        return True

    def run(self) -> None:
        """Run the e-ink polling loop."""
        self.running = True

        def _handle_exit(sig, frame):
            logger.info("Shutdown signal received. Exiting e-ink loop...")
            self.running = False

        signal.signal(signal.SIGINT, _handle_exit)
        signal.signal(signal.SIGTERM, _handle_exit)

        logger.info(
            "Starting e-Ink display worker (poll interval: %ds, idle refresh: %ds)",
            self.poll_interval_seconds,
            self.idle_refresh_seconds,
        )

        while self.running:
            try:
                now = time.time()
                allow_idle_poster = (
                    self.last_displayed_id is None
                    or self.last_was_playing
                    or now - self.last_refresh_time >= self.idle_refresh_seconds
                )
                item = self.fetch_content_fn(self.width, self.height, allow_idle_poster)
                was_connection_lost = self.connection_lost
                if was_connection_lost and item is None and self.last_good_item is None:
                    item = self.fetch_content_fn(self.width, self.height, True)
                self.connection_lost = bool(item and item.connection_lost)
                recovered = was_connection_lost and not self.connection_lost
                if item:
                    now = time.time()
                    should_refresh = (
                        recovered
                        or item.connection_lost != self.last_display_connection_lost
                    )

                    # Condition 1: First render
                    if self.last_displayed_id is None:
                        should_refresh = True
                        logger.info("Initial display update.")

                    # Condition 2: Playback state changed (movie started or stopped)
                    elif item.is_playing != self.last_was_playing:
                        should_refresh = True
                        logger.info(
                            "Playback state transition (was_playing=%s, is_playing=%s).",
                            self.last_was_playing,
                            item.is_playing,
                        )

                    # Condition 3: Different movie is playing now
                    elif item.is_playing and item.item_id != self.last_displayed_id:
                        should_refresh = True
                        logger.info("Active playing movie changed to '%s'.", item.title)
                    elif (
                        item.connection_lost and item.item_id != self.last_displayed_id
                    ):
                        should_refresh = True

                    # Condition 4: Idle timeout elapsed, rotate random poster
                    elif (
                        not item.is_playing
                        and (now - self.last_refresh_time) >= self.idle_refresh_seconds
                    ):
                        should_refresh = True
                        logger.info(
                            "Idle timer elapsed (%d seconds). Rotating poster.",
                            self.idle_refresh_seconds,
                        )

                    if should_refresh:
                        self.render_item(item)
                elif (
                    self.last_display_connection_lost
                    and self.last_good_item is not None
                ):
                    # Remove the connection warning while retaining the last poster.
                    self.render_item(self.last_good_item)
            except (OSError, RuntimeError, ValueError):
                logger.exception("Error in e-ink loop")
                if not self.connection_lost or self.hardware_update_failed:
                    self.connection_lost = True
                    previous = self.last_good_item
                    warning_item = PosterDisplayItem(
                        item_id=previous.item_id if previous else "connection-lost",
                        title=previous.title if previous else "Connection Lost",
                        image=(
                            previous.image.copy()
                            if previous
                            else Image.new("RGB", (self.width, self.height), "black")
                        ),
                        is_playing=previous.is_playing if previous else False,
                        user_name=previous.user_name if previous else None,
                        connection_lost=True,
                    )
                    self.render_item(warning_item)

            # Sleep in small increments for fast response to shutdown signals
            for _ in range(self.poll_interval_seconds):
                if not self.running:
                    break
                time.sleep(1)

        self.cleanup()

    def cleanup(self) -> None:
        """Clean up hardware on shutdown."""
        if self.is_hardware_available and self.epd is not None:
            try:
                self.epd.sleep()
            except (OSError, RuntimeError):
                logger.warning(
                    "Could not put e-Paper display into sleep", exc_info=True
                )
        epdconfig.implementation.module_exit(cleanup_power=True)
        logger.info("e-Ink display shutdown complete.")
