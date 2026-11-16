import subprocess
import unittest
from unittest.mock import Mock, patch

import requests
from PIL import Image

from displays.base import PosterDisplayItem
from displays.eink import EInkDisplay
from displays.regular import RegularDisplay
from main import NetworkMonitor, PosterCoordinator, Settings


class NetworkCheckTests(unittest.TestCase):
    def setUp(self):
        self.monitor = NetworkMonitor()
        self.monitor.disabled = False

    @patch("main.subprocess.run")
    def test_wifi_and_ethernet_states(self, run):
        for output, disconnected in (
            ("wifi:disconnected\nethernet:unavailable\n", True),
            ("wifi:unavailable\n", True),
            ("wifi:connected\nethernet:unavailable\n", False),
            ("wifi:disconnected\nethernet:connected\n", False),
            ("wifi:connected (externally)\n", False),
        ):
            with self.subTest(output=output):
                run.return_value.stdout = output
                self.assertEqual(self.monitor.disconnected(), disconnected)
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertEqual(run.call_args.kwargs["env"]["LC_ALL"], "C")

    @patch("main.subprocess.run")
    def test_unknown_status_preserves_last_state(self, run):
        self.monitor.last_disconnected = True
        run.return_value.stdout = "wifi:unmanaged\n"
        with self.assertLogs("main", level="WARNING"):
            self.assertTrue(self.monitor.disconnected())
        run.side_effect = subprocess.TimeoutExpired("nmcli", 3)
        with self.assertLogs("main", level="WARNING"):
            self.assertTrue(self.monitor.disconnected())

    @patch("main.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_nmcli_disables_check_without_false_warning(self, run):
        with self.assertLogs("main", level="WARNING"):
            self.assertFalse(self.monitor.disconnected())
        self.assertFalse(self.monitor.disconnected())
        run.assert_called_once()


class CoordinatorNetworkTests(unittest.TestCase):
    def setUp(self):
        self.check = Mock(return_value=False)
        self.coordinator = PosterCoordinator(
            Mock(), Settings(jellyfin_url="http://local", api_token="token"), self.check
        )
        self.coordinator.poster_cache = Mock()
        self.coordinator.poster_cache.get_fallback.return_value = None
        self.item = PosterDisplayItem(
            item_id="movie", title="Movie", image=Image.new("RGB", (10, 10))
        )

    def test_network_outage_with_local_jellyfin_and_recovery(self):
        self.coordinator._fetch_online_item = Mock(side_effect=[self.item, None, None])
        self.assertFalse(self.coordinator.fetch_item(10, 10).network_disconnected)
        self.check.return_value = True
        warning = self.coordinator.fetch_item(10, 10, False)
        self.assertTrue(warning.network_disconnected)
        self.assertFalse(warning.connection_lost)
        self.assertEqual(warning.item_id, "movie")
        self.check.return_value = False
        self.assertIsNone(self.coordinator.fetch_item(10, 10, False))

    def test_both_connections_lost_at_startup_without_cache(self):
        self.check.return_value = True
        self.coordinator._fetch_online_item = Mock(
            side_effect=requests.ConnectionError("offline")
        )
        with self.assertLogs("main", level="WARNING"):
            warning = self.coordinator.fetch_item(10, 10)
        self.assertTrue(warning.connection_lost)
        self.assertTrue(warning.network_disconnected)
        self.assertEqual(warning.image.size, (10, 10))

    def test_cached_poster_reports_both_outages(self):
        self.check.return_value = True
        self.coordinator._fetch_online_item = Mock(
            side_effect=requests.ConnectionError("offline")
        )
        self.coordinator.poster_cache.get_fallback.return_value = PosterDisplayItem(
            item_id="cached",
            title="Cached",
            image=Image.new("RGB", (10, 10)),
            connection_lost=True,
        )
        with self.assertLogs("main", level="WARNING"):
            warning = self.coordinator.fetch_item(10, 10)
        self.assertTrue(warning.connection_lost)
        self.assertTrue(warning.network_disconnected)
        self.assertEqual(warning.item_id, "cached")

    def test_jellyfin_error_still_propagates_without_cache_when_network_works(self):
        self.coordinator._fetch_online_item = Mock(
            side_effect=requests.ConnectionError("offline")
        )
        with (
            self.assertLogs("main", level="WARNING"),
            self.assertRaises(requests.ConnectionError),
        ):
            self.coordinator.fetch_item(10, 10)

    def test_placeholder_is_replaced_as_soon_as_jellyfin_recovers(self):
        self.check.side_effect = [True, False, False]
        self.coordinator.client.get_active_media_sessions.side_effect = [
            requests.ConnectionError("offline"),
            requests.ConnectionError("server unavailable"),
            [],
        ]
        self.coordinator.client.get_random_poster_image.return_value = (
            "movie",
            "Movie",
            self.item.image,
        )
        with self.assertLogs("main", level="WARNING"):
            first = self.coordinator.fetch_item(10, 10)
            second = self.coordinator.fetch_item(10, 10, False)
        self.assertTrue(first.is_placeholder)
        self.assertTrue(first.network_disconnected)
        self.assertTrue(second.is_placeholder)
        self.assertTrue(second.connection_lost)
        self.assertFalse(second.network_disconnected)
        recovered = self.coordinator.fetch_item(10, 10, False)
        self.assertEqual(recovered.item_id, "movie")
        self.assertFalse(recovered.is_placeholder)
        self.assertFalse(recovered.connection_lost)
        self.coordinator.client.get_random_poster_image.assert_called_once()

    def test_connected_server_recovers_even_when_network_remains_disconnected(self):
        self.check.return_value = True
        self.coordinator.client.get_active_media_sessions.side_effect = [
            requests.ConnectionError("offline"),
            [],
        ]
        self.coordinator.client.get_random_poster_image.return_value = (
            "movie",
            "Movie",
            self.item.image,
        )
        with self.assertLogs("main", level="WARNING"):
            self.coordinator.fetch_item(10, 10)
        recovered = self.coordinator.fetch_item(10, 10, False)
        self.assertTrue(recovered.network_disconnected)
        self.assertFalse(recovered.is_placeholder)
        self.assertEqual(recovered.item_id, "movie")


class DisplayNetworkTests(unittest.TestCase):
    def test_regular_shows_and_clears_network_banner_with_same_poster(self):
        with (
            patch("displays.regular.tk.Tk"),
            patch("displays.regular.tk.Label"),
            patch("displays.regular.tk.Frame"),
            patch.object(RegularDisplay, "_make_banner_image"),
        ):
            display = RegularDisplay(Mock())
        display.root.winfo_screenwidth.return_value = 10
        display.root.winfo_screenheight.return_value = 10
        display._set_banner_text = Mock()
        display._do_fade = Mock()
        display._last_displayed_id = "movie"
        display._last_refresh_time = float("inf")
        display.fetch_content_fn.side_effect = [
            PosterDisplayItem(
                item_id="movie",
                title="Movie",
                image=Image.new("RGB", (10, 10)),
                network_disconnected=True,
            ),
            None,
        ]
        display.refresh_once()
        display._set_banner_text.assert_called_with("Network Disconnected")
        self.assertTrue(display.banner_visible)
        display.refresh_once()
        self.assertFalse(display.banner_visible)

    def test_eink_renders_and_clears_network_warning_without_new_poster(self):
        item = PosterDisplayItem(
            item_id="movie",
            title="Movie",
            image=Image.new("RGB", (10, 10)),
            network_disconnected=True,
        )
        with patch.object(EInkDisplay, "_init_driver"):
            display = EInkDisplay(Mock(), width=100, height=100, preview_path=None)
        display.poll_interval_seconds = 0
        display.fetch_content_fn.side_effect = [item, None]
        rendered = []
        original_render = display.render_item

        def render(rendered_item):
            rendered.append(rendered_item)
            if len(rendered) == 2:
                display.running = False
            return original_render(rendered_item)

        with (
            patch("displays.eink.signal.signal"),
            patch.object(display, "render_item", side_effect=render),
        ):
            display.run()
        self.assertTrue(rendered[0].network_disconnected)
        self.assertFalse(rendered[1].network_disconnected)
        self.assertEqual(rendered[1].item_id, "movie")

    def test_offline_startup_recovery_updates_both_displays(self):
        for kind in ("regular", "eink"):
            with self.subTest(kind=kind):
                client = Mock()
                client.get_active_media_sessions.side_effect = [
                    requests.ConnectionError("offline"),
                    requests.ConnectionError("server unavailable"),
                    [],
                ]
                client.get_random_poster_image.return_value = (
                    "movie",
                    "Movie",
                    Image.new("RGB", (10, 10)),
                )
                coordinator = PosterCoordinator(
                    client,
                    Settings(jellyfin_url="http://local", api_token="token"),
                    Mock(side_effect=[True, False, False]),
                )
                coordinator.poster_cache = Mock()
                coordinator.poster_cache.get_fallback.return_value = None
                if kind == "regular":
                    with (
                        patch("displays.regular.tk.Tk"),
                        patch("displays.regular.tk.Label"),
                        patch("displays.regular.tk.Frame"),
                        patch.object(RegularDisplay, "_make_banner_image"),
                    ):
                        display = RegularDisplay(coordinator.fetch_item)
                    display.root.winfo_screenwidth.return_value = 10
                    display.root.winfo_screenheight.return_value = 10
                    display._set_banner_text = Mock()
                    display._do_fade = Mock()
                    with self.assertLogs("main", level="WARNING"):
                        display.refresh_once()
                        display.refresh_once()
                    self.assertEqual(
                        [
                            call.args[0]
                            for call in display._set_banner_text.call_args_list
                        ],
                        ["Network Disconnected", "Connection Lost"],
                    )
                    display.refresh_once()
                    self.assertEqual(display._last_displayed_id, "movie")
                    self.assertFalse(display.banner_visible)
                else:
                    with patch.object(EInkDisplay, "_init_driver"):
                        display = EInkDisplay(
                            coordinator.fetch_item,
                            width=100,
                            height=100,
                            preview_path=None,
                        )
                    display.poll_interval_seconds = 0
                    rendered = []
                    original_render = display.render_item

                    def render(item):
                        rendered.append(item)
                        if len(rendered) == 3:
                            display.running = False
                        return original_render(item)

                    with (
                        patch("displays.eink.signal.signal"),
                        patch.object(display, "render_item", side_effect=render),
                        self.assertLogs("main", level="WARNING"),
                    ):
                        display.run()
                    self.assertEqual(len(rendered), 3)
                    self.assertTrue(rendered[0].network_disconnected)
                    self.assertFalse(rendered[1].network_disconnected)
                    self.assertTrue(rendered[1].connection_lost)
                    self.assertEqual(rendered[2].item_id, "movie")
                    self.assertFalse(rendered[2].is_placeholder)


if __name__ == "__main__":
    unittest.main()
