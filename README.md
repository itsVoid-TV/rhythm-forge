# Rhythm Forge

![Rhythm Forge preview](preview.png)

Rhythm Forge is an Omarchy bar extension and a one-key Linux rhythm game. Paste a music-video URL, let the game download a local 720p copy and detect its percussive onsets, then press **Space** when each note reaches the timing line.

The interface and all user-facing errors use American English.

## Requirements

- Omarchy 4.0 or newer (Quickshell plugin schema version 1)
- GTK 4 with Python GObject bindings (`gtk4`, `python-gobject`)
- Qt 6 QML and its FFmpeg multimedia backend (`qt6-declarative`, `qt6-multimedia`, `qt6-multimedia-ffmpeg`)
- `yt-dlp`, `ffmpeg`, and `ffprobe`
- A Nerd Font in the Omarchy bar (provided by the standard Omarchy setup)

The standard Omarchy installation provides the Qt playback stack. Rhythm Forge never requests root access and does not run downloaded media as code.

## Test without installing

```bash
./run.sh
```

## Install the Omarchy extension

```bash
omarchy plugin add https://github.com/itsVoid-TV/rhythm-forge.git --enable
```

Omarchy clones and validates the public plugin repository, installs it as `io.github.itsvoid-tv.rhythm-forge`, and enables it in the right bar section. For local development, `./install.sh` installs the current checkout and preserves an existing installation under `${XDG_STATE_HOME:-~/.local/state}/rhythm-forge/plugin-backups/`.

Click the music-note icon in the Omarchy bar to start the game. The extension can also be opened through IPC:

```bash
omarchy-shell shell summon io.github.itsvoid-tv.rhythm-forge
```

## Controls

| Key | Action |
| --- | --- |
| Space, W, or Arrow Up | Hit a tap/SPAM note, or hold and release a HOLD note |
| P or Escape | Pause or resume |
| `[` / `]` | Move notes later / earlier in 10 ms steps |

The setup screen keeps up to five locally cached tracks under **Recently Played**. Selecting one starts it immediately without downloading or analyzing it again.

Timing calibration is stored separately for each track. Use `[` when notes arrive before the sound, or `]` when they arrive after it; the selected correction is restored the next time that song is played.

VSync is enabled by default and can be changed with the toggle in the game toolbar. With VSync on, note movement updates once per rendered frame; with it off, the game uses a 60 Hz timer.

Deliberate rapid tapping is allowed for dense passages. Extra taps between notes are counted for the result screen but do not damage score, combo, or accuracy. Only impossible duplicate events less than 20 ms apart and held-key auto-repeat are filtered.

Four or more tightly packed beats are combined into one readable **SPAM** block; tap Space repeatedly until its minimum counter is full. Every additional physical tap before the SPAM block ends awards bonus points, with no upper tap limit. A sustained tone becomes a **HOLD** block: press Space as its leading edge reaches the timing line, keep it held, and release near the trailing edge. A 3–2–1 countdown now runs after the video is ready, before audio and chart movement begin.

The chart analyzer uses separate percussion and vocal paths. Percussion drives ordinary TAP/SPAM notes, while a voice-band autocorrelation pass detects pitched syllable starts and stable sustained vowels independently of drum spacing. Its pitch tracking treats octave jumps as one continuous phrase, which keeps processed and rap vocals from fragmenting a held vowel. Long vocal phrases replace colliding percussion notes with one playable HOLD block, avoiding impossible one-key hold-and-tap overlaps. Existing cached songs are automatically reanalyzed once when the vocal-aware chart format changes.

## Stars, advancements, and colors

Every completed track receives a rating of up to 10 stars. The rating combines song length with accuracy; ratings below 50% earn no stars. A track awards the difference above its previous best rating, so improving a personal best earns the remaining stars without making replays an unlimited currency farm.

The song-selection screen contains separate **★ Shop** and **Inventory** buttons. Buy regular colors in the Shop, then equip any purchased or event-won color from Inventory. SPAM, HOLD, and timing-line colors can be equipped independently. Every regular color costs 15 stars, while defaults remain free. The expanded catalog includes blue, pink, green, purple, white, red, gold, orange, ice, and other category-specific choices. Lifetime stars, completed songs, event wins, advancement rank, owned colors, and equipped colors persist between sessions.

Before each song, the game independently rolls a 5% chance for a random event. If one appears, the song waits on an event card before the countdown. The card sets a score target of 100,000, 250,000, or 500,000 points according to chart length and previews an exclusive color reward. Winning permanently unlocks that color; event-exclusive colors cannot be bought in the shop.

Timing windows are ±70 ms for Perfect, ±130 ms for Great, and ±200 ms for Good.

## Privacy and storage

Rhythm Forge sends the pasted URL only to `yt-dlp` and the source site needed to retrieve the video. Videos and generated beat maps are cached under `${XDG_CACHE_HOME:-~/.cache}/rhythm-forge/`. No analytics or telemetry are collected.

Only download videos when you have permission to do so and when the source site's terms allow it.

## Development

```bash
./build.sh
```

This runs the unit tests, Python syntax checks, the native `omarchy plugin validate` command, and produces a versioned tarball plus SHA-256 checksum in `dist/`.

## Uninstall

```bash
omarchy plugin remove io.github.itsvoid-tv.rhythm-forge
```

The local-development `./uninstall.sh` path is recoverable: it disables the plugin and moves it into the XDG state backup directory. Cached videos are deliberately left untouched by either removal method.

## License

GPL-3.0-or-later. See `LICENSE`.
