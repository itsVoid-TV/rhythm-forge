# Rhythm Forge

![Rhythm Forge preview](preview.png)

Rhythm Forge is an Omarchy bar extension and a one-key Linux rhythm game. Paste a music-video URL, let the game download a local 720p copy and detect its percussive onsets, then press **Space** when each note reaches the timing line.

The interface and all user-facing errors use American English.

## Requirements

- Omarchy 4.0 or newer (Quickshell plugin schema version 1)
- GTK 4 with Python GObject bindings (`gtk4`, `python-gobject`)
- Qt 6 QML and its FFmpeg multimedia backend (`qt6-declarative`, `qt6-multimedia`, `qt6-multimedia-ffmpeg`)
- Current `yt-dlp` with its matching EJS challenge solver (`yt-dlp-ejs` on Arch), `ffmpeg`, and `ffprobe`
- Deno 2.3+ (preferred) or Node.js 22+ for YouTube's JavaScript challenges
- A Nerd Font in the Omarchy bar (provided by the standard Omarchy setup)

Rhythm Forge needs the **Qt 6** QML runtime specifically. It looks for
`/usr/lib/qt6/bin/qml`, then `qml6`, then a `qml` on `PATH` that reports a 6.x
runtime — a system that also has `qt5-declarative` installed keeps the Qt 5
runtime at `/usr/bin/qml`, where it would otherwise shadow Qt 6. Set
`RHYTHM_FORGE_QT6_QML` to point at the runtime directly if Qt 6 lives in a
different prefix.

The standard Omarchy installation provides the Qt playback stack. Rhythm Forge does not run downloaded media as code. Any missing packages are offered through Omarchy's normal package helper only after explicit user action.

## Test without installing

```bash
./run.sh
```

## Install the Omarchy extension

```bash
omarchy plugin add https://github.com/itsVoid-TV/rhythm-forge.git --enable
```

Omarchy clones and validates the public plugin repository, installs it as `io.github.itsvoid-tv.rhythm-forge`, and enables it in the right bar section. For local development, `./install.sh` installs the current checkout and preserves an existing installation under `${XDG_STATE_HOME:-~/.local/state}/rhythm-forge/plugin-backups/`.

The marketplace installation never installs system packages silently. The bar widget checks the required tools and a supported JavaScript runtime before GTK is imported and changes to a warning icon when something is missing. For an Arch-managed yt-dlp it also checks the EJS package. Clicking the warning shows an actionable Omarchy notification; clicking that notification opens the standard floating terminal and runs `omarchy-pkg-add` for the missing packages. The user can inspect and cancel that normal package-manager flow. These local checks do not guarantee that YouTube will accept a request.

Click the music-note icon in the Omarchy bar to start the game. The extension can also be opened through IPC:

```bash
omarchy-shell shell summon io.github.itsvoid-tv.rhythm-forge
```

## YouTube troubleshooting

