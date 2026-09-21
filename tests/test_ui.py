"""Smoke-test the actual GTK setup screen under Xvfb in CI."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
try:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gio, Gtk
    GTK_AVAILABLE = Gdk.Display.get_default() is not None
except (ImportError, ValueError):
    GTK_AVAILABLE = False

if os.environ.get("RHYTHM_FORGE_REQUIRE_GTK_TESTS") == "1" and not GTK_AVAILABLE:
    raise RuntimeError("GTK smoke tests are required here, but GTK 4 or its display is unavailable.")


@unittest.skipUnless(GTK_AVAILABLE, "GTK 4 and a display are required (CI uses Xvfb)")
class SetupSmokeTests(unittest.TestCase):
    def setUp(self):
        import rhythm_forge
        self.launcher = rhythm_forge
        fixture = tempfile.TemporaryDirectory()
        self.addCleanup(fixture.cleanup)
        env = patch.dict(os.environ, {"XDG_CACHE_HOME": fixture.name})
        env.start()
        self.addCleanup(env.stop)
        self.app = Gtk.Application(application_id="io.github.omarchy.rhythmforge.test",
                                   flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.app.register(None)
        self.window = rhythm_forge.RhythmForgeWindow(self.app)
        self.addCleanup(self.window.destroy)

    def test_browser_session_is_opt_in_and_passed_to_worker(self):
        self.assertEqual(self.window.browser_session.get_selected(), 0)
        self.window.browser_session.set_selected(1)
        self.window.url_entry.set_text("https://www.youtube.com/watch?v=test")
        with patch.object(self.launcher, "TrackLoader") as loader, patch.object(self.launcher.threading, "Thread"):
            self.window.load_track()
        self.assertEqual(loader.call_args.kwargs["browser"], "firefox")
        self.assertFalse(self.window.browser_session.get_sensitive())
        self.window.show_load_error("A test error")
        self.assertTrue(self.window.browser_session.get_sensitive())

    def test_default_download_has_no_browser_and_success_restores_controls(self):
        self.window.url_entry.set_text("https://www.youtube.com/watch?v=test")
        with patch.object(self.launcher, "TrackLoader") as loader, patch.object(self.launcher.threading, "Thread"):
            self.window.load_track()
        self.assertIsNone(loader.call_args.kwargs["browser"])
        self.window.track_ready(Path("/tmp/test.mp4"), [1.0], [{"time": 1.0}], "Test", "Artist", 42)
        self.assertTrue(self.window.browser_session.get_sensitive())
        self.assertTrue(self.window.ready_box.get_visible())


if __name__ == "__main__":
    unittest.main()
