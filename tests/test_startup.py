import builtins
import sys
import unittest
from unittest.mock import patch

from main import Settings, main


class RegularDisplayStartupTests(unittest.TestCase):
    def run_with_missing_module(self, module_name):
        original_import = builtins.__import__

        def import_without_module(name, *args, **kwargs):
            if name == "displays.regular":
                raise ModuleNotFoundError(
                    f"No module named '{module_name}'", name=module_name
                )
            return original_import(name, *args, **kwargs)

        settings = Settings(jellyfin_url="http://jellyfin", api_token="test-token")
        with (
            patch("main.Settings.from_env", return_value=settings),
            patch("main.PosterCoordinator"),
            patch("builtins.__import__", side_effect=import_without_module),
        ):
            return main()

    def test_missing_tkinter_reports_installation_instructions(self):
        for module_name in ("tkinter", "_tkinter"):
            with (
                self.subTest(module_name=module_name),
                self.assertLogs("main", level="ERROR") as logs,
            ):
                self.assertEqual(self.run_with_missing_module(module_name), 1)

            self.assertIn("cannot be installed with pip", logs.output[0])
            self.assertIn(
                f"brew install python-tk@{sys.version_info.major}.{sys.version_info.minor}",
                logs.output[0],
            )

    def test_unrelated_missing_dependencies_are_not_hidden(self):
        with self.assertRaises(ModuleNotFoundError) as error:
            self.run_with_missing_module("unrelated_dependency")

        self.assertEqual(error.exception.name, "unrelated_dependency")


if __name__ == "__main__":
    unittest.main()
