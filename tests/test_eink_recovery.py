import unittest
from unittest.mock import Mock, patch

from PIL import Image

from displays.base import PosterDisplayItem
from displays.eink import EInkDisplay
from displays.waveshare import epd7in3e


class BusyTimeoutTests(unittest.TestCase):
    def test_idle_panel_returns_without_waiting(self):
        config = Mock()
        config.digital_read.return_value = 1
        epd7in3e.EPD(config=config).read_busy_high()
        config.delay_ms.assert_not_called()

    def test_busy_panel_raises_instead_of_reporting_success(self):
        config = Mock()
        config.digital_read.return_value = 0
        with (
            patch(
                "displays.waveshare.epd7in3e.time.monotonic",
                side_effect=[100.0, 100.0, 130.0],
            ),
            self.assertRaisesRegex(TimeoutError, "BUSY pin"),
        ):
            epd7in3e.EPD(config=config).read_busy_high()
        config.delay_ms.assert_called_once_with(5)

    def test_refresh_stops_sending_commands_after_timeout(self):
        driver = epd7in3e.EPD(config=Mock())
        with (
            patch.object(driver, "send_command") as send_command,
            patch.object(driver, "read_busy_high", side_effect=TimeoutError),
            self.assertRaises(TimeoutError),
        ):
            driver.turn_on_display()
        send_command.assert_called_once_with(0x04)


