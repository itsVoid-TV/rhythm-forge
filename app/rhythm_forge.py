#!/usr/bin/env python3
"""Rhythm Forge — an Omarchy-native one-key music-video rhythm game."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from engine import (
    HIT_WINDOW_MS,
    MAX_MEDIA_DURATION_SECONDS,
    ProcessCancelledError,
    ScoreState,
    analyze_media_chart,
    judge_timing,
    nearest_playable_beat,
    run_bounded_process,
    sanitize_external_text,
    terminate_process_group,
    validate_video_url,
)
from progression import COLOR_GROUPS, COLOR_PRICE, ProgressionStore, advancement_rank


APP_ID = "io.github.omarchy.rhythmforge"
APP_NAME = "Rhythm Forge"
VERSION = "1.0.12"
MAX_DURATION_SECONDS = MAX_MEDIA_DURATION_SECONDS
BEATMAP_VERSION = 6
MAX_METADATA_BYTES = 64 * 1024
MAX_DOWNLOAD_LOG_BYTES = 1024 * 1024
MAX_DOWNLOAD_LINE_BYTES = 4096
DOWNLOAD_TIMEOUT_SECONDS = 30 * 60
MAX_TITLE_LENGTH = 160
MAX_ARTIST_LENGTH = 100
MAX_UI_ERROR_LENGTH = 500


CSS = b"""
window { background: #090b13; color: #f4f5fb; }
.hero { font-size: 34px; font-weight: 800; letter-spacing: 1px; }
.subtitle { color: #aeb4ca; font-size: 15px; }
.card { background: rgba(25, 28, 43, 0.96); border: 1px solid rgba(143, 119, 255, 0.35); border-radius: 18px; padding: 24px; }
.accent-button { background: #8668ff; color: white; font-weight: 700; border-radius: 10px; padding: 10px 18px; }
.accent-button:hover { background: #9b84ff; }
.secondary-button { background: rgba(255,255,255,0.08); color: #f4f5fb; border-radius: 10px; padding: 9px 15px; }
.stat { font-size: 24px; font-weight: 800; text-shadow: 0 2px 8px #000; }
.stat-label { color: #bec3d7; font-size: 11px; font-weight: 700; letter-spacing: 2px; text-shadow: 0 2px 8px #000; }
.judgement { font-size: 42px; font-weight: 900; text-shadow: 0 3px 12px #000; }
.hint { background: rgba(5, 7, 13, 0.82); border-radius: 12px; padding: 9px 16px; color: #d8dbee; }
.error { color: #ff8096; }
.success { color: #79edc0; }
entry { background: #111522; color: #f7f7fb; border: 1px solid #3f4661; border-radius: 10px; padding: 12px; }
progressbar trough { background: #131726; border-radius: 6px; min-height: 7px; }
progressbar progress { background: #8668ff; border-radius: 6px; min-height: 7px; }
"""


def cache_root() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".cache"
    path = base / "rhythm-forge"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_history() -> list[dict]:
    try:
        data = json.loads((cache_root() / "history.json").read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [entry for entry in data if isinstance(entry, dict)][:8]
    except (OSError, TypeError, json.JSONDecodeError):
        return []


def write_history(entries: list[dict]) -> None:
    destination = cache_root() / "history.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(entries[:8], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(destination)


def safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")[:100] or "track"


class BoundedLineTail:
    """Decode a process stream without accepting unbounded individual lines."""

    def __init__(self, on_line=None, tail_lines: int = 12) -> None:
        self.on_line = on_line
        self.tail_lines = tail_lines
        self.pending = bytearray()
        self.tail: list[str] = []

    def feed(self, chunk: bytes, _total: int) -> None:
        self.pending.extend(chunk)
        while True:
            newline = self.pending.find(b"\n")
            if newline < 0:
                if len(self.pending) > MAX_DOWNLOAD_LINE_BYTES:
                    raise RuntimeError("yt-dlp produced an overlong output line.")
                return
            raw_line = bytes(self.pending[:newline])
            del self.pending[:newline + 1]
            self._record(raw_line)

    def finish(self) -> None:
        if self.pending:
            self._record(bytes(self.pending))
            self.pending.clear()

    def _record(self, raw_line: bytes) -> None:
        if len(raw_line) > MAX_DOWNLOAD_LINE_BYTES:
            raise RuntimeError("yt-dlp produced an overlong output line.")
        line = raw_line.decode("utf-8", "replace").strip()
        if line:
            self.tail.append(line)
            del self.tail[:-self.tail_lines]
            if self.on_line:
                self.on_line(line)


class TrackLoader:
    def __init__(self, url: str, status, progress, complete, failed, cancel_event: threading.Event) -> None:
        self.url = url
        self.status = status
        self.progress = progress
        self.complete = complete
        self.failed = failed
        self.cancel_event = cancel_event

    def emit(self, callback, *args) -> None:
        GLib.idle_add(callback, *args)

    def run(self) -> None:
        try:
            yt_dlp = shutil.which("yt-dlp")
            if not yt_dlp:
                raise RuntimeError("yt-dlp is unavailable. Reopen Rhythm Forge from the bar to check dependencies.")

            self.emit(self.status, "Reading video information…")
            metadata_code, metadata_stdout, metadata_stderr = run_bounded_process(
                [
                    yt_dlp,
                    "--ignore-config",
                    "--no-playlist",
                    "--socket-timeout", "15",
                    "--retries", "3",
                    "--no-warnings",
                    "--print", "%(.{id,extractor_key,title,artist,uploader,duration})j",
                    "--",
                    self.url,
                ],
                timeout=45,
                stdout_limit=MAX_METADATA_BYTES,
                cancel_event=self.cancel_event,
            )
            if metadata_code != 0:
                raise RuntimeError(self.clean_error(metadata_stderr.decode("utf-8", "replace"), "The video link could not be opened."))
            metadata = json.loads(metadata_stdout.decode("utf-8", "strict"))
            if not isinstance(metadata, dict):
                raise RuntimeError("The video service returned invalid metadata.")
            duration = float(metadata.get("duration") or 0)
            if not math.isfinite(duration) or duration <= 0:
                raise RuntimeError("This video does not report a playable duration.")
            if duration > MAX_DURATION_SECONDS:
                raise RuntimeError("Choose a video shorter than 20 minutes.")

            track_id = safe_component(f"{metadata.get('extractor_key', 'video')}-{metadata.get('id', 'track')}")
            track_dir = cache_root() / "tracks" / track_id
            track_dir.mkdir(parents=True, exist_ok=True)
            media = self.find_media(track_dir)

            if media is None:
                self.emit(self.status, "Downloading a 720p game copy…")
                output_template = str(track_dir / "track.%(ext)s")
                command = [
                    yt_dlp,
                    "--ignore-config",
                    "--no-playlist",
                    "--newline",
                    "--no-warnings",
                    "--socket-timeout", "15",
                    "--retries", "3",
                    "--fragment-retries", "3",
                    "--retry-sleep", "1",
                    "--max-filesize", "750M",
                    "-f", "bv*[vcodec^=avc1][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]/bv*[height<=720]+ba/b[height<=720]/b",
                    "--merge-output-format", "mp4",
                    "-o", output_template,
                    "--",
                    self.url,
                ]

                def update_download_progress(line: str) -> None:
                    match = re.search(r"\[download\]\s+([0-9.]+)%", line)
                    if match:
                        self.emit(self.progress, min(0.72, float(match.group(1)) / 100.0 * 0.72))

                stdout_lines = BoundedLineTail(update_download_progress)
                stderr_lines = BoundedLineTail()
                download_code, _output, _download_stderr = run_bounded_process(
                    command,
                    timeout=DOWNLOAD_TIMEOUT_SECONDS,
                    stdout_limit=MAX_DOWNLOAD_LOG_BYTES,
                    stderr_limit=MAX_DOWNLOAD_LOG_BYTES,
                    on_stdout=stdout_lines.feed,
                    on_stderr=stderr_lines.feed,
                    capture_stdout=False,
                    capture_stderr=False,
                    cancel_event=self.cancel_event,
                )
                stdout_lines.finish()
                stderr_lines.finish()
                if download_code != 0:
                    output_tail = stdout_lines.tail + stderr_lines.tail
                    raise RuntimeError(self.clean_error("\n".join(output_tail), "The video download failed."))
                media = self.find_media(track_dir)
                if media is None:
                    raise RuntimeError("The download completed but no playable video was created.")

            beatmap_path = track_dir / "beatmap.json"
            beats: list[float]
            notes: list[dict]
            cached = self.read_beatmap(beatmap_path, media)
            if cached is not None:
                self.emit(self.status, "Using the cached beat map…")
                beats, notes = cached
                self.emit(self.progress, 1.0)
            else:
                self.emit(self.status, "Separating percussion, vocal syllables, and held notes…")
                beats, notes = analyze_media_chart(
                    media,
                    lambda value: self.emit(self.progress, 0.72 + value * 0.28),
                    self.cancel_event,
                )
                self.write_beatmap(beatmap_path, media, beats, notes)

            title = sanitize_external_text(metadata.get("title"), "Untitled track", MAX_TITLE_LENGTH)
            artist = sanitize_external_text(
                metadata.get("artist") or metadata.get("uploader"),
                "Unknown artist",
                MAX_ARTIST_LENGTH,
            )
            self.emit(self.complete, media, beats, notes, title, artist, duration)
        except ProcessCancelledError:
            self.emit(self.failed, "Loading was cancelled.")
        except Exception as error:  # Worker errors must become UI messages.
            message = sanitize_external_text(str(error), error.__class__.__name__, MAX_UI_ERROR_LENGTH)
            self.emit(self.failed, message)

    @staticmethod
    def find_media(track_dir: Path) -> Path | None:
        ignored = {".part", ".ytdl", ".json"}
        candidates = [
            path for path in track_dir.glob("track.*")
            if path.is_file() and path.suffix.lower() not in ignored and path.stat().st_size > 0
        ]
        return max(candidates, key=lambda path: path.stat().st_mtime_ns) if candidates else None

    @staticmethod
    def read_beatmap(path: Path, media: Path) -> tuple[list[float], list[dict]] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") != BEATMAP_VERSION or data.get("media_mtime_ns") != media.stat().st_mtime_ns:
                return None
            beats = [float(value) for value in data.get("beats", [])]
            notes = [value for value in data.get("notes", []) if isinstance(value, dict)]
            return (beats, notes) if len(beats) >= 8 and notes else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def write_beatmap(path: Path, media: Path, beats: list[float], notes: list[dict]) -> None:
        path.write_text(json.dumps({
            "version": BEATMAP_VERSION,
            "media_mtime_ns": media.stat().st_mtime_ns,
            "beats": beats,
            "notes": notes,
        }, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def clean_error(output: str, fallback: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        useful = next((line for line in reversed(lines) if "ERROR:" in line), "")
        if useful:
            return useful.replace("ERROR:", "", 1).strip()
        return lines[-1][:300] if lines else fallback


class RhythmForgeWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(1120, 720)
        self.set_size_request(760, 560)

        self.media: Gtk.MediaFile | None = None
        self.media_path: Path | None = None
        self.beats: list[float] = []
        self.notes: list[dict] = []
        self.title_text = ""
        self.artist_text = ""
        self.current_url = ""
        self.current_duration = 0.0
        self.next_beat = 0
        self.score = ScoreState()
        self.playing = False
        self.paused = False
        self.finished = False
        self.input_offset_ms = 0
        self.last_judgement = ""
        self.last_judgement_time = 0.0
        self.flash_strength = 0.0
        self.loader_active = False
        self.awaiting_playback = False
        self.history_recorded = False
        self.media_generation = 0
        self.game_process: subprocess.Popen | None = None
        self.loader_cancel_event = threading.Event()
        self.progression_store = ProgressionStore(cache_root() / "timing.ini")
        self.color_status_message = ""

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=220)
        self.stack.add_named(self.build_setup_page(), "setup")
        self.stack.add_named(self.build_game_page(), "game")
        self.set_child(self.stack)
        self.refresh_recent_tracks()
        self.refresh_progression_summary()

        key_controller = Gtk.EventControllerKey()
        # Gtk.Video binds Space to its own play/pause action. Capture keys at
        # the window before they reach the video so Space remains the game's
        # hit button regardless of which child currently has focus.
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)
        self.connect("close-request", self.on_close_request)
        GLib.timeout_add(16, self.tick)

    def build_setup_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        page.set_halign(Gtk.Align.CENTER)
        page.set_valign(Gtk.Align.START)
        page.set_margin_start(28)
        page.set_margin_end(28)
        page.set_margin_top(28)
        page.set_margin_bottom(28)

        icon = Gtk.Label(label="♫")
        icon.add_css_class("hero")
        title = Gtk.Label(label="RHYTHM FORGE")
        title.add_css_class("hero")
        subtitle = Gtk.Label(label="Turn a music-video link into a one-key rhythm challenge.")
        subtitle.add_css_class("subtitle")

        progression_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        progression_card.add_css_class("card")
        progression_card.set_size_request(650, -1)
        progression_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        progression_text.set_hexpand(True)
        progression_title = Gtk.Label(label="ADVANCEMENTS", xalign=0)
        progression_title.add_css_class("stat-label")
        self.progression_label = Gtk.Label(xalign=0)
        self.progression_label.set_wrap(True)
        progression_text.append(progression_title)
        progression_text.append(self.progression_label)
        shop_button = Gtk.Button(label="★ Shop")
        shop_button.add_css_class("accent-button")
        shop_button.connect("clicked", lambda _button: self.show_color_window("shop"))
        inventory_button = Gtk.Button(label="Inventory")
        inventory_button.add_css_class("secondary-button")
        inventory_button.connect("clicked", lambda _button: self.show_color_window("inventory"))
        progression_card.append(progression_text)
        progression_card.append(shop_button)
        progression_card.append(inventory_button)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.add_css_class("card")
        card.set_size_request(650, -1)
        prompt = Gtk.Label(label="MUSIC VIDEO LINK", xalign=0)
        prompt.add_css_class("stat-label")
        self.url_entry = Gtk.Entry()
        self.url_entry.set_placeholder_text("https://www.youtube.com/watch?v=…")
        self.url_entry.set_input_purpose(Gtk.InputPurpose.URL)
        self.url_entry.connect("activate", lambda _entry: self.load_track())

        self.load_button = Gtk.Button(label="Download & Analyze")
        self.load_button.add_css_class("accent-button")
        self.load_button.connect("clicked", lambda _button: self.load_track())

        self.progress = Gtk.ProgressBar(show_text=False)
        self.progress.set_visible(False)
        self.status_label = Gtk.Label(label="Video is cached locally after the first analysis.", xalign=0)
        self.status_label.add_css_class("subtitle")
        self.status_label.set_wrap(True)

        self.ready_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.ready_box.set_visible(False)
        self.track_label = Gtk.Label(xalign=0)
        self.track_label.set_wrap(True)
        self.track_label.add_css_class("success")
        self.start_button = Gtk.Button(label="Start Game")
        self.start_button.add_css_class("accent-button")
        self.start_button.connect("clicked", lambda _button: self.start_game())
        self.ready_box.append(self.track_label)
        self.ready_box.append(self.start_button)

        for child in (prompt, self.url_entry, self.load_button, self.progress, self.status_label, self.ready_box):
            card.append(child)

        self.recent_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.recent_card.add_css_class("card")
        self.recent_card.set_size_request(650, -1)
        recent_title = Gtk.Label(label="RECENTLY PLAYED", xalign=0)
        recent_title.add_css_class("stat-label")
        self.recent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.recent_card.append(recent_title)
        self.recent_card.append(self.recent_box)

        controls = Gtk.Label(label="SPACE / W / ↑  Hit or Hold   ·   P  Pause   ·   [ / ]  Timing offset")
        controls.add_css_class("hint")
        legal = Gtk.Label(label="Use only videos you are allowed to download. Supported sites depend on yt-dlp.")
        legal.add_css_class("subtitle")
        legal.set_wrap(True)

        for child in (icon, title, subtitle, progression_card, card, self.recent_card, controls, legal):
            page.append(child)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(page)
        return scroller

    def refresh_progression_summary(self) -> None:
        values = self.progression_store.read()
        stars = int(values["stars"])
        lifetime = int(values["lifetimeStars"])
        songs = int(values["songsCompleted"])
        events = int(values["eventWins"])
        self.progression_label.set_text(
            f"★ {stars} available  ·  {advancement_rank(lifetime)}  ·  "
            f"{songs} songs  ·  {events} event wins"
        )

    def show_color_window(self, mode: str) -> None:
        values = self.progression_store.read()
        stars = int(values["stars"])
        lifetime = int(values["lifetimeStars"])
        title = "Color Shop" if mode == "shop" else "Color Inventory"
        window = Gtk.Window(title=f"Rhythm Forge — {title}")
        window.set_transient_for(self)
        window.set_modal(True)
        window.set_default_size(720, 680)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_start(24)
        outer.set_margin_end(24)
        outer.set_margin_top(20)
        outer.set_margin_bottom(20)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        heading = Gtk.Label(label=title.upper(), xalign=0)
        heading.add_css_class("hero")
        heading.set_hexpand(True)
        wallet = Gtk.Label(label=f"★ {stars}")
        wallet.add_css_class("stat")
        close_button = Gtk.Button(label="Close")
        close_button.add_css_class("secondary-button")
        close_button.connect("clicked", lambda _button: window.close())
        header.append(heading)
        header.append(wallet)
        header.append(close_button)
        outer.append(header)

        if mode == "inventory":
            overview = Gtk.Label(
                label=(
                    f"{advancement_rank(lifetime)}  ·  {values['songsCompleted']} songs  ·  "
                    f"{values['eventWins']} event wins  ·  {lifetime} lifetime stars"
                ),
                xalign=0,
            )
            overview.add_css_class("subtitle")
            outer.append(overview)
        else:
            explanation = Gtk.Label(
                label=f"Every regular color costs ★{COLOR_PRICE}. Event-exclusive colors can only be won before songs.",
                xalign=0,
            )
            explanation.add_css_class("subtitle")
            explanation.set_wrap(True)
            outer.append(explanation)

        notice = Gtk.Label(label=self.color_status_message, xalign=0)
        notice.add_css_class("success")
        notice.set_visible(bool(self.color_status_message))
        outer.append(notice)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        group_names = {"spam": "SPAM COLORS", "hold": "HOLD COLORS", "lane": "TIMING-LINE COLORS"}
        equipped_keys = {"spam": "equippedSpam", "hold": "equippedHold", "lane": "equippedLane"}

        for category, colors in COLOR_GROUPS.items():
            section = Gtk.Label(label=group_names[category], xalign=0)
            section.add_css_class("stat-label")
            section.set_margin_top(12)
            content.append(section)
            visible_count = 0
            for color in colors:
                owned = self.progression_store.is_owned(values, category, color["id"])
                if mode == "inventory" and not owned:
                    continue
                if mode == "shop" and color["kind"] == "default":
                    continue
                visible_count += 1
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                row.add_css_class("card")
                swatch = Gtk.Label()
                swatch.set_markup(f"<span foreground=\"{color['hex']}\" size=\"xx-large\">●</span>")
                details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
                details.set_hexpand(True)
                name = Gtk.Label(label=color["name"], xalign=0)
                kind_text = "Event Exclusive" if color["kind"] == "event" else ("Included" if color["kind"] == "default" else f"Shop Color  ·  ★{COLOR_PRICE}")
                kind = Gtk.Label(label=f"{group_names[category][:-7].title()}  ·  {kind_text}", xalign=0)
                kind.add_css_class("subtitle")
                details.append(name)
                details.append(kind)
                row.append(swatch)
                row.append(details)

                if mode == "shop":
                    if owned:
                        action = Gtk.Button(label="Owned")
                        action.set_sensitive(False)
                    elif color["kind"] == "event":
                        action = Gtk.Button(label="Event Only")
                        action.set_sensitive(False)
                    else:
                        action = Gtk.Button(label=f"Buy  ★{COLOR_PRICE}")
                        action.add_css_class("accent-button")
                        action.set_sensitive(stars >= COLOR_PRICE)
                        action.connect(
                            "clicked",
                            lambda _button, selected_category=category, selected=color, owner=window: self.purchase_color(owner, selected_category, selected),
                        )
                else:
                    equipped = values[equipped_keys[category]] == color["id"]
                    action = Gtk.Button(label="Equipped" if equipped else "Equip")
                    action.set_sensitive(not equipped)
                    if not equipped:
                        action.add_css_class("accent-button")
                        action.connect(
                            "clicked",
                            lambda _button, selected_category=category, selected=color, owner=window: self.equip_color(owner, selected_category, selected),
                        )
                row.append(action)
                content.append(row)
            if visible_count == 0:
                empty = Gtk.Label(label="No colors unlocked in this category yet.", xalign=0)
                empty.add_css_class("subtitle")
                content.append(empty)

        if mode == "inventory":
            first_mark = "✓" if int(values["songsCompleted"]) >= 1 else "○"
            star_mark = "✓" if lifetime >= 30 else "○"
            event_mark = "✓" if int(values["eventWins"]) >= 1 else "○"
            achievements = Gtk.Label(
                label=(
                    "ADVANCEMENTS\n"
                    f"{first_mark} First Forge — Complete one song\n"
                    f"{star_mark} Star Collector — Earn 30 lifetime stars\n"
                    f"{event_mark} Event Hunter — Win a random event"
                ),
                xalign=0,
            )
            achievements.add_css_class("hint")
            achievements.set_margin_top(14)
            content.append(achievements)

        scroller.set_child(content)
        outer.append(scroller)
        window.set_child(outer)
        window.present()

    def purchase_color(self, window: Gtk.Window, category: str, color: dict[str, str]) -> None:
        _changed, message = self.progression_store.buy(category, color["id"])
        self.color_status_message = f"{color['name']}: {message}"
        window.close()
        self.refresh_progression_summary()
        self.show_color_window("shop")

    def equip_color(self, window: Gtk.Window, category: str, color: dict[str, str]) -> None:
        _changed, message = self.progression_store.equip(category, color["id"])
        self.color_status_message = f"{color['name']}: {message}"
        window.close()
        self.refresh_progression_summary()
        self.show_color_window("inventory")

    def refresh_recent_tracks(self) -> None:
        child = self.recent_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.recent_box.remove(child)
            child = next_child

        valid_entries = [entry for entry in read_history() if Path(str(entry.get("media_path", ""))).is_file()]
        self.recent_card.set_visible(bool(valid_entries))
        for entry in valid_entries[:5]:
            title = sanitize_external_text(entry.get("title"), "Untitled track", MAX_TITLE_LENGTH)
            artist = sanitize_external_text(entry.get("artist"), "Unknown artist", MAX_ARTIST_LENGTH)
            button = Gtk.Button(label=f"▶  {title}\n    {artist}")
            button.add_css_class("secondary-button")
            button.set_halign(Gtk.Align.FILL)
            button.connect("clicked", lambda _button, selected=entry: self.play_recent_track(selected))
            self.recent_box.append(button)

    def play_recent_track(self, entry: dict) -> None:
        media_path = Path(str(entry.get("media_path", "")))
        if not media_path.is_file():
            self.show_load_error("This cached video is missing. Paste its link to download it again.")
            return
        cached = TrackLoader.read_beatmap(media_path.parent / "beatmap.json", media_path)
        if cached is None:
            self.reanalyze_recent_track(entry, media_path)
            return
        beats, notes = cached
        self.open_recent_track(entry, media_path, beats, notes)

    def open_recent_track(self, entry: dict, media_path: Path, beats: list[float], notes: list[dict]) -> None:
        self.current_url = str(entry.get("url") or "")
        self.url_entry.set_text(self.current_url)
        self.track_ready(
            media_path,
            beats,
            notes,
            sanitize_external_text(entry.get("title"), "Untitled track", MAX_TITLE_LENGTH),
            sanitize_external_text(entry.get("artist"), "Unknown artist", MAX_ARTIST_LENGTH),
            float(entry.get("duration") or 0),
        )
        self.start_game()

    def reanalyze_recent_track(self, entry: dict, media_path: Path) -> None:
        if self.loader_active:
            return
        self.loader_active = True
        self.load_button.set_sensitive(False)
        self.progress.set_fraction(0.02)
        self.progress.set_visible(True)
        self.status_label.remove_css_class("error")
        self.status_label.set_text("Updating this track with vocal-aware lyric detection…")
        self.loader_cancel_event = threading.Event()
        cancel_event = self.loader_cancel_event

        def worker() -> None:
            try:
                beats, notes = analyze_media_chart(
                    media_path,
                    lambda value: GLib.idle_add(self.set_load_progress, value),
                    cancel_event,
                )
                TrackLoader.write_beatmap(media_path.parent / "beatmap.json", media_path, beats, notes)
                GLib.idle_add(self.recent_reanalysis_ready, entry, media_path, beats, notes)
            except ProcessCancelledError:
                GLib.idle_add(self.show_load_error, "Loading was cancelled.")
            except Exception as error:
                GLib.idle_add(
                    self.show_load_error,
                    sanitize_external_text(str(error), error.__class__.__name__, MAX_UI_ERROR_LENGTH),
                )

        threading.Thread(target=worker, name="beatmap-upgrade", daemon=True).start()

    def recent_reanalysis_ready(self, entry: dict, media_path: Path, beats: list[float], notes: list[dict]) -> bool:
        self.loader_active = False
        self.load_button.set_sensitive(True)
        self.progress.set_fraction(1.0)
        self.status_label.set_text(f"Chart updated — {len(notes)} playable blocks.")
        self.open_recent_track(entry, media_path, beats, notes)
        return GLib.SOURCE_REMOVE

    def record_recent_track(self) -> None:
        if self.history_recorded or not self.media_path:
            return
        current = {
            "url": self.current_url,
            "title": self.title_text,
            "artist": self.artist_text,
            "duration": self.current_duration,
            "media_path": str(self.media_path),
            "played_at": int(time.time()),
        }
        existing = [entry for entry in read_history() if entry.get("media_path") != current["media_path"]]
        write_history([current] + existing)
        self.history_recorded = True
        self.refresh_recent_tracks()

    def build_game_page(self) -> Gtk.Widget:
        overlay = Gtk.Overlay()
        self.video = Gtk.Video(autoplay=False)
        self.video.set_hexpand(True)
        self.video.set_vexpand(True)
        overlay.set_child(self.video)

        self.game_canvas = Gtk.DrawingArea()
        self.game_canvas.set_hexpand(True)
        self.game_canvas.set_vexpand(True)
        self.game_canvas.set_draw_func(self.draw_game)
        overlay.add_overlay(self.game_canvas)

        hud = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        hud.set_margin_start(24)
        hud.set_margin_end(24)
        hud.set_margin_top(18)
        hud.set_margin_bottom(18)
        hud.set_can_target(False)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=28)
        self.score_label = self.stat_block(top, "SCORE")
        self.combo_label = self.stat_block(top, "COMBO")
        self.accuracy_label = self.stat_block(top, "ACCURACY")
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        top.append(spacer)
        self.offset_label = Gtk.Label(label="OFFSET  +0 ms")
        self.offset_label.add_css_class("hint")
        top.append(self.offset_label)

        middle = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        middle.set_vexpand(True)
        middle.set_valign(Gtk.Align.CENTER)
        self.judgement_label = Gtk.Label()
        self.judgement_label.add_css_class("judgement")
        middle.append(self.judgement_label)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bottom.set_halign(Gtk.Align.CENTER)
        self.track_game_label = Gtk.Label()
        self.track_game_label.add_css_class("hint")
        bottom.append(self.track_game_label)

        hud.append(top)
        hud.append(middle)
        hud.append(bottom)
        overlay.add_overlay(hud)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        controls.set_halign(Gtk.Align.END)
        controls.set_valign(Gtk.Align.END)
        controls.set_margin_end(22)
        controls.set_margin_bottom(62)
        self.pause_button = Gtk.Button(label="Pause")
        self.pause_button.add_css_class("secondary-button")
        self.pause_button.connect("clicked", lambda _button: self.toggle_pause())
        back_button = Gtk.Button(label="Choose Another Track")
        back_button.add_css_class("secondary-button")
        back_button.connect("clicked", lambda _button: self.back_to_setup())
        controls.append(self.pause_button)
        controls.append(back_button)
        overlay.add_overlay(controls)

        self.result_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.result_card.add_css_class("card")
        self.result_card.set_halign(Gtk.Align.CENTER)
        self.result_card.set_valign(Gtk.Align.CENTER)
        self.result_card.set_visible(False)
        result_title = Gtk.Label(label="TRACK COMPLETE")
        result_title.add_css_class("hero")
        self.result_label = Gtk.Label()
        replay = Gtk.Button(label="Play Again")
        replay.add_css_class("accent-button")
        replay.connect("clicked", lambda _button: self.start_game())
        choose = Gtk.Button(label="Choose Another Track")
        choose.add_css_class("secondary-button")
        choose.connect("clicked", lambda _button: self.back_to_setup())
        self.result_card.append(result_title)
        self.result_card.append(self.result_label)
        self.result_card.append(replay)
        self.result_card.append(choose)
        overlay.add_overlay(self.result_card)
        return overlay

    @staticmethod
    def stat_block(parent: Gtk.Box, name: str) -> Gtk.Label:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        label = Gtk.Label(label="0", xalign=0)
        label.add_css_class("stat")
        caption = Gtk.Label(label=name, xalign=0)
        caption.add_css_class("stat-label")
        box.append(label)
        box.append(caption)
        parent.append(box)
        return label

    def load_track(self) -> None:
        if self.loader_active:
            return
        try:
            url = validate_video_url(self.url_entry.get_text())
        except ValueError as error:
            self.show_load_error(str(error))
            return
        self.current_url = url
        self.loader_active = True
        self.load_button.set_sensitive(False)
        self.url_entry.set_sensitive(False)
        self.ready_box.set_visible(False)
        self.progress.set_fraction(0.02)
        self.progress.set_visible(True)
        self.status_label.remove_css_class("error")
        self.status_label.set_text("Connecting…")
        self.loader_cancel_event = threading.Event()
        worker = TrackLoader(
            url,
            self.set_load_status,
            self.set_load_progress,
            self.track_ready,
            self.show_load_error,
            self.loader_cancel_event,
        )
        threading.Thread(target=worker.run, name="track-loader", daemon=True).start()

    def set_load_status(self, text: str) -> bool:
        self.status_label.set_text(text)
        return GLib.SOURCE_REMOVE

    def set_load_progress(self, value: float) -> bool:
        self.progress.set_fraction(value)
        return GLib.SOURCE_REMOVE

    def show_load_error(self, message: str) -> bool:
        self.loader_active = False
        self.load_button.set_sensitive(True)
        self.url_entry.set_sensitive(True)
        self.progress.set_visible(False)
        self.status_label.add_css_class("error")
        self.status_label.set_text(sanitize_external_text(message, "The operation failed.", MAX_UI_ERROR_LENGTH))
        return GLib.SOURCE_REMOVE

    def track_ready(
        self,
        media_path: Path,
        beats: list[float],
        notes: list[dict],
        title: str,
        artist: str,
        duration: float,
    ) -> bool:
        self.loader_active = False
        self.load_button.set_sensitive(True)
        self.url_entry.set_sensitive(True)
        self.progress.set_fraction(1.0)
        self.status_label.remove_css_class("error")
        self.status_label.set_text(f"Ready — {len(notes)} playable blocks across {int(duration // 60)}:{int(duration % 60):02d}.")
        self.media_path = Path(media_path)
        self.beats = beats
        self.notes = notes
        self.title_text = sanitize_external_text(title, "Untitled track", MAX_TITLE_LENGTH)
        self.artist_text = sanitize_external_text(artist, "Unknown artist", MAX_ARTIST_LENGTH)
        self.current_duration = duration
        self.track_label.set_text(f"{self.title_text}  ·  {self.artist_text}")
        self.track_game_label.set_text(f"{self.title_text}  —  {self.artist_text}")
        self.ready_box.set_visible(True)
        return GLib.SOURCE_REMOVE

    def start_game(self) -> None:
        if not self.media_path or not self.notes:
            return
        qml = shutil.which("qml")
        if qml is None and Path("/usr/lib/qt6/bin/qml").is_file():
            qml = "/usr/lib/qt6/bin/qml"
        if qml is None:
            self.show_load_error("The Qt QML runtime is missing. Install qt6-declarative.")
            return
        qml_game = Path(__file__).with_name("Game.qml")
        if not qml_game.is_file():
            self.show_load_error("Game.qml is missing from this Rhythm Forge installation.")
            return

        environment = os.environ.copy()
        environment["QT_MEDIA_BACKEND"] = "ffmpeg"
        # This machine exposes CUDA decoding even though its GPU cannot decode
        # AV1. Qt otherwise retries that unusable path forever instead of
        # falling back to libdav1d. An empty priority list forces reliable
        # software decoding for every supported Linux system.
        environment["QT_FFMPEG_DECODING_HW_DEVICE_TYPES"] = ","
        log_path = cache_root() / "game.log"
        timing_path = cache_root() / "timing.ini"
        note_payload = json.dumps(self.notes, separators=(",", ":"))
        try:
            with log_path.open("ab") as log_stream:
                self.game_process = subprocess.Popen(
                    [
                        qml,
                        str(qml_game),
                        "--",
                        self.media_path.resolve().as_uri(),
                        note_payload,
                        self.title_text,
                        self.artist_text,
                        safe_component(self.media_path.parent.name),
                        timing_path.resolve().as_uri(),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=log_stream,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    start_new_session=True,
                )
        except OSError as error:
            self.show_load_error(f"The game window could not start: {error}")
            return

        self.history_recorded = False
        self.record_recent_track()
        application = self.get_application()
        if application:
            application.hold()
        self.set_visible(False)
        GLib.timeout_add(200, self.watch_game_process)

    def watch_game_process(self) -> bool:
        if self.game_process is not None and self.game_process.poll() is None:
            return GLib.SOURCE_CONTINUE
        self.game_process = None
        self.refresh_recent_tracks()
        self.refresh_progression_summary()
        self.set_visible(True)
        self.present()
        application = self.get_application()
        if application:
            application.release()
        return GLib.SOURCE_REMOVE

    def on_media_prepared(self, media: Gtk.MediaFile, _property) -> None:
        if media is not self.media or not self.awaiting_playback:
            return
        if media.get_error() is not None:
            self.on_media_error(media, None)
            return
        if not media.has_audio() and not media.has_video():
            return
        self.awaiting_playback = False
        self.playing = True
        self.last_judgement = "GET READY"
        self.last_judgement_time = time.monotonic()
        media.seek(0)
        media.play()
        self.record_recent_track()
        self.update_hud()

    def on_media_error(self, media: Gtk.MediaFile, _property) -> None:
        if media is not self.media:
            return
        error = media.get_error()
        if error is None:
            return
        self.awaiting_playback = False
        self.playing = False
        self.last_judgement = "PLAYBACK ERROR"
        self.result_label.set_text(
            "The video could not be played.\n\n"
            f"{error.message}\n\n"
            "Install gst-plugins-good and gst-libav, then try again."
        )
        self.result_card.set_visible(True)
        self.update_hud()

    def check_playback_start(self, generation: int) -> bool:
        if generation != self.media_generation or not self.awaiting_playback:
            return GLib.SOURCE_REMOVE
        if self.media and self.media.get_error() is not None:
            self.on_media_error(self.media, None)
        else:
            self.awaiting_playback = False
            self.playing = False
            self.last_judgement = "PLAYBACK ERROR"
            self.result_label.set_text(
                "The media player did not become ready.\n\n"
                "Install gst-plugins-good and gst-libav, then try again."
            )
            self.result_card.set_visible(True)
            self.update_hud()
        return GLib.SOURCE_REMOVE

    def current_time(self) -> float:
        if not self.media:
            return 0.0
        return max(0.0, self.media.get_timestamp() / 1_000_000.0 + self.input_offset_ms / 1000.0)

    def hit(self) -> None:
        now = self.current_time()
        found = nearest_playable_beat(self.beats, self.next_beat, now)
        if found is None:
            self.score.register(None)
            self.last_judgement = "MISS"
        else:
            index, delta_ms = found
            while self.next_beat < index:
                self.score.register(None)
                self.next_beat += 1
            judgement = judge_timing(delta_ms)
            self.score.register(judgement)
            self.next_beat = index + 1
            self.last_judgement = judgement.label if judgement else "MISS"
        self.flash_strength = 1.0
        self.last_judgement_time = time.monotonic()
        self.update_hud()

    def mark_late_misses(self) -> None:
        now = self.current_time()
        limit = now - HIT_WINDOW_MS / 1000.0
        missed = False
        while self.next_beat < len(self.beats) and self.beats[self.next_beat] < limit:
            self.score.register(None)
            self.next_beat += 1
            missed = True
        if missed:
            self.last_judgement = "MISS"
            self.last_judgement_time = time.monotonic()
            self.update_hud()

    def update_hud(self) -> None:
        self.score_label.set_text(f"{self.score.score:,}")
        self.combo_label.set_text(str(self.score.combo))
        self.accuracy_label.set_text(f"{self.score.accuracy:.1f}%")
        self.offset_label.set_text(f"OFFSET  {self.input_offset_ms:+d} ms")
        self.judgement_label.set_text(self.last_judgement)
        if self.last_judgement == "PERFECT":
            self.judgement_label.set_markup("<span foreground='#ad9cff'>PERFECT</span>")
        elif self.last_judgement == "GREAT":
            self.judgement_label.set_markup("<span foreground='#70edc2'>GREAT</span>")
        elif self.last_judgement == "GOOD":
            self.judgement_label.set_markup("<span foreground='#f5d875'>GOOD</span>")
        elif self.last_judgement == "MISS":
            self.judgement_label.set_markup("<span foreground='#ff718d'>MISS</span>")

    def toggle_pause(self) -> None:
        if not self.playing or not self.media or self.finished:
            return
        if self.paused:
            self.media.play()
            self.paused = False
            self.pause_button.set_label("Pause")
            self.last_judgement = ""
        else:
            self.media.pause()
            self.paused = True
            self.pause_button.set_label("Resume")
            self.last_judgement = "PAUSED"
        self.last_judgement_time = time.monotonic()
        self.update_hud()

    def adjust_offset(self, amount: int) -> None:
        self.input_offset_ms = max(-250, min(250, self.input_offset_ms + amount))
        self.update_hud()

    def back_to_setup(self) -> None:
        if self.media:
            self.media.pause()
        self.playing = False
        self.awaiting_playback = False
        self.paused = False
        self.refresh_recent_tracks()
        self.stack.set_visible_child_name("setup")

    def finish_game(self) -> None:
        if self.finished:
            return
        while self.next_beat < len(self.beats):
            self.score.register(None)
            self.next_beat += 1
        self.finished = True
        self.playing = False
        self.result_label.set_text(
            f"Score  {self.score.score:,}\n"
            f"Accuracy  {self.score.accuracy:.1f}%\n"
            f"Max combo  {self.score.max_combo}"
        )
        self.result_card.set_visible(True)
        self.update_hud()

    def on_key_pressed(self, _controller, keyval: int, _keycode: int, _state: Gdk.ModifierType) -> bool:
        if self.stack.get_visible_child_name() != "game":
            return False
        if keyval in (Gdk.KEY_space, Gdk.KEY_w, Gdk.KEY_W, Gdk.KEY_Up) and self.playing and not self.paused:
            self.hit()
            return True
        if keyval in (Gdk.KEY_p, Gdk.KEY_P, Gdk.KEY_Escape):
            self.toggle_pause()
            return True
        if keyval == Gdk.KEY_bracketleft:
            self.adjust_offset(-10)
            return True
        if keyval == Gdk.KEY_bracketright:
            self.adjust_offset(10)
            return True
        return False

    def tick(self) -> bool:
        if self.playing and not self.paused and self.media:
            self.mark_late_misses()
            if self.media.get_ended():
                self.finish_game()
            self.flash_strength *= 0.86
            if time.monotonic() - self.last_judgement_time > 0.65:
                self.judgement_label.set_text("")
            self.game_canvas.queue_draw()
        return GLib.SOURCE_CONTINUE

    def draw_game(self, _area: Gtk.DrawingArea, context, width: int, height: int) -> None:
        now = self.current_time()
        lane_width = max(150.0, min(260.0, width * 0.22))
        center_x = width / 2.0
        target_y = height * 0.78
        spawn_y = 42.0
        approach = 1.7

        context.set_source_rgba(0.03, 0.04, 0.09, 0.48)
        context.rectangle(center_x - lane_width / 2, 0, lane_width, height)
        context.fill()

        context.set_source_rgba(0.55, 0.42, 1.0, 0.24 + self.flash_strength * 0.3)
        context.rectangle(center_x - lane_width / 2, target_y - 8, lane_width, 16)
        context.fill()
        context.set_source_rgba(0.86, 0.82, 1.0, 0.95)
        context.set_line_width(3.0)
        context.move_to(center_x - lane_width / 2, target_y)
        context.line_to(center_x + lane_width / 2, target_y)
        context.stroke()

        for index in range(self.next_beat, len(self.beats)):
            remaining = self.beats[index] - now
            if remaining > approach:
                break
            if remaining < -HIT_WINDOW_MS / 1000.0:
                continue
            progress = 1.0 - max(0.0, remaining) / approach
            y = spawn_y + (target_y - spawn_y) * progress
            note_width = lane_width * 0.78
            note_height = 14.0
            glow = max(0.0, 1.0 - abs(remaining) / 0.20)
            context.set_source_rgba(0.60, 0.46, 1.0, 0.30 + glow * 0.35)
            context.rectangle(center_x - note_width / 2 - 7, y - note_height / 2 - 7, note_width + 14, note_height + 14)
            context.fill()
            context.set_source_rgba(0.88, 0.83, 1.0, 1.0)
            context.rectangle(center_x - note_width / 2, y - note_height / 2, note_width, note_height)
            context.fill()

        context.set_source_rgba(1.0, 1.0, 1.0, 0.82)
        context.select_font_face("Sans", 0, 1)
        context.set_font_size(17)
        text = "SPACE  /  W  /  ↑"
        extents = context.text_extents(text)
        context.move_to(center_x - extents.width / 2, target_y + 48)
        context.show_text(text)

    def on_close_request(self, _window) -> bool:
        self.loader_cancel_event.set()
        if self.game_process is not None:
            terminate_process_group(self.game_process)
            self.game_process = None
        if self.media:
            self.media.pause()
        return False


class RhythmForgeApplication(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window: RhythmForgeWindow | None = None

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self) -> None:
        if self.window is None:
            self.window = RhythmForgeWindow(self)
        self.window.present()


def main() -> int:
    return RhythmForgeApplication().run(None)


if __name__ == "__main__":
    raise SystemExit(main())
