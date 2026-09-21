"""Behavioral regression tests for runtime selection and video-load recovery."""

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import downloader
from engine import ProcessCancelledError


def load_launcher():
    gi = ModuleType("gi")
    gi.require_version = lambda *_args: None
    repository = ModuleType("gi.repository")
    repository.Gdk = SimpleNamespace()
    repository.Gio = SimpleNamespace()
    repository.GLib = SimpleNamespace(idle_add=lambda callback, *args: callback(*args))
    repository.Gtk = SimpleNamespace(ApplicationWindow=object, Application=object)
    gi.repository = repository
    spec = importlib.util.spec_from_file_location("_loader_test", ROOT / "app/rhythm_forge.py")
    launcher = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
        spec.loader.exec_module(launcher)
    return launcher


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory(prefix="runtime with spaces ")
        self.addCleanup(fixture.cleanup)
        self.directory = Path(fixture.name)
        env = patch.dict(os.environ, {"PATH": str(self.directory)})
        env.start()
        self.addCleanup(env.stop)

    def binary(self, name, banner, code=0):
        path = self.directory / name
        path.write_text(f"#!{sys.executable}\nprint({banner!r})\nraise SystemExit({code})\n")
        path.chmod(0o755)
        return path

    def test_supported_deno_wins_over_node(self):
        deno = self.binary("deno", "deno 2.3.0\nv8 13.5")
        self.binary("node", "v22.0.0")
        self.assertEqual(downloader.find_js_runtime(), f"deno:{deno}")

    def test_old_deno_falls_back_to_node(self):
        self.binary("deno", "deno 2.2.9")
        node = self.binary("node", "v22.0.0")
        self.assertEqual(downloader.find_js_runtime(), f"node:{node}")

    def test_nonzero_and_invalid_probes_fall_back(self):
        node = self.binary("node", "v24.1.0")
        for banner, code in (("deno 9.0.0", 1), ("unrelated 9.0.0", 0), ("deno 2.3.0-rc.1", 0)):
            with self.subTest(banner=banner, code=code):
                self.binary("deno", banner, code)
                self.assertEqual(downloader.find_js_runtime(), f"node:{node}")

    def test_old_node_and_missing_runtime_are_rejected(self):
        self.assertIsNone(downloader.find_js_runtime())
        self.binary("node", "v20.19.0")
        self.assertIsNone(downloader.find_js_runtime())

    def test_excessive_probe_output_is_bounded_and_falls_back(self):
        self.binary("deno", "x" * 5000)
        node = self.binary("node", "v22.2.0")
        self.assertEqual(downloader.find_js_runtime(), f"node:{node}")

    def test_cancelled_probe_does_not_start_another_runtime(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(ProcessCancelledError):
            downloader.find_js_runtime(event)

    def test_browser_is_opt_in_and_runtime_path_stays_one_argument(self):
        self.binary("node", "v22.0.0")
        args = downloader.download_options()
        self.assertIn("--ignore-config", args)
        self.assertIn("--no-remote-components", args)
        self.assertNotIn("--cookies-from-browser", args)
        self.assertEqual(args[args.index("--js-runtimes") + 1], f"node:{self.directory / 'node'}")
        self.assertEqual(downloader.download_options("firefox")[-2:], ["--cookies-from-browser", "firefox"])
        for invalid in ("--exec touch /tmp/x", "firefox:unknown-profile", ""):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                downloader.download_options(invalid)

    def test_checker_reports_missing_runtime_and_arch_ejs(self):
        # Real Python probe, fake unrelated desktop packages; no GUI required.
        import subprocess
        self.binary("node", "v20.0.0")
        python = self.directory / "python3"
        python.write_text(f'#!/bin/sh\n[ "$1" = "-I" ] && exit 0\nexec {sys.executable!r} "$@"\n')
        python.chmod(0o755)
        for name, body in {
            "yt-dlp": "exit 0", "ffmpeg": "exit 0", "ffprobe": "exit 0",
            "pacman": "exit 0", "qml": 'echo "Qml Runtime 6.11.2"',
            "timeout": 'shift\nexec "$@"',
        }.items():
            path = self.directory / name
            path.write_text("#!/bin/sh\n" + body + "\n")
            path.chmod(0o755)
        result = subprocess.run([str(ROOT / "app/check-dependencies")], capture_output=True, text=True,
                                env={**os.environ, "RHYTHM_FORGE_QT6_QML": str(self.directory / "absent")}, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Missing packages: deno.", result.stdout)
        self.binary("node", "v22.0.0")
        result = subprocess.run([str(ROOT / "app/check-dependencies")], capture_output=True, text=True,
                                env={**os.environ, "RHYTHM_FORGE_QT6_QML": str(self.directory / "absent")}, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.directory / "pacman").write_text('#!/bin/sh\n[ "$1" = "-Qqo" ] && { echo yt-dlp; exit 0; }\n[ "$2" = "yt-dlp-ejs" ] && exit 1\nexit 0\n')
        result = subprocess.run([str(ROOT / "app/check-dependencies")], capture_output=True, text=True,
                                env={**os.environ, "RHYTHM_FORGE_QT6_QML": str(self.directory / "absent")}, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Missing packages: yt-dlp-ejs.", result.stdout)


class ErrorTests(unittest.TestCase):
    def test_error_categories_have_actionable_messages(self):
        cases = (
            ("ERROR: Sign in to confirm you’re not a bot", "Browser session"),
            ("ERROR: could not find firefox cookies database", "browser session could not be read"),
            ("WARNING: No supported JavaScript runtime\nERROR: Requested format is not available", "JavaScript challenge"),
            ("WARNING: challenge solving failed\nERROR: download failed", "yt-dlp-ejs"),
            ("WARNING: GVS PO Token missing\nERROR: HTTP Error 403", "Proof of Origin"),
            ("ERROR: HTTP Error 403: Forbidden", "HTTP 403"),
            ("ERROR: HTTP Error 429: Too Many Requests", "rate-limiting"),
            ("ERROR: Video unavailable", "unavailable or restricted"),
            ("ERROR: no such option: --js-runtimes", "too old"),
            ("ERROR: unable to download webpage: timed out", "connection"),
        )
        for diagnostic, expected in cases:
            with self.subTest(diagnostic=diagnostic):
                self.assertIn(expected, downloader.download_error(diagnostic, "Download failed."))

    def test_verification_error_outranks_optional_format_warnings(self):
        message = downloader.download_error("WARNING: GVS PO Token missing\nERROR: Sign in to confirm you're not a bot", "Failed.")
        self.assertIn("Browser session", message)
        self.assertNotIn("Proof of Origin", message)

    def test_unknown_error_never_exposes_sensitive_service_output(self):
        message = downloader.download_error("ERROR: SECRET_TOKEN at https://example.com/?cookie=SECRET_COOKIE", "Download failed.")
        self.assertNotIn("SECRET", message)
        self.assertNotIn("https://", message)
        self.assertLess(len(message), 500)


class LoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = load_launcher()

    def setUp(self):
        fixture = tempfile.TemporaryDirectory(prefix="loader with spaces ")
        self.addCleanup(fixture.cleanup)
        self.directory = Path(fixture.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.cache = self.directory / "cache"
        self.track_dir = self.cache / "tracks/Youtube-test"
        self.track_dir.mkdir(parents=True)
        self.log = self.directory / "argv.jsonl"
        self.complete = []
        self.failed = []
        self.event = threading.Event()
        self.loader = self.launcher.TrackLoader("https://www.youtube.com/watch?v=test", lambda *_: None,
            lambda *_: None, lambda *args: self.complete.append(args), self.failed.append, self.event)
        for context in (
            patch.dict(os.environ, {"PATH": str(self.bin)}),
            patch.object(self.launcher, "cache_root", return_value=self.cache),
            patch.object(self.launcher, "analyze_media_chart", return_value=([1.0] * 8, [{"time": 1.0}])),
        ):
            context.start()
            self.addCleanup(context.stop)

    def fake_downloader(self, metadata_error="", download_error="", final_name="track.mp4", metadata_output=None):
        metadata_output = json.dumps({"id": "test", "extractor_key": "Youtube", "title": "Test", "duration": 42}) if metadata_output is None else metadata_output
        script = f'''#!{sys.executable}
import json, sys
from pathlib import Path
args = sys.argv[1:]
with Path({str(self.log)!r}).open('a') as log:
    log.write(json.dumps(args) + '\\n')
metadata = '--print' in args
error = {metadata_error!r} if metadata else {download_error!r}
if error:
    print(error, file=sys.stderr)
    raise SystemExit(1)
if metadata:
    print({metadata_output!r})
else:
    output = Path(args[args.index('-o') + 1]).parent / {final_name!r}
    output.write_bytes(b'fake media')
    print('[download] 100%')
'''
        path = self.bin / "yt-dlp"
        path.write_text(script)
        path.chmod(0o755)

    def test_metadata_and_download_share_runtime_and_opt_in_session(self):
        self.fake_downloader()
        node = self.bin / "node"
        node.write_text('#!/bin/sh\necho v22.0.0\n')
        node.chmod(0o755)
        self.loader.browser = "firefox"
        self.loader.run()
        self.assertEqual(self.failed, [])
        self.assertEqual(len(self.complete), 1)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        for args in calls:
            self.assertEqual(args[args.index("--cookies-from-browser") + 1], "firefox")
            self.assertEqual(args[args.index("--js-runtimes") + 1], f"node:{node}")
            self.assertIn("--ignore-config", args)
            self.assertIn("--no-remote-components", args)
            self.assertNotIn("--no-warnings", args)
            self.assertEqual(args[-2:], ["--", self.loader.url])

    def test_default_requests_do_not_read_browser_cookies(self):
        self.fake_downloader()
        self.loader.run()
        self.assertEqual(len(self.complete), 1)
        self.assertNotIn("--cookies-from-browser", self.log.read_text())

    def test_verification_failure_stops_before_download(self):
        self.fake_downloader(metadata_error="ERROR: Sign in to confirm you're not a bot")
        self.loader.run()
        self.assertEqual(self.complete, [])
        self.assertIn("Browser session", self.failed[0])
        self.assertEqual(len(self.log.read_text().splitlines()), 1)

    def test_download_failure_includes_ejs_warning_context(self):
        self.fake_downloader(download_error="WARNING: challenge solving failed\nERROR: Requested format is not available")
        self.loader.run()
        self.assertEqual(self.complete, [])
        self.assertIn("yt-dlp-ejs", self.failed[0])

    def test_split_streams_are_ignored_and_retried(self):
        for name in ("track.f137.mp4", "track.f140.m4a", "track.mp4.part", "track.mp4.ytdl", "track.temp.mp4", "track.json", "track.m4a"):
            (self.track_dir / name).write_bytes(b'incomplete')
        self.assertIsNone(self.launcher.TrackLoader.find_media(self.track_dir))
        self.fake_downloader()
        self.loader.run()
        self.assertEqual(self.failed, [])
        self.assertEqual(self.complete[0][0].name, "track.mp4")
        self.assertEqual(len(self.log.read_text().splitlines()), 2)

    def test_completed_media_is_reused(self):
        (self.track_dir / "track.mp4").write_bytes(b'complete')
        self.fake_downloader()
        self.loader.run()
        self.assertEqual(len(self.complete), 1)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)

    def test_zero_length_and_partial_output_do_not_complete(self):
        (self.track_dir / "track.mp4").touch()
        self.fake_downloader(final_name="track.f137.mp4")
        self.loader.run()
        self.assertEqual(self.complete, [])
        self.assertIn("no playable video", self.failed[0])

    def test_malformed_metadata_and_invalid_duration_never_download(self):
        for metadata in ("not json", "[]", '{"duration": "nan"}', '{"duration": 1201}'):
            with self.subTest(metadata=metadata):
                self.failed.clear()
                self.log.unlink(missing_ok=True)
                self.fake_downloader(metadata_output=metadata)
                self.loader.run()
                self.assertEqual(self.complete, [])
                self.assertEqual(len(self.failed), 1)
                self.assertEqual(len(self.log.read_text().splitlines()), 1)

    def test_cancellation_remains_actionable(self):
        self.fake_downloader()
        self.event.set()
        self.loader.run()
        self.assertEqual(self.complete, [])
        self.assertEqual(self.failed, ["Loading was cancelled."])
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