class EInkRecoveryTests(unittest.TestCase):
    model = "7in3e"

    def make_display(self):
        with patch.object(EInkDisplay, "_init_driver"):
            display = EInkDisplay(
                fetch_content_fn=Mock(), model=self.model, preview_path=None
            )
        display.is_hardware_available = True
        display.epd = Mock(spec=display.epd_module.EPD(config=Mock()))
        display.epd.init.return_value = 0
        display.epd.config.gpio_lib = "gpiozero"
        return display

    def test_failed_refresh_keeps_state_and_powers_down_before_retry(self):
        display = self.make_display()
        display.last_displayed_id = "old"
        display.last_refresh_time = 123.0
        display.last_was_playing = True
        item = PosterDisplayItem(
            item_id="new",
            title="New Poster",
            image=Image.new("RGB", (800, 480)),
        )
        display.epd.display.side_effect = [TimeoutError("BUSY pin"), None]

        with self.assertLogs("displays.eink", level="ERROR"):
            self.assertFalse(display.render_item(item))

        self.assertTrue(display.hardware_update_failed)
        self.assertEqual(display.last_displayed_id, "old")
        self.assertEqual(display.last_refresh_time, 123.0)
        self.assertTrue(display.last_was_playing)
        display.epd.config.module_exit.assert_called_once_with()
        display.epd.sleep.assert_not_called()

        with patch(
            "displays.eink.time.monotonic", return_value=display._hardware_retry_at
        ):
            self.assertTrue(display.render_item(item))
        self.assertFalse(display.hardware_update_failed)
        self.assertEqual(display.last_displayed_id, "new")
        self.assertFalse(display.last_was_playing)
        display.epd.sleep.assert_called_once_with()

    def test_failed_init_does_not_send_image_or_update_state(self):
        display = self.make_display()
        display.epd.init.return_value = -1
        item = PosterDisplayItem(
            item_id="new",
            title="New Poster",
            image=Image.new("RGB", (800, 480)),
        )
        with self.assertLogs("displays.eink", level="ERROR"):
            self.assertFalse(display.render_item(item))
        display.epd.display.assert_not_called()
        display.epd.config.module_exit.assert_called_once_with()
        self.assertIsNone(display.last_displayed_id)

    def test_unavailable_hardware_does_not_report_success_on_retry(self):
        for gpio_lib, spi in (("mock", Mock()), (None, Mock()), ("gpiozero", None)):
            with self.subTest(gpio_lib=gpio_lib, spi=spi):
                display = self.make_display()
                display.hardware_update_failed = True
                display.epd.config.gpio_lib = gpio_lib
                display.epd.config.spi = spi
                item = PosterDisplayItem(
                    item_id="new",
                    title="New Poster",
                    image=Image.new("RGB", (400, 600)),
                )
                with self.assertLogs("displays.eink", level="ERROR"):
                    self.assertFalse(display.render_item(item))
                display.epd.display.assert_not_called()
                display.epd.config.module_exit.assert_called_once_with()
                self.assertTrue(display.hardware_update_failed)
                self.assertIsNone(display.last_displayed_id)
                self.assertGreater(display._hardware_retry_at, 0)

    def test_retry_delays_are_bounded_and_reset_after_success(self):
        display = self.make_display()
        item = PosterDisplayItem(
            item_id="new",
            title="New Poster",
            image=Image.new("RGB", (400, 600)),
        )
        display.epd.init.side_effect = TimeoutError("BUSY pin")
        now = 100.0
        for attempt, delay in enumerate((15, 60, 300, 300), start=1):
            with (
                patch("displays.eink.time.monotonic", return_value=now),
                self.assertLogs("displays.eink", level="ERROR") as logs,
            ):
                self.assertFalse(display.render_item(item))
            self.assertIn(f"retrying in {delay} seconds", logs.output[-1])
            self.assertIn(self.model, logs.output[-1])
            self.assertEqual(display._hardware_retry_at, now + delay)
            self.assertEqual(display.epd.init.call_count, attempt)
            self.assertEqual(display.epd.config.module_exit.call_count, attempt)
            with patch("displays.eink.time.monotonic", return_value=now + delay - 0.01):
                self.assertFalse(display.render_item(item))
            self.assertEqual(display.epd.init.call_count, attempt)
            self.assertIsNone(display.last_displayed_id)
            now += delay

        display.epd.init.side_effect = None
        with patch("displays.eink.time.monotonic", return_value=now):
            self.assertTrue(display.render_item(item))
        self.assertEqual(display._hardware_failure_count, 0)
        self.assertEqual(display._hardware_retry_at, 0.0)
        self.assertFalse(display.hardware_update_failed)
        display.epd.init.side_effect = TimeoutError("BUSY pin")
        with (
            patch("displays.eink.time.monotonic", return_value=now),
            self.assertLogs("displays.eink", level="ERROR"),
        ):
            self.assertFalse(display.render_item(item))
        self.assertEqual(display._hardware_retry_at, now + 15)

    def test_loop_keeps_polling_and_retries_failed_idle_refresh(self):
        display = self.make_display()
        display.poll_interval_seconds = 5
        display.last_displayed_id = "old"
        display.last_refresh_time = 100.0
        item = PosterDisplayItem(
            item_id="new",
            title="New Poster",
            image=Image.new("RGB", (400, 600)),
        )
        display.epd.init.side_effect = [TimeoutError("BUSY pin"), 0]
        clock = [2000.0]
        polls = []

        def fetch(width, height, allow_idle):
            polls.append(allow_idle)
            if len(polls) == 5:
                display.running = False
            return item if allow_idle else None

        def sleep(seconds):
            clock[0] += seconds

        display.fetch_content_fn = fetch
        with (
            patch("displays.eink.signal.signal"),
            patch("displays.eink.time.time", side_effect=lambda: clock[0]),
            patch("displays.eink.time.monotonic", side_effect=lambda: clock[0]),
            patch("displays.eink.time.sleep", side_effect=sleep),
            patch.object(display, "cleanup"),
            self.assertLogs("displays.eink", level="ERROR"),
        ):
            display.run()
        self.assertEqual(polls, [True, True, True, True, False])
        self.assertEqual(display.epd.init.call_count, 2)
        self.assertEqual(display.last_displayed_id, "new")
        self.assertFalse(display.hardware_update_failed)


class E6RecoveryTests(EInkRecoveryTests):
    model = "4in0e"


if __name__ == "__main__":
    unittest.main()