Version 1.0.15 automatically selects supported Deno or Node.js and passes the
same runtime and session options to both video-information and download requests.
This matters because yt-dlp enables only Deno by default; an installed Node.js
alone was not sufficient in earlier Rhythm Forge versions. YouTube also needs
the matching EJS solver. See the [upstream EJS setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
The [Arch yt-dlp package](https://archlinux.org/packages/extra/any/yt-dlp/)
depends on `yt-dlp-ejs`; update them together through Omarchy's full system
update. Avoid mixing a system yt-dlp with a different pip installation.

If the bar reports a missing runtime, use its normal installation action to add
`deno`. A supported `node` already on `PATH` also satisfies the check. Restart
Rhythm Forge after installing or updating dependencies. No source-code changes
are required.

- **JavaScript / signature challenge:** update yt-dlp and EJS together and check
  for Deno 2.3+ or Node.js 22+. Having the executable installed does not establish
  that the solver version is compatible; request-time failures are reported.
- **Sign in / confirm you are not a bot:** open the video in your browser first.
  If it is playable and you want to use that session, select your browser under
  **Browser session** and retry. The default is **No browser session**. The choice
  lasts only while this app window is open; select **No browser session** to stop
  using it. yt-dlp reads the selected browser's default local profile. Custom or
  Flatpak-only profiles are not selected by this menu. Cookies do not guarantee
  that a verification block will be resolved.
- **Cannot read browser cookies:** close that browser, unlock its keyring if
  needed, or retry without a browser session. Never paste cookies or tokens into
  a public issue.
- **PO token:** this is different from a JavaScript challenge or sign-in.
  Update yt-dlp first; if still needed, follow the
  [upstream PO Token Guide](https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide)
  for a provider compatible with your yt-dlp installation. Existing provider
  plugins in yt-dlp's default plugin directories remain available. Rhythm Forge
  does not install a provider, force an alternate YouTube client, or generate
  tokens. A provider requiring extra configuration may need further integration;
  ordinary yt-dlp configuration files remain intentionally ignored.
- **HTTP 403 / 429:** access was denied or requests were rate-limited. Update
  yt-dlp and wait before retrying; repeated retries do not reliably fix either
  case. Private, removed, region-restricted or inaccessible videos may require
  choosing a different video.

Error messages now distinguish these cases without exposing signed media URLs,
cookie values or tokens. Warnings stay available to the error classifier instead
of being suppressed. A failed download's intermediate audio/video streams are
no longer mistaken for a completed cached track. **Recently Played** still
opens previously completed tracks without contacting YouTube.

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

Four or more tightly packed beats are combined into one readable **SPAM** block. Its segmented meter fills with every tap, and the block displays the required count directly. Extra physical taps before the block ends build an escalating, capped per-tap bonus while remaining unlimited in count. A sustained tone becomes a **HOLD** block: press as its leading edge reaches the timing line, keep the key held while the progress fill and percentage advance, then release near the trailing edge. HOLD ticks award small bonus points throughout the sustain. A 3–2–1 countdown runs after the video is ready, before audio and chart movement begin.

The chart analyzer uses separate percussion and vocal paths. Percussion drives ordinary TAP/SPAM notes, while a voice-band autocorrelation pass detects pitched syllable starts and stable sustained vowels independently of drum spacing. Its pitch tracking treats octave jumps as one continuous phrase, which keeps processed and rap vocals from fragmenting a held vowel. Long vocal phrases replace colliding percussion notes with one playable HOLD block, avoiding impossible one-key hold-and-tap overlaps. Existing cached songs are automatically reanalyzed once when the vocal-aware chart format changes.

## Stars, advancements, and styles

Every completed track receives a rating of up to 10 stars. The rating combines song length with accuracy; ratings below 50% earn no stars. A track awards the difference above its previous best rating, so improving a personal best earns the remaining stars without making replays an unlimited currency farm.

The song-selection screen contains separate **★ Shop** and **Inventory** buttons. Buy regular styles in the Shop, then equip any purchased or event-won style from Inventory. SPAM, HOLD, timing-line colors, and video-overlay background themes can be equipped independently. Every regular style costs 15 stars, while defaults remain free. The expanded catalog includes cyan, lime, gold, pink, purple, white, red, orange, and other category-specific choices. Background themes tint the video with a restrained gradient and grid without hiding it, preserving the original Rhythm Forge playfield. Lifetime stars, completed songs, event wins, advancement rank, owned styles, and equipped styles persist between sessions.

Before each song, the game independently rolls a 5% chance for a random event. If one appears, the song waits on an event card before the countdown. The card sets a score target of 100,000, 250,000, or 500,000 points according to chart length and previews an exclusive color or background reward. Winning permanently unlocks that style; event-exclusive styles cannot be bought in the shop.

Timing windows are ±70 ms for Perfect, ±130 ms for Great, and ±200 ms for Good.

## Privacy and storage

Rhythm Forge passes the pasted URL to local `yt-dlp`, which contacts the source site and its media services. Videos and generated beat maps are cached under `${XDG_CACHE_HOME:-~/.cache}/rhythm-forge/`. No analytics or telemetry are collected.

Browser cookies are read only when you explicitly select a browser in the setup
screen. yt-dlp then uses that browser's cookies for the matching source-site
requests. Rhythm Forge does not export a cookie file or save the browser choice.
It keeps `--ignore-config` for ambient yt-dlp configurations and disables
automatic remote EJS component downloads. Locally installed yt-dlp plugins still
run according to yt-dlp's plugin discovery rules and may make their own requests.

Only download videos when you have permission to do so and when the source site's terms allow it.

## Runtime safety

- Every `yt-dlp`, `ffprobe`, and analysis `ffmpeg` process runs in its own process group with an absolute deadline. Timeout, cancellation, output-limit, and parser failures terminate the complete group and reap its leader.
- Metadata, logs, individual output lines, FFmpeg diagnostics, decoded PCM, and media duration all have explicit ceilings. The duration read from the downloaded file must be finite, positive, and no longer than 20 minutes even when remote metadata claimed otherwise.
- Percussion PCM is reduced into feature frames while it streams. Voice PCM is streamed into a size-limited temporary file and analyzed in two bounded passes, so neither FFmpeg pipe is accumulated without a limit in memory.
- Remote title, artist, and decoder-error text is normalized and length-limited before storage or command-line use. QML renders those values explicitly as `Text.PlainText`.

## Development

```bash
./build.sh
```

This runs the unit tests, Python and shell syntax checks, the native `omarchy plugin validate` command, and produces a versioned tarball plus SHA-256 checksum in `dist/`.

For regression tests without Omarchy, run `python3 -m unittest discover -s tests -v`.
GitHub Actions additionally runs the real GTK setup-screen smoke tests under Xvfb
and ShellCheck. GTK smoke tests skip locally when GTK or a display is unavailable.
The suite exercises fake video services and does not claim a live YouTube download
or native Omarchy/Wayland gameplay acceptance.

## Uninstall

```bash
omarchy plugin remove io.github.itsvoid-tv.rhythm-forge
```

The local-development `./uninstall.sh` path is recoverable: it disables the plugin and moves it into the XDG state backup directory. Cached videos are deliberately left untouched by either removal method.

## License

GPL-3.0-or-later. See `LICENSE`.
