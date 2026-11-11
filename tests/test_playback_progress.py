import os
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from displays.base import PosterDisplayItem
from displays.regular import RegularDisplay
from main import JellyfinClient, PosterCoordinator, Settings


class ProgressSettingsTests(unittest.TestCase):
    def load_settings(self, **overrides):
        with patch("main.load_dotenv"), patch.dict(
            os.environ,
            {
                "JELLYFIN_URL": "http://jellyfin",
                "JELLYFIN_API_TOKEN": "test-token",
                **overrides,
            },
            clear=True,
        ):
            return Settings.from_env()

    def test_defaults_off_and_white(self):
        settings = self.load_settings()
        self.assertFalse(settings.progress_bar_enabled)
        self.assertEqual(settings.progress_bar_color, "white")

    def test_enable_and_choose_color(self):
        settings = self.load_settings(
            PROGRESS_BAR_ENABLED="YES", PROGRESS_BAR_COLOR="#00FF00"
        )
        self.assertTrue(settings.progress_bar_enabled)
        self.assertEqual(settings.progress_bar_color, "#00FF00")

    def test_invalid_enabled_color_reports_configuration_error(self):
        with self.assertRaisesRegex(ValueError, "PROGRESS_BAR_COLOR"):
            self.load_settings(PROGRESS_BAR_ENABLED="true", PROGRESS_BAR_COLOR="invalid")

    def test_eink_ignores_color(self):
        settings = self.load_settings(
            DISPLAY_TYPE="eink", PROGRESS_BAR_ENABLED="true", PROGRESS_BAR_COLOR="invalid"
        )
        self.assertEqual(settings.display_type, "eink")


class PlaybackProgressTests(unittest.TestCase):
    def make_session(self, media_type="Movie", position=25, duration=100):
        return {
            "Id": "session",
            "UserName": "Viewer",
            "NowPlayingItem": {
                "Id": "movie", "Type": media_type, "Name": "Title",
                "SeriesId": "series", "RunTimeTicks": duration,
            },
            "PlayState": {"PositionTicks": position, "IsPaused": True},
        }

    def test_progress_uses_movie_or_episode_duration_even_when_paused(self):
        settings = Settings(
            jellyfin_url="http://jellyfin", api_token="test-token",
            poster_tags=[], media_types=["Movie", "Series"],
        )
        client = JellyfinClient(settings)
        for media_type, poster_id in (("Movie", "movie"), ("Episode", "series")):
            with self.subTest(media_type=media_type):
                client._get = Mock()
                client._get.return_value.json.return_value = [self.make_session(media_type)]
                active = client.get_active_media_sessions()
                self.assertEqual(active[0]["item_id"], poster_id)
                self.assertEqual(active[0]["playback_progress"], 0.25)
                coordinator = PosterCoordinator(client, settings)
                coordinator.poster_cache = Mock()
                client.get_item_poster_image = Mock(return_value=Image.new("RGB", (10, 10)))
                item = coordinator.fetch_item(10, 10)
                self.assertEqual(item.playback_progress, 0.25)

    def test_missing_duration_or_position_hides_progress(self):
        for position, duration in ((None, 100), (25, None)):
            self.assertIsNone(
                JellyfinClient._playback_progress(
                    self.make_session(position=position, duration=duration)
                )
            )

    def test_invalid_ticks_are_logged_and_hidden(self):
        for position, duration in ((25, 0), (25, -1), ("25", 100)):
            with self.assertLogs("main", level="WARNING"):
                self.assertIsNone(
                    JellyfinClient._playback_progress(
                        self.make_session(position=position, duration=duration)
                    )
                )

    def test_seeks_and_out_of_range_positions(self):
        for position, expected in ((-1, 0), (0, 0), (75, 0.75), (200, 1)):
            self.assertEqual(
                JellyfinClient._playback_progress(self.make_session(position=position)),
                expected,
            )


class RegularProgressBarTests(unittest.TestCase):
    def make_display(self, **overrides):
        with patch("displays.regular.tk.Tk"), patch(
            "displays.regular.tk.Label"
        ), patch("displays.regular.tk.Frame", side_effect=lambda *args, **kwargs: Mock()), patch.object(
            RegularDisplay, "_make_banner_image"
        ):
            display = RegularDisplay(Mock(), **overrides)
        display._make_banner_image = Mock()
        return display

    def make_item(self, **overrides):
        return PosterDisplayItem(
            item_id="movie", title="Title", image=Image.new("RGB", (10, 10)),
            **overrides,
        )

    def test_disabled_idle_offline_and_missing_progress_are_hidden(self):
        item = self.make_item(is_playing=True, playback_progress=0.5)
        display = self.make_display()
        display._update_progress_bar(item)
        display.progress_bar.place_forget.assert_called_once()
        display = self.make_display(progress_bar_enabled=True)
        for item in (
            None, self.make_item(), self.make_item(is_playing=True),
            self.make_item(is_playing=True, connection_lost=True, playback_progress=0.5),
        ):
            display.progress_bar.reset_mock()
            display._update_progress_bar(item)
            display.progress_bar.place_forget.assert_called_once()
            display.progress_bar.place.assert_not_called()

    def test_placement_and_fill_follow_rotation(self):
        for rotation in (0, 180):
            display = self.make_display(progress_bar_enabled=True, rotation=rotation)
            display._update_progress_bar(
                self.make_item(is_playing=True, playback_progress=0.25)
            )
            self.assertEqual(display.progress_bar.place.call_args.kwargs["height"], 8)
            self.assertEqual(
                display.progress_bar.place.call_args.kwargs["rely"],
                1.0 if rotation == 0 else 0.0,
            )
            self.assertEqual(display.progress_fill.place.call_args.kwargs["relwidth"], 0.25)
            self.assertEqual(
                display.progress_fill.place.call_args.kwargs["anchor"],
                "nw" if rotation == 0 else "ne",
            )

    def test_progress_updates_without_refading_same_poster(self):
        display = self.make_display(progress_bar_enabled=True)
        display._last_displayed_id = "movie"
        display._last_was_playing = True
        display._last_refresh_time = float("inf")
        display.fetch_content_fn.return_value = self.make_item(
            is_playing=True, playback_progress=0.75
        )
        display._do_fade = Mock()
        display.refresh_once()
        self.assertEqual(display.progress_fill.place.call_args.kwargs["relwidth"], 0.75)
        display._do_fade.assert_not_called()

    def test_poll_failure_hides_progress(self):
        display = self.make_display(progress_bar_enabled=True)
        display.fetch_content_fn.side_effect = RuntimeError("failed")
        with self.assertLogs("displays.regular", level="ERROR"):
            display.refresh_once()
        display.progress_bar.place_forget.assert_called_once()

    def test_zero_progress_has_no_fill(self):
        display = self.make_display(progress_bar_enabled=True)
        display._update_progress_bar(self.make_item(is_playing=True, playback_progress=0))
        display.progress_fill.place_forget.assert_called_once()


if __name__ == "__main__":
    unittest.main()
