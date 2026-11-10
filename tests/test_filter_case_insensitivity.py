import os
import unittest
from unittest.mock import Mock, patch

from main import JellyfinClient, Settings


class FilterCaseInsensitivityTests(unittest.TestCase):
    def make_client(self, **settings_overrides):
        settings = Settings(
            jellyfin_url="http://jellyfin",
            api_token="test-token",
            poster_tags=[],
            **settings_overrides,
        )
        return JellyfinClient(settings)

    def test_included_and_excluded_genres_are_case_insensitive(self):
        client = self.make_client(genres=["action"], excluded_genres=["documentary"])

        self.assertTrue(
            client._matches_item_filters({"Genres": ["ACTION"]}, "included")
        )
        self.assertFalse(
            client._matches_item_filters(
                {"Genres": ["Action", "DOCUMENTARY"]}, "excluded"
            )
        )

    def test_selected_movie_titles_are_case_insensitive(self):
        client = self.make_client()
        client.resolve_user_id = Mock(return_value="user-id")
        client._get_all_items = Mock(
            return_value=[{"Id": "movie-id", "Name": "INCEPTION"}]
        )
        client.get_item_poster_image = Mock(return_value="poster-image")

        result = client.get_random_poster_image(
            100, 100, selected_movies=["inception"]
        )

        self.assertEqual(result, ("movie-id", "INCEPTION", "poster-image"))

    def test_collection_names_are_case_insensitive(self):
        client = self.make_client(collections=["pixar"])
        client._get_all_items = Mock(
            return_value=[{"Id": "collection-id", "Name": "PIXAR"}]
        )

        self.assertEqual(client._resolve_collection_ids("user-id"), ["collection-id"])

    def test_media_type_values_are_case_insensitive(self):
        with patch("main.load_dotenv"), patch.dict(
            os.environ,
            {
                "JELLYFIN_URL": "http://jellyfin",
                "JELLYFIN_API_TOKEN": "test-token",
                "MEDIA_TYPES": "movie, SERIES",
            },
            clear=True,
        ):
            settings = Settings.from_env()

        self.assertEqual(settings.media_types, ["Movie", "Series"])


if __name__ == "__main__":
    unittest.main()
