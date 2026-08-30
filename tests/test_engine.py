import math
import struct
import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from engine import (  # noqa: E402
    ScoreState,
    build_note_chart,
    detect_voiced_segments,
    detect_beats_from_features,
    judge_timing,
    nearest_playable_beat,
    pcm_features,
    validate_video_url,
)


class UrlValidationTests(unittest.TestCase):
    def test_accepts_https(self):
        self.assertEqual(validate_video_url(" https://example.com/watch?v=1 "), "https://example.com/watch?v=1")

    def test_rejects_non_web_schemes(self):
        for value in ("", "youtube.com/test", "file:///etc/passwd", "javascript:alert(1)"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_video_url(value)

    def test_rejects_credentials(self):
        with self.assertRaises(ValueError):
            validate_video_url("https://name:secret@example.com/video")


class BeatDetectionTests(unittest.TestCase):
    def test_detects_regular_transients(self):
        energy = [10.0] * 220
        brightness = [8.0] * 220
        expected = []
        for index in range(12, 210, 11):
            energy[index] = 1000.0
            brightness[index] = 800.0
            expected.append(index * 0.05)
        beats = detect_beats_from_features(energy, brightness, hop_seconds=0.05)
        self.assertGreaterEqual(len(beats), len(expected) - 2)
        for target in expected[1:-1]:
            self.assertTrue(any(abs(found - target) <= 0.051 for found in beats))
        self.assertAlmostEqual(beats[0], expected[0] + 0.025, places=3)

    def test_silence_has_no_beats(self):
        self.assertEqual(detect_beats_from_features([0.0] * 100, [0.0] * 100), [])

    def test_pcm_feature_frames(self):
        samples = [int(10_000 * math.sin(index / 8)) for index in range(1024)]
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        energy, brightness = pcm_features(pcm, hop_samples=512)
        self.assertEqual(len(energy), 2)
        self.assertTrue(all(value > 0 for value in energy))
        self.assertTrue(all(value > 0 for value in brightness))

    def test_groups_spam_and_detects_sustained_hold(self):
        beats = [0.50, 0.75, 1.00, 1.25, 2.00, 3.40, 4.00]
        energy = [10.0] * 60
        for index in range(19, 32):
            energy[index] = 100.0
        chart = build_note_chart(beats, energy, hop_seconds=0.1)
        self.assertEqual(chart[0], {"type": "spam", "start": 0.5, "end": 1.25, "taps": 4})
        self.assertEqual(chart[1]["type"], "hold")
        self.assertGreaterEqual(chart[1]["end"] - chart[1]["start"], 0.85)
        self.assertEqual(chart[-1]["type"], "tap")

    def test_short_runs_remain_individual_taps(self):
        chart = build_note_chart([0.5, 0.8, 1.1])
        self.assertEqual([note["type"] for note in chart], ["tap", "tap", "tap"])

    def test_detects_sustained_voiced_tone(self):
        sample_rate = 4000
        samples = [0] * int(sample_rate * 0.3)
        samples.extend(int(9000 * math.sin(2 * math.pi * 200 * index / sample_rate)) for index in range(int(sample_rate * 1.2)))
        samples.extend([0] * int(sample_rate * 0.3))
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        segments = detect_voiced_segments(pcm, sample_rate=sample_rate)
        self.assertTrue(any(segment["end"] - segment["start"] >= 1.0 for segment in segments))

    def test_keeps_octave_switching_processed_vocal_as_one_phrase(self):
        sample_rate = 4000
        samples = [0] * int(sample_rate * 0.3)
        phase = 0.0
        phrase_samples = int(sample_rate * 1.1)
        switch_samples = int(sample_rate * 0.08)
        for index in range(phrase_samples):
            frequency = 180.0 if (index // switch_samples) % 2 == 0 else 360.0
            phase += 2 * math.pi * frequency / sample_rate
            samples.append(int(9000 * math.sin(phase)))
        samples.extend([0] * int(sample_rate * 0.3))
        pcm = struct.pack(f"<{len(samples)}h", *samples)
        segments = detect_voiced_segments(pcm, sample_rate=sample_rate)
        self.assertTrue(any(segment["end"] - segment["start"] >= 0.9 for segment in segments))

    def test_vocal_hold_replaces_colliding_drum_notes(self):
        chart = build_note_chart(
            [1.0, 1.25, 1.5, 1.75, 2.0, 3.0],
            vocal_segments=[{"start": 0.95, "end": 2.2, "confidence": 0.8, "pitch": 180.0}],
        )
        holds = [note for note in chart if note["type"] == "hold"]
        self.assertEqual(holds, [{"type": "hold", "start": 0.95, "end": 2.2}])
        self.assertFalse(any(0.95 <= note["start"] <= 2.2 and note["type"] != "hold" for note in chart))


class ScoringTests(unittest.TestCase):
    def test_timing_bands(self):
        self.assertEqual(judge_timing(70).label, "PERFECT")
        self.assertEqual(judge_timing(-130).label, "GREAT")
        self.assertEqual(judge_timing(200).label, "GOOD")
        self.assertIsNone(judge_timing(201))

    def test_combo_and_accuracy(self):
        score = ScoreState()
        score.register(judge_timing(0))
        score.register(judge_timing(100))
        score.register(None)
        self.assertEqual(score.combo, 0)
        self.assertEqual(score.max_combo, 2)
        self.assertAlmostEqual(score.accuracy, (1.0 + 0.75) / 3 * 100)

    def test_nearest_beat(self):
        self.assertEqual(nearest_playable_beat([1.0, 2.0, 3.0], 0, 1.94), (1, -60.00000000000006))
        self.assertIsNone(nearest_playable_beat([1.0, 2.0], 0, 1.5))


if __name__ == "__main__":
    unittest.main()
