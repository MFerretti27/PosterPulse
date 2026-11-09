import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from main import JellyfinClient, Settings


class PosterTagFilterTests(unittest.TestCase):
    def make_client(self, **settings_overrides):
        settings = Settings(
            jellyfin_url="http://jellyfin",
            api_token="test-token",
            **settings_overrides,
        )
        return JellyfinClient(settings)

    def test_matches_both_tag_spellings_case_insensitively(self):
        client = self.make_client()

        self.assertTrue(client._matches_poster_tags({"Tags": ["posterpulse"]}))
        self.assertTrue(client._matches_poster_tags({"Tags": ["POSTER PULSE"]}))
        self.assertFalse(client._matches_poster_tags({"Tags": ["Poster Pulse!"]}))

    def test_random_poster_selection_excludes_unmatched_tags(self):
        client = self.make_client()
        client.resolve_user_id = Mock(return_value="user-id")
        client._get_all_items = Mock(
            return_value=[
                {"Id": "unmatched", "Name": "Unmatched", "Tags": ["Action"]},
                {"Id": "matched", "Name": "Matched", "Tags": ["posterpulse"]},
            ]
        )
        client.get_item_poster_image = Mock(return_value="poster-image")

        result = client.get_random_poster_image(100, 100)

        self.assertEqual(result, ("matched", "Matched", "poster-image"))

    def test_top_rated_selection_ranks_only_tagged_movies(self):
        client = self.make_client(top_rated_movie_count=2)
        client.resolve_user_id = Mock(return_value="user-id")
        client._get_all_items = Mock(
            return_value=[
                {
                    "Id": "untagged",
                    "Name": "Untagged",
                    "CommunityRating": 10,
                    "Tags": ["Action"],
                },
                {
                    "Id": "tagged-high",
                    "Name": "Tagged High",
                    "CommunityRating": 9,
                    "Tags": ["Poster Pulse"],
                },
                {
                    "Id": "tagged-next",
                    "Name": "Tagged Next",
                    "CommunityRating": 8,
                    "Tags": ["Drama", "PosterPulse"],
                },
                {
                    "Id": "tagged-low",
                    "Name": "Tagged Low",
                    "CommunityRating": 7,
                    "Tags": ["POSTERPULSE"],
                },
            ]
        )
        client.get_item_poster_image = Mock(return_value="poster-image")

        with patch("main.random.choice", side_effect=lambda items: items[0]):
            result = client.get_top_rated_movie_image(100, 100)

        self.assertEqual(result, ("tagged-high", "Tagged High", "poster-image"))

    def test_active_playback_fetches_and_checks_tags(self):
        client = self.make_client()

        def fake_get(url, *, params=None, timeout=10):
            if url.endswith("/Sessions"):
                return SimpleNamespace(
                    json=lambda: [
                        {
                            "Id": "session-id",
                            "NowPlayingItem": {
                                "Type": "Movie",
                                "Id": "movie-id",
                                "Name": "Tagged Movie",
                            },
                        }
                    ]
                )
            return SimpleNamespace(json=lambda: {"Tags": ["poster pulse"]})

        client._get = fake_get

        sessions = client.get_active_media_sessions()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["item_id"], "movie-id")


if __name__ == "__main__":
    unittest.main()
