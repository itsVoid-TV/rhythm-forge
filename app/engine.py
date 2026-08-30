"""Pure game and audio-analysis helpers for Rhythm Forge."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import shutil
import statistics
import struct
import subprocess
from typing import Callable, Iterable
from urllib.parse import urlparse


SAMPLE_RATE = 11_025
HOP_SAMPLES = 256
HOP_SECONDS = HOP_SAMPLES / SAMPLE_RATE
HIT_WINDOW_MS = 200
SPAM_GAP_SECONDS = 0.34
SPAM_MIN_TAPS = 4
HOLD_MIN_SECONDS = 0.85
HOLD_MAX_SECONDS = 4.0
VOICE_SAMPLE_RATE = 4_000
VOICE_FRAME_SAMPLES = 320
VOICE_HOP_SAMPLES = 80


def validate_video_url(value: str) -> str:
    """Return a normalized HTTP(S) URL or raise a user-facing ValueError."""
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a complete http:// or https:// music-video link.")
    if parsed.username or parsed.password:
        raise ValueError("Links containing a username or password are not supported.")
    return value


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    amount = position - lower
    return ordered[lower] * (1.0 - amount) + ordered[upper] * amount


def _local_stats(values: list[float], index: int, radius: int = 18) -> tuple[float, float]:
    start = max(0, index - radius)
    end = min(len(values), index + radius + 1)
    neighborhood = values[start:end]
    mean = statistics.fmean(neighborhood) if neighborhood else 0.0
    deviation = statistics.pstdev(neighborhood) if len(neighborhood) > 1 else 0.0
    return mean, deviation


def detect_beats_from_features(
    energy: list[float],
    brightness: list[float],
    hop_seconds: float = HOP_SECONDS,
) -> list[float]:
    """Detect musical onsets from per-frame energy and high-frequency activity.

    This deliberately uses only the Python standard library. The adaptive
    threshold handles quiet verses and loud choruses independently.
    """
    count = min(len(energy), len(brightness))
    if count < 5:
        return []

    energy = energy[:count]
    brightness = brightness[:count]
    e_scale = max(percentile(energy, 0.95), 1.0)
    b_scale = max(percentile(brightness, 0.95), 1.0)
    novelty: list[float] = [0.0]
    for index in range(1, count):
        energy_rise = max(0.0, energy[index] - energy[index - 1]) / e_scale
        bright_rise = max(0.0, brightness[index] - brightness[index - 1]) / b_scale
        sustained = max(0.0, energy[index] / e_scale - 0.08)
        novelty.append(energy_rise * 0.60 + bright_rise * 0.32 + sustained * 0.08)

    floor = max(0.018, percentile(novelty, 0.58))
    candidates: list[tuple[float, float]] = []
    adaptive_radius = max(4, round(0.84 / hop_seconds))
    for index in range(2, count - 2):
        value = novelty[index]
        local_mean, local_deviation = _local_stats(novelty, index, adaptive_radius)
        threshold = max(floor, local_mean + local_deviation * 0.72)
        if value < threshold:
            continue
        if value < max(novelty[index - 2:index] + novelty[index + 1:index + 3]):
            continue
        # Refine the peak between feature frames with a parabolic estimate.
        # The half-frame term maps the measurement to the center of its PCM
        # window instead of making every note systematically early.
        previous = novelty[index - 1]
        following = novelty[index + 1]
        denominator = previous - 2.0 * value + following
        fractional = 0.0
        if abs(denominator) > 1e-12:
            fractional = max(-0.5, min(0.5, 0.5 * (previous - following) / denominator))
        candidates.append(((index + 0.5 + fractional) * hop_seconds, value))

    # Keep the strongest onset when candidates crowd the same playable window.
    refractory = 0.235
    selected: list[tuple[float, float]] = []
    for candidate in candidates:
        if not selected or candidate[0] - selected[-1][0] >= refractory:
            selected.append(candidate)
        elif candidate[1] > selected[-1][1]:
            selected[-1] = candidate

    # Skip codec-start noise and cap pathological charts at a humane density.
    return [round(time_s, 4) for time_s, _strength in selected if time_s >= 0.35]


def pcm_features(pcm: bytes, hop_samples: int = HOP_SAMPLES) -> tuple[list[float], list[float]]:
    usable = len(pcm) - (len(pcm) % 2)
    samples = struct.unpack(f"<{usable // 2}h", pcm[:usable]) if usable else ()
    energy: list[float] = []
    brightness: list[float] = []
    for start in range(0, len(samples) - hop_samples + 1, hop_samples):
        frame = samples[start:start + hop_samples]
        square_sum = sum(sample * sample for sample in frame)
        energy.append(math.sqrt(square_sum / hop_samples))
        brightness.append(sum(abs(frame[i] - frame[i - 1]) for i in range(1, len(frame))) / (len(frame) - 1))
    return energy, brightness


def detect_voiced_segments(
    pcm: bytes,
    sample_rate: int = VOICE_SAMPLE_RATE,
    frame_samples: int = VOICE_FRAME_SAMPLES,
    hop_samples: int = VOICE_HOP_SAMPLES,
) -> list[dict[str, float]]:
    """Find stable pitched phrases in voice-band PCM.

    Normalized autocorrelation distinguishes vowels and other voiced syllables
    from noisy percussion. Pitch continuity then separates a held vowel from a
    sequence of changing sung notes. This remains dependency-free and is fast
    enough to run beside the percussion analysis.
    """
    usable = len(pcm) - (len(pcm) % 2)
    samples = struct.unpack(f"<{usable // 2}h", pcm[:usable]) if usable else ()
    if len(samples) < frame_samples:
        return []

    frames: list[tuple[int, float, float, float]] = []
    minimum_lag = max(2, round(sample_rate / 500.0))
    maximum_lag = min(frame_samples // 2, round(sample_rate / 90.0))
    rms_values: list[float] = []
    prepared: list[tuple[int, list[float], float]] = []
    for start in range(0, len(samples) - frame_samples + 1, hop_samples):
        raw = samples[start:start + frame_samples]
        mean = statistics.fmean(raw)
        centered = [sample - mean for sample in raw]
        energy_sum = sum(sample * sample for sample in centered)
        rms = math.sqrt(energy_sum / frame_samples)
        rms_values.append(rms)
        prepared.append((start, centered, energy_sum))

    energy_threshold = max(90.0, percentile(rms_values, 0.30) * 1.22)
    for (start, centered, energy_sum), rms in zip(prepared, rms_values):
        if rms < energy_threshold or energy_sum <= 1.0:
            frames.append((start, rms, 0.0, 0.0))
            continue
        best_lag = 0
        best_confidence = 0.0
        square_prefix = [0.0]
        for sample in centered:
            square_prefix.append(square_prefix[-1] + sample * sample)
        for lag in range(minimum_lag, maximum_lag + 1):
            count = frame_samples - lag
            numerator = sum(centered[index] * centered[index + lag] for index in range(count))
            left = square_prefix[count]
            right = square_prefix[frame_samples] - square_prefix[lag]
            denominator = math.sqrt(left * right)
            confidence = numerator / denominator if denominator > 1.0 else 0.0
            if confidence > best_confidence:
                best_confidence = confidence
                best_lag = lag
        pitch = sample_rate / best_lag if best_lag else 0.0
        frames.append((start, rms, best_confidence, pitch))

    segments: list[dict[str, float]] = []
    current: list[tuple[int, float, float, float]] = []
    dropout = 0
    allowed_dropout = max(1, round(0.12 * sample_rate / hop_samples))

    def finish_current() -> None:
        nonlocal current, dropout
        voiced = [frame for frame in current if frame[2] >= 0.54]
        if voiced:
            start_s = voiced[0][0] / sample_rate
            end_s = (voiced[-1][0] + frame_samples) / sample_rate
            segments.append({
                "start": round(start_s, 4),
                "end": round(end_s, 4),
                "confidence": round(statistics.fmean(frame[2] for frame in voiced), 4),
                "pitch": round(statistics.median(frame[3] for frame in voiced), 2),
            })
        current = []
        dropout = 0

    for frame in frames:
        voiced = frame[2] >= 0.54 and 90.0 <= frame[3] <= 500.0
        pitch_fits = True
        if voiced and current:
            recent_pitches = [item[3] for item in current[-10:] if item[2] >= 0.54]
            if recent_pitches:
                reference = statistics.median(recent_pitches)
                raw_cents = 1200.0 * math.log2(frame[3] / reference)
                # Mixed vocals often make autocorrelation alternate between a
                # fundamental and its octave. Treat octave-equivalent estimates
                # as one sustained note instead of fragmenting the vowel.
                octave_cents = abs(raw_cents - round(raw_cents / 1200.0) * 1200.0)
                pitch_fits = octave_cents <= 320.0
        if voiced and pitch_fits:
            current.append(frame)
            dropout = 0
        elif current:
            dropout += 1
            if dropout <= allowed_dropout:
                current.append((frame[0], frame[1], 0.0, 0.0))
            else:
                finish_current()
                if voiced:
                    current.append(frame)
    if current:
        finish_current()

    minimum_phrase = 0.14
    return [segment for segment in segments if segment["end"] - segment["start"] >= minimum_phrase]


def build_note_chart(
    beats: Iterable[float],
    energy: list[float] | None = None,
    hop_seconds: float = HOP_SECONDS,
    vocal_segments: Iterable[dict[str, float]] = (),
) -> list[dict[str, float | int | str]]:
    """Turn onset times into tap, spam, and sustained hold notes.

    Dense onset runs become one readable SPAM block. HOLD notes require a
    sufficiently long gap after the onset and, when an energy envelope is
    available, a genuinely sustained signal instead of silence.
    """
    vocal_segments = sorted(vocal_segments, key=lambda segment: segment["start"])
    vocal_holds: list[tuple[float, float]] = []
    vocal_taps: list[float] = []
    for segment in vocal_segments:
        start = float(segment["start"])
        end = float(segment["end"])
        duration = end - start
        if duration >= 0.72 and float(segment.get("confidence", 0.0)) >= 0.58:
            vocal_holds.append((start, min(end, start + HOLD_MAX_SECONDS)))
        elif duration >= 0.14:
            vocal_taps.append(start)

    times = sorted(float(value) for value in beats)
    for vocal_tap in vocal_taps:
        if not any(abs(existing - vocal_tap) <= 0.18 for existing in times):
            times.append(vocal_tap)
    times.sort()
    chart: list[dict[str, float | int | str]] = []
    smoothed: list[float] = []
    if energy:
        for index in range(len(energy)):
            start = max(0, index - 2)
            end = min(len(energy), index + 3)
            smoothed.append(statistics.fmean(energy[start:end]))
    energy_floor = percentile(smoothed, 0.35) if smoothed else 0.0

    def sustained_end(start_time: float, next_time: float | None) -> float | None:
        available = (next_time - start_time - 0.24) if next_time is not None else HOLD_MAX_SECONDS
        limit = min(HOLD_MAX_SECONDS, available)
        if limit < HOLD_MIN_SECONDS:
            return None
        if not smoothed:
            # Cached legacy maps have no envelope. Be conservative: only
            # convert medium-size gaps, never long silent breaks.
            if next_time is None or next_time - start_time > 3.2:
                return None
            return start_time + min(1.4, limit)

        onset_index = min(len(smoothed) - 1, max(0, round(start_time / hop_seconds)))
        reference_end = min(len(smoothed), onset_index + max(2, round(0.22 / hop_seconds)))
        reference = max(smoothed[onset_index:reference_end], default=0.0)
        threshold = max(energy_floor * 1.18, reference * 0.30)
        first = min(len(smoothed), onset_index + round(0.16 / hop_seconds))
        last = min(len(smoothed), onset_index + round(limit / hop_seconds) + 1)
        allowed_dropout = max(1, round(0.14 / hop_seconds))
        dropout = 0
        final_active = first
        for index in range(first, last):
            if smoothed[index] >= threshold:
                final_active = index
                dropout = 0
            else:
                dropout += 1
                if dropout > allowed_dropout:
                    break
        duration = (final_active - onset_index) * hop_seconds
        if duration < HOLD_MIN_SECONDS:
            return None
        return round(start_time + min(duration, HOLD_MAX_SECONDS), 4)

    index = 0
    while index < len(times):
        run_end = index
        while run_end + 1 < len(times) and times[run_end + 1] - times[run_end] <= SPAM_GAP_SECONDS:
            run_end += 1
        run_count = run_end - index + 1
        if run_count >= SPAM_MIN_TAPS:
            chart.append({
                "type": "spam",
                "start": round(times[index], 4),
                "end": round(times[run_end], 4),
                "taps": run_count,
            })
            index = run_end + 1
            continue

        next_time = times[index + 1] if index + 1 < len(times) else None
        hold_end = sustained_end(times[index], next_time)
        if hold_end is not None:
            chart.append({"type": "hold", "start": round(times[index], 4), "end": hold_end})
        else:
            chart.append({"type": "tap", "start": round(times[index], 4), "end": round(times[index], 4)})
        index += 1
    # Vocal holds are independent of percussion. Replace any colliding drum
    # notes so one-key gameplay never asks the player to hold and tap at once.
    merged_holds: list[tuple[float, float]] = []
    for start, end in vocal_holds:
        if merged_holds and start <= merged_holds[-1][1] + 0.10:
            old_start, old_end = merged_holds[-1]
            merged_holds[-1] = (old_start, min(old_start + HOLD_MAX_SECONDS, max(old_end, end)))
        else:
            merged_holds.append((start, end))
    for start, end in merged_holds:
        chart = [
            note for note in chart
            if float(note["end"]) < start - 0.12 or float(note["start"]) > end + 0.05
        ]
        chart.append({"type": "hold", "start": round(start, 4), "end": round(end, 4)})
    chart.sort(key=lambda note: float(note["start"]))
    return chart


def analyze_media_chart(
    path: Path,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[list[float], list[dict[str, float | int | str]]]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to analyze the track.")

    duration = probe_duration(path)
    command = [
        ffmpeg, "-v", "error", "-i", str(path), "-vn", "-ac", "1",
        "-ar", str(SAMPLE_RATE), "-f", "s16le", "-",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    chunks: list[bytes] = []
    read_bytes = 0
    expected_bytes = max(1, int(duration * SAMPLE_RATE * 2))
    assert process.stdout is not None
    while True:
        chunk = process.stdout.read(256 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
        read_bytes += len(chunk)
        if on_progress:
            on_progress(min(0.72, read_bytes / expected_bytes * 0.72))
    stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
    if process.wait() != 0:
        raise RuntimeError(stderr.strip() or "ffmpeg could not decode this video.")

    energy, brightness = pcm_features(b"".join(chunks))
    beats = detect_beats_from_features(energy, brightness)
    if len(beats) < 8:
        raise RuntimeError("Not enough clear beats were found. Try a track with stronger percussion.")

    voice_command = [
        ffmpeg, "-v", "error", "-i", str(path), "-vn", "-ac", "1",
        "-af", "highpass=f=90,lowpass=f=1800",
        "-ar", str(VOICE_SAMPLE_RATE), "-f", "s16le", "-",
    ]
    voice_result = subprocess.run(voice_command, capture_output=True, check=False)
    if voice_result.returncode != 0:
        message = voice_result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(message or "ffmpeg could not analyze the vocal range.")
    if on_progress:
        on_progress(0.90)
    vocal_segments = detect_voiced_segments(voice_result.stdout)
    if on_progress:
        on_progress(1.0)
    return beats, build_note_chart(beats, energy, vocal_segments=vocal_segments)


def analyze_media(path: Path, on_progress: Callable[[float], None] | None = None) -> list[float]:
    """Compatibility helper returning only onset times."""
    beats, _chart = analyze_media_chart(path, on_progress)
    return beats


def probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required to read the track duration.")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        duration = float(result.stdout.strip())
    except ValueError as error:
        raise RuntimeError(result.stderr.strip() or "Could not read the video duration.") from error
    if duration <= 0:
        raise RuntimeError("The video has no playable duration.")
    return duration


@dataclass(frozen=True)
class Judgement:
    label: str
    points: int
    weight: float


def judge_timing(delta_ms: float) -> Judgement | None:
    distance = abs(delta_ms)
    if distance <= 70:
        return Judgement("PERFECT", 1000, 1.0)
    if distance <= 130:
        return Judgement("GREAT", 650, 0.75)
    if distance <= HIT_WINDOW_MS:
        return Judgement("GOOD", 350, 0.45)
    return None


class ScoreState:
    def __init__(self) -> None:
        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self.judged = 0
        self.accuracy_total = 0.0

    def register(self, judgement: Judgement | None) -> None:
        self.judged += 1
        if judgement is None:
            self.combo = 0
            return
        self.combo += 1
        self.max_combo = max(self.max_combo, self.combo)
        multiplier = 1.0 + min(1.0, self.combo / 50.0)
        self.score += round(judgement.points * multiplier)
        self.accuracy_total += judgement.weight

    @property
    def accuracy(self) -> float:
        return 100.0 * self.accuracy_total / self.judged if self.judged else 100.0


def nearest_playable_beat(beats: Iterable[float], start_index: int, time_s: float) -> tuple[int, float] | None:
    beat_list = list(beats)
    best: tuple[int, float] | None = None
    for index in range(max(0, start_index), min(len(beat_list), start_index + 5)):
        delta_ms = (time_s - beat_list[index]) * 1000.0
        if best is None or abs(delta_ms) < abs(best[1]):
            best = (index, delta_ms)
        if beat_list[index] > time_s + HIT_WINDOW_MS / 1000.0:
            break
    if best and abs(best[1]) <= HIT_WINDOW_MS:
        return best
    return None
