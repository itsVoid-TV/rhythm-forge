"""Exercise the real runtime resolver without requiring a GTK display."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class Qt6RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Stub only the GUI import boundary, not either resolver function.
        # No application/window is instantiated by these tests.
        gi = ModuleType("gi")
        gi.require_version = lambda *_args: None
        repository = ModuleType("gi.repository")
        repository.Gdk = SimpleNamespace()
        repository.Gio = SimpleNamespace()
        repository.GLib = SimpleNamespace()
        repository.Gtk = SimpleNamespace(ApplicationWindow=object, Application=object)
        gi.repository = repository
        spec = importlib.util.spec_from_file_location(
            "_rhythm_forge_runtime_test", ROOT / "app" / "rhythm_forge.py"
        )
        cls.launcher = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}), patch.object(
            sys, "path", [str(ROOT / "app"), *sys.path]
        ):
            spec.loader.exec_module(cls.launcher)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        environment = patch.dict(os.environ, {
            "PATH": str(self.bin),
            "RHYTHM_FORGE_QT6_QML": str(self.directory / "absent"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        for name in ("python3", "yt-dlp", "ffmpeg", "ffprobe", "pacman"):
            self.command(self.bin / name, "exit 0")
        self.command(self.bin / "timeout", 'shift\nexec "$@"')

    def command(self, path, body):
        path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        path.chmod(0o755)
        return str(path)

    def runtime(self, path, major=6, stderr=False):
        redirect = " >&2" if stderr else ""
        return self.command(
            path,
            '[ "$1" = "-v" ] || exit 2\n'
            f'echo "Qml Runtime {major}.11.2"{redirect}',
        )

    def assert_checker(self, ready):
        result = subprocess.run(
            [str(ROOT / "app" / "check-dependencies")],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=2,
        )
        self.assertEqual(result.returncode, 0 if ready else 1, result.stderr)
        if ready:
            self.assertEqual(result.stdout.strip(), "Rhythm Forge is ready.")
        else:
            self.assertIn("Missing packages: qt6-declarative.", result.stdout)

    def test_default_versioned_path_is_probed_first(self):
        with patch.dict(os.environ, {"RHYTHM_FORGE_QT6_QML": ""}), patch.object(
            self.launcher.os, "access", return_value=True
        ), patch.object(
            self.launcher.shutil, "which", side_effect=["/path/qml6", "/path/qml"]
        ), patch.object(
            self.launcher, "is_qt6_qml", return_value=True
        ) as probe:
            self.assertEqual(self.launcher.find_qt6_qml(), "/usr/lib/qt6/bin/qml")
            probe.assert_called_once_with("/usr/lib/qt6/bin/qml")

    def test_override_with_spaces_wins_over_qt5_on_path(self):
        expected = self.runtime(self.directory / "qt6 runtime")
        os.environ["RHYTHM_FORGE_QT6_QML"] = expected
        self.runtime(self.bin / "qml", major=5)
        self.assertEqual(self.launcher.find_qt6_qml(), expected)
        self.assert_checker(True)

    def test_qml6_wins_over_qt5_qml(self):
        expected = self.runtime(self.bin / "qml6")
        self.runtime(self.bin / "qml", major=5)
        self.assertEqual(self.launcher.find_qt6_qml(), expected)
        self.assert_checker(True)

    def test_plain_qml_is_accepted_when_it_reports_qt6(self):
        expected = self.runtime(self.bin / "qml")
        self.assertEqual(self.launcher.find_qt6_qml(), expected)
        self.assert_checker(True)

    def test_qt5_only_is_rejected_by_launcher_and_checker(self):
        self.runtime(self.bin / "qml", major=5)
        self.assertIsNone(self.launcher.find_qt6_qml())
        self.assert_checker(False)

    def test_qml6_name_does_not_bypass_version_check(self):
        self.runtime(self.bin / "qml6", major=5)
        self.assertIsNone(self.launcher.find_qt6_qml())
        self.assert_checker(False)

    def test_invalid_override_falls_back_to_valid_qml6(self):
        os.environ["RHYTHM_FORGE_QT6_QML"] = self.runtime(
            self.directory / "wrong-runtime", major=5
        )
        expected = self.runtime(self.bin / "qml6")
        self.assertEqual(self.launcher.find_qt6_qml(), expected)
        self.assert_checker(True)

    def test_version_banner_on_stderr_is_accepted(self):
        expected = self.runtime(self.bin / "qml", stderr=True)
        self.assertEqual(self.launcher.find_qt6_qml(), expected)
        self.assert_checker(True)

    def test_missing_runtime_is_reported(self):
        self.assertIsNone(self.launcher.find_qt6_qml())
        self.assert_checker(False)

    def test_non_executable_runtime_is_skipped(self):
        binary = self.runtime(self.bin / "qml")
        Path(binary).chmod(0o644)
        self.assertIsNone(self.launcher.find_qt6_qml())
        self.assert_checker(False)

    def test_probe_handles_os_error_and_timeout(self):
        errors = (OSError("not executable"), subprocess.TimeoutExpired("qml", 10))
        for error in errors:
            with self.subTest(error=error), patch.object(
                self.launcher.subprocess, "run", side_effect=error
            ) as run:
                self.assertFalse(self.launcher.is_qt6_qml("/missing/qml"))
                self.assertEqual(run.call_args.kwargs["timeout"], 10)
                self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
