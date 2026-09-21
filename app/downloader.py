"""Bounded YouTube runtime detection and actionable, non-sensitive errors."""

from __future__ import annotations

import re
import shutil
import sys
import threading

from engine import ProcessCancelledError, run_bounded_process


# Upstream EJS requirements: https://github.com/yt-dlp/yt-dlp/wiki/EJS
JS_RUNTIMES = (("deno", (2, 3, 0)), ("node", (22, 0, 0)))
BROWSERS = ("firefox", "chromium", "chrome", "brave", "opera", "vivaldi", "edge")


def find_js_runtime(cancel_event: threading.Event | None = None) -> str | None:
    """Prefer supported Deno, then Node; a binary's presence is insufficient."""
    for name, minimum in JS_RUNTIMES:
        if cancel_event is not None and cancel_event.is_set():
            raise ProcessCancelledError("Loading was cancelled.")
        binary = shutil.which(name)
        if not binary:
            continue
        try:
            code, stdout, _stderr = run_bounded_process(
                [binary, "--version"], timeout=3, stdout_limit=4096,
                stderr_limit=4096, cancel_event=cancel_event,
            )
        except ProcessCancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError):
            continue
        pattern = r"^deno (\d+)\.(\d+)\.(\d+)(?:\s|$)" if name == "deno" else r"^v(\d+)\.(\d+)\.(\d+)(?:\s|$)"
        match = re.match(pattern, stdout.decode("utf-8", "replace"))
        if code == 0 and match and tuple(map(int, match.groups())) >= minimum:
            return f"{name}:{binary}"
    return None


def download_options(browser: str | None = None, *, cancel_event=None) -> list[str]:
    """Use the same explicit options for metadata and media requests."""
    if browser is not None and browser not in BROWSERS:
        raise ValueError("Choose a supported browser from the Browser session menu.")
    # Keep ambient config isolated: it can change output, run hooks or add URLs.
    # EJS comes from the user's package installation, never an automatic fetch.
    options = ["--ignore-config", "--no-remote-components", "--no-playlist",
               "--socket-timeout", "15", "--retries", "3", "--color", "never"]
    runtime = find_js_runtime(cancel_event)
    if runtime:
        options += ["--no-js-runtimes", "--js-runtimes", runtime]
    if browser:
        options += ["--cookies-from-browser", browser]
    return options


def download_error(output: str, fallback: str) -> str:
    """Classify complete diagnostics; never show cookie/token values or URLs."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    errors = [line for line in lines if "ERROR:" in line]
    # The actual failure outranks incidental warnings (e.g. skipped PO formats).
    cause = "\n".join(errors or lines).lower().replace("’", "'")
    context = output.lower()
    if any(part in cause for part in ("cookie database", "failed to decrypt", "could not copy", "keyring", "cookies database")):
        return ("The selected browser session could not be read. Close that browser, "
                "unlock its keyring and try again, or choose No browser session.")
    if any(part in cause for part in ("not a bot", "confirm you're", "confirm you are", "login required", "sign in", "log in", "age-restricted")):
        return ("The video service requires verification or a permitted signed-in session. "
                "Open the video in your browser first, then optionally select that browser "
                "under Browser session and retry. This may not resolve every verification block.")
    if any(part in cause for part in ("private video", "video unavailable", "video is not available", "not available in your country", "not available in your region", "removed", "copyright", "geo restricted", "geo-restricted")):
        return "This video is unavailable or restricted for your account or region. Choose another video."
    if "no such option" in cause or "unrecognized arguments" in cause:
        return "yt-dlp is too old for this loader. Update it through Omarchy's system update and retry."
    if any(part in cause for part in ("429", "too many requests")):
        return "The video service is rate-limiting requests. Wait before retrying; repeated retries can prolong the block."
    if any(part in context for part in ("no supported javascript", "javascript runtime", "challenge solving failed", "signature solving failed", "nsig extraction failed", "yt-dlp-ejs", "ejs:")):
        return ("YouTube's JavaScript challenge could not be solved. Update yt-dlp and "
                "yt-dlp-ejs together through Omarchy, and install Deno 2.3+ or Node.js 22+. "
                "Restart Rhythm Forge and retry.")
    if any(part in context for part in ("po token", "po_token", "proof of origin")):
        return ("YouTube requires a Proof of Origin (PO) token for this request. Update yt-dlp first. "
                "If it persists, see README > YouTube troubleshooting for the upstream provider guide, "
                "or choose another video. Repeated retries alone will not fix it.")
    if any(part in cause for part in ("403", "forbidden")):
        return ("The video service refused the media request (HTTP 403). Update yt-dlp, then try again later "
                "or use another video. A browser session may help when sign-in is required.")
    if "requested format" in cause:
        return "No playable video format was returned. Update yt-dlp and its EJS package, then try another video."
    if any(part in cause for part in ("timed out", "timeout", "unable to download", "name resolution", "network is unreachable")):
        return "The video service could not be reached. Check your connection and retry later."
    # Unknown service output can contain signed URLs, cookies or token values.
    return fallback + " Update yt-dlp and try another video; see README > YouTube troubleshooting."


if __name__ == "__main__":
    if sys.argv[1:] != ["--check-runtime"]:
        raise SystemExit("Usage: downloader.py --check-runtime")
    runtime = find_js_runtime()
    print(runtime or "Install Deno 2.3+ or Node.js 22+ for YouTube downloads.")
    raise SystemExit(0 if runtime else 1)
