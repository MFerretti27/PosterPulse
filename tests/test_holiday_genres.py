import unittest
from unittest.mock import Mock, patch

from main import HolidayRule, JellyfinClient, Settings


class HolidayGenreFilterTests(unittest.TestCase):
    def make_client(self, **settings_overrides):
        settings = Settings(
            jellyfin_url="http://jellyfin",
            api_token="test-token",
            poster_tags=[],
            **settings_overrides,
        )
        return JellyfinClient(settings)

    def test_holiday_selection_requires_every_configured_genre(self):
        rule = HolidayRule(
            name="Holiday",
            genres=["Christmas", "Family"],
            start_month_day=(1, 1),
            end_month_day=(12, 31),
        )
        client = self.make_client(holiday_mode=True, holiday_rules=[rule])
        client.resolve_user_id = Mock(return_value="user-id")
        client._get_all_items = Mock(
            return_value=[
                {
                    "Id": "christmas-only",
                    "Name": "Christmas Only",
                    "Genres": ["Christmas"],
                },
                {
                    "Id": "both-genres",
                    "Name": "Both Genres",
                    "Genres": ["Christmas", "Family"],
                },
            ]
        )
        client.get_item_poster_image = Mock(return_value="poster-image")

        with patch("main.random.choice", side_effect=lambda items: items[0]):
            result = client.get_random_poster_image(100, 100)

        self.assertEqual(result, ("both-genres", "Both Genres", "poster-image"))

    def test_active_playback_requires_every_holiday_genre(self):
        rule = HolidayRule(
            name="Holiday",
            genres=["Christmas", "Family"],
            start_month_day=(1, 1),
            end_month_day=(12, 31),
        )
        client = self.make_client(holiday_mode=True, holiday_rules=[rule])

        self.assertFalse(client._matches_item_filters({"Genres": ["Christmas"]}, "one"))
        self.assertTrue(
            client._matches_item_filters(
                {"Genres": ["CHRISTMAS", "family"]}, "both"
            )
        )

    def test_regular_genres_continue_matching_any_configured_genre(self):
        client = self.make_client(genres=["Action", "Comedy"])

        self.assertTrue(
            client._matches_genre_filter({"action"}, {"action", "comedy"}, False)
        )
        self.assertFalse(
            client._matches_genre_filter({"drama"}, {"action", "comedy"}, False)
        )


if __name__ == "__main__":
    unittest.main()
