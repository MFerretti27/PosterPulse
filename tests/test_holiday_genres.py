import os
import unittest
import warnings
from datetime import date
from unittest.mock import Mock, patch

from main import HolidayRule, JellyfinClient, Settings


class HolidayDateSettingsTests(unittest.TestCase):
    def make_settings(self, days):
        with (
            patch("main.load_dotenv"),
            patch.dict(
                os.environ,
                {
                    "JELLYFIN_URL": "http://jellyfin",
                    "JELLYFIN_API_TOKEN": "test-token",
                    "HOLIDAY_MODE": "true",
                    "HOLIDAYS": "Holiday",
                    "HOLIDAY_GENRE": "Family",
                    "HOLIDAY_DAYS": days,
                },
                clear=True,
            ),
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("error", DeprecationWarning)
            return Settings.from_env()

    def test_holiday_dates_parse_without_deprecation_warnings(self):
        rule = self.make_settings(" 12/18 - 12/31 ").holiday_rules[0]

        self.assertEqual(rule.start_month_day, (12, 18))
        self.assertEqual(rule.end_month_day, (12, 31))
        self.assertTrue(rule.is_active(date(2026, 12, 18)))
        self.assertTrue(rule.is_active(date(2026, 12, 31)))
        self.assertFalse(rule.is_active(date(2026, 12, 17)))

    def test_leap_day_is_valid_for_recurring_holidays(self):
        rule = self.make_settings("02/29-03/01").holiday_rules[0]

        self.assertEqual(rule.start_month_day, (2, 29))
        self.assertTrue(rule.is_active(date(2028, 2, 29)))

    def test_holiday_range_can_cross_new_year(self):
        rule = self.make_settings("12/18-01/07").holiday_rules[0]

        self.assertTrue(rule.is_active(date(2026, 12, 31)))
        self.assertTrue(rule.is_active(date(2027, 1, 7)))
        self.assertFalse(rule.is_active(date(2027, 1, 8)))

    def test_invalid_calendar_dates_are_rejected(self):
        for days in ("02/30-03/01", "12/18-04/31", "13/01-12/31"):
            with (
                self.subTest(days=days),
                self.assertRaisesRegex(ValueError, "must use valid MM/DD-MM/DD dates"),
            ):
                self.make_settings(days)


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

        with patch(
            "main.random.choices", side_effect=lambda items, **kwargs: [items[0]]
        ):
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
            client._matches_item_filters({"Genres": ["CHRISTMAS", "family"]}, "both")
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
