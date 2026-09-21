from pathlib import Path
import json
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SecurityContractTests(unittest.TestCase):
    # "timeout" must run its command instead of stubbing it out, otherwise the
    # Qt 6 version probe in check-dependencies can never observe a banner.
    STUB_BODIES = {
        "timeout": '#!/bin/sh\nshift\nexec "$@"\n',
        "qml": '#!/bin/sh\necho "Qml Runtime 6.11.2"\n',
    }

    @classmethod
    def fake_commands(
        cls,
        directory: Path,
        names: tuple[str, ...],
        bodies: dict[str, str] | None = None,
    ) -> None:
        overrides = {**cls.STUB_BODIES, **(bodies or {})}
        for name in names:
            path = directory / name
            path.write_text(
                overrides.get(name, "#!/bin/sh\nexit 0\n"), encoding="utf-8"
            )
            path.chmod(0o755)

    def test_external_qml_text_is_plain_and_bounded(self):
        game = (ROOT / "app" / "Game.qml").read_text(encoding="utf-8")
        self.assertIn('root.trackTitle = root.safeExternalText', game)
        self.assertIn('root.playbackError = root.safeExternalText', game)
        self.assertIn('text: root.trackTitle + "  —  " + root.trackArtist\n            textFormat: Text.PlainText', game)
        self.assertIn('text: root.playbackError; textFormat: Text.PlainText', game)

    def test_marketplace_launcher_has_in_bar_dependency_state(self):
        widget = (ROOT / "BarWidget.qml").read_text(encoding="utf-8")
        checker = (ROOT / "app" / "check-dependencies").read_text(encoding="utf-8")
        self.assertIn("Process {\n    id: dependencyCheck", widget)
        self.assertIn('Qt.resolvedUrl("app/check-dependencies")', widget)
        self.assertIn("omarchy-notification-send", checker)
        self.assertIn("omarchy-pkg-add", checker)
        self.assertNotIn("notify-send", checker)
        self.assertNotIn("sudo pacman", checker)

    def test_gameplay_polish_keeps_bounded_one_key_mechanics(self):
        game = (ROOT / "app" / "Game.qml").read_text(encoding="utf-8")
        self.assertIn("function updateActiveHold(now, note)", game)
        self.assertIn("Math.max(0, Math.min(16, Math.floor((cappedNow - holdLastTickAt) / 250)))", game)
        self.assertIn("Math.min(16, Math.max(1, Number(note.taps || 1)))", game)
        self.assertIn('property string equippedBackground: "backgroundDefault"', game)
        self.assertIn("root.backgroundTheme", game)

    def test_manifest_and_launcher_versions_match(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        launcher = (ROOT / "app" / "rhythm_forge.py").read_text(encoding="utf-8")
        self.assertIn(f'VERSION = "{manifest["version"]}"', launcher)

    def test_dependency_checker_accepts_complete_runtime(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            self.fake_commands(
                directory,
                ("python3", "timeout", "yt-dlp", "ffmpeg", "ffprobe", "qml", "pacman"),
            )
            result = subprocess.run(
                [ROOT / "app" / "check-dependencies"],
                capture_output=True,
                text=True,
                timeout=2,
                env={
                    "PATH": str(directory),
                    "RHYTHM_FORGE_QT6_QML": str(directory / "absent-qt6-qml"),
                },
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "Rhythm Forge is ready.")

    def test_dependency_checker_reports_only_missing_packages(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            self.fake_commands(
                directory,
                ("python3", "timeout", "ffmpeg", "ffprobe", "qml", "pacman"),
            )
            result = subprocess.run(
                [ROOT / "app" / "check-dependencies"],
                capture_output=True,
                text=True,
                timeout=2,
                env={
                    "PATH": str(directory),
                    "RHYTHM_FORGE_QT6_QML": str(directory / "absent-qt6-qml"),
                },
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("Missing packages: yt-dlp.", result.stdout)
            self.assertNotIn("python-gobject", result.stdout)

    def test_dependency_checker_rejects_qt5_qml_on_path(self):
        """qt5-declarative owns /usr/bin/qml and must not satisfy Qt 6."""
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            self.fake_commands(
                directory,
                ("python3", "timeout", "yt-dlp", "ffmpeg", "ffprobe", "qml", "pacman"),
                bodies={"qml": '#!/bin/sh\necho "Qml Runtime 5.15.19"\n'},
            )
            result = subprocess.run(
                [ROOT / "app" / "check-dependencies"],
                capture_output=True,
                text=True,
                timeout=10,
                env={
                    "PATH": str(directory),
                    "RHYTHM_FORGE_QT6_QML": str(directory / "absent-qt6-qml"),
                },
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("qt6-declarative", result.stdout)

    def test_launcher_resolves_qt6_qml_before_path_qml(self):
        launcher = (ROOT / "app" / "rhythm_forge.py").read_text(encoding="utf-8")
        self.assertIn("def find_qt6_qml()", launcher)
        self.assertIn('QT6_QML_BANNER = "Qml Runtime 6"', launcher)
        self.assertNotIn('qml = shutil.which("qml")', launcher)
        candidates = launcher.index("    candidates = (")
        qt6_path = launcher.index('"/usr/lib/qt6/bin/qml"', candidates)
        path_qml = launcher.index('shutil.which("qml")', candidates)
        self.assertLess(qt6_path, path_qml)


if __name__ == "__main__":
    unittest.main()
