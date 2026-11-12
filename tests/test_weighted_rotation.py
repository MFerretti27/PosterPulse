import unittest
from unittest.mock import Mock, patch

from main import JellyfinClient, Settings


class WeightedRotationTests(unittest.TestCase):
    def setUp(self):
        self.client = JellyfinClient(
            Settings(jellyfin_url="http://jellyfin", api_token="test", poster_tags=[])
        )
        self.items = [
            {"Id": "a", "Name": "A", "CommunityRating": 10},
            {"Id": "b", "Name": "B", "CommunityRating": 9},
            {"Id": "c", "Name": "C", "CommunityRating": 8},
            {"Id": "d", "Name": "D", "CommunityRating": 7},
        ]
        self.client.resolve_user_id = Mock(return_value="user")
        self.client._get_all_items = Mock(return_value=self.items)
        self.client.get_item_poster_image = Mock(return_value="image")

    def test_recent_items_have_lower_weights_and_last_is_excluded(self):
        self.client._record_idle_poster("a")
        self.client._record_idle_poster("b")
        self.client._record_idle_poster("c")

        with patch("main.random.choices", return_value=[self.items[0]]) as choose:
            self.client.get_random_poster_image(100, 100)

        candidates = choose.call_args.args[0]
        weights = choose.call_args.kwargs["weights"]
        self.assertEqual([item["Id"] for item in candidates], ["a", "b", "d"])
        self.assertGreater(weights[0], weights[1])
        self.assertGreater(weights[2], weights[0])
        self.assertTrue(all(weight > 0 for weight in weights))

    def test_single_candidate_remains_available(self):
        self.client._get_all_items.return_value = [self.items[0]]
        self.client._record_idle_poster("a")

        self.assertEqual(self.client.get_random_poster_image(100, 100)[0], "a")

    def test_failed_image_fetch_does_not_update_history(self):
        self.client.get_item_poster_image.side_effect = OSError("image failed")
        with self.assertRaisesRegex(OSError, "image failed"):
            self.client.get_random_poster_image(100, 100)

        self.assertEqual(self.client._idle_selection_count, 0)
        self.assertEqual(self.client._idle_last_selected, {})

    def test_top_rated_mode_shares_history_and_respects_candidate_limit(self):
        self.client._record_idle_poster("a")
        self.client._record_idle_poster("b")
        self.client.top_rated_movie_count = 3
        self.client._get = Mock(return_value=Mock(json=lambda: {"Items": self.items}))
        with patch("main.random.choices", return_value=[self.items[2]]) as choose:
            result = self.client.get_random_poster_image(100, 100)

        self.assertEqual(result[0], "c")
        self.assertEqual([item["Id"] for item in choose.call_args.args[0]], ["a", "c"])
        self.assertGreater(
            choose.call_args.kwargs["weights"][1],
            choose.call_args.kwargs["weights"][0],
        )
        self.assertEqual(self.client._idle_last_selected["c"], 3)

    def test_last_playback_poster_is_excluded_even_if_not_last_idle_poster(self):
        self.client._record_idle_poster("a")
        with patch("main.random.choices", return_value=[self.items[0]]) as choose:
            self.client.get_random_poster_image(100, 100, last_item_id="b")

        self.assertNotIn("b", [item["Id"] for item in choose.call_args.args[0]])


if __name__ == "__main__":
    unittest.main()
