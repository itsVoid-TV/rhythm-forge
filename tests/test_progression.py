import sys
from pathlib import Path
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from progression import COLOR_GROUPS, COLOR_PRICE, ProgressionStore, advancement_rank  # noqa: E402


class ProgressionStoreTests(unittest.TestCase):
    def test_purchase_and_equip_persist_in_qt_ini_format(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timing.ini"
            path.write_text("[display]\nsavedVSync=true\n\n[progression]\nstars=20\n", encoding="utf-8")
            store = ProgressionStore(path)

            changed, _message = store.buy("spam", "spamBlue")
            self.assertTrue(changed)
            values = store.read()
            self.assertEqual(int(values["stars"]), 20 - COLOR_PRICE)
            self.assertTrue(store.is_owned(values, "spam", "spamBlue"))

            equipped, _message = store.equip("spam", "spamBlue")
            self.assertTrue(equipped)
            self.assertEqual(store.read()["equippedSpam"], "spamBlue")
            self.assertIn("savedVSync=true", path.read_text(encoding="utf-8"))

    def test_purchase_requires_stars_and_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProgressionStore(Path(directory) / "timing.ini")
            changed, message = store.buy("lane", "laneYellow")
            self.assertFalse(changed)
            self.assertIn("15 more stars", message)
            equipped, _message = store.equip("lane", "laneYellow")
            self.assertFalse(equipped)

    def test_background_theme_purchase_is_backward_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timing.ini"
            path.write_text("[progression]\nstars=30\n", encoding="utf-8")
            store = ProgressionStore(path)

            values = store.read()
            self.assertEqual(values["equippedBackground"], "backgroundDefault")
            self.assertTrue(store.is_owned(values, "background", "backgroundDefault"))

            changed, _message = store.buy("background", "backgroundNebula")
            self.assertTrue(changed)
            equipped, _message = store.equip("background", "backgroundNebula")
            self.assertTrue(equipped)
            self.assertEqual(store.read()["equippedBackground"], "backgroundNebula")

    def test_advancement_ranks(self):
        self.assertEqual(advancement_rank(0), "ROOKIE")
        self.assertEqual(advancement_rank(30), "BEAT RIDER")
        self.assertEqual(advancement_rank(100), "RHYTHM LEGEND")

    def test_every_style_category_has_a_default_and_multiple_unlocks(self):
        self.assertEqual(set(COLOR_GROUPS), {"spam", "hold", "lane", "background"})
        game_qml = (Path(__file__).resolve().parents[1] / "app" / "Game.qml").read_text(encoding="utf-8")
        for styles in COLOR_GROUPS.values():
            self.assertEqual(sum(style["kind"] == "default" for style in styles), 1)
            self.assertGreaterEqual(sum(style["kind"] == "shop" for style in styles), 5)
            self.assertGreaterEqual(sum(style["kind"] == "event" for style in styles), 1)
            for style in styles:
                self.assertIn(f'"{style["id"]}"', game_qml)


if __name__ == "__main__":
    unittest.main()
