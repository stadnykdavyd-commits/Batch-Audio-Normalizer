"""Small helpers around the ffmpeg / ffprobe command-line tools."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".flac", ".aif", ".aiff", ".m4a", ".aac", ".ogg", ".opus", ".wma",
}


class FFmpegError(RuntimeError):
    """Raised when ffmpeg / ffprobe fails or is missing."""


def require_tools() -> None:
    """Make sure ffmpeg and ffprobe are installed and on PATH."""
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        raise FFmpegError(
            f"Not found on PATH: {', '.join(missing)}. "
            "Install FFmpeg (Windows: `winget install ffmpeg`, macOS: `brew install ffmpeg`, "
            "Linux: `sudo apt install ffmpeg`) and open a new terminal."
        )


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a command and return the completed process (stderr captured as text)."""
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        lines = proc.stderr.strip().splitlines()
        reason = lines[-1].split(": ", 1)[-1] if lines else f"exit code {proc.returncode}"
        raise FFmpegError(f"{cmd[0]}: {reason} (unreadable or not an audio file?)")
    return proc


def probe(path: Path) -> dict:
    """Return basic stream info: sample_rate, channels, duration (seconds), codec."""
    proc = run([
        "ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels,codec_name:format=duration",
        "-of", "json", str(path),
    ])
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    if not streams:
        raise FFmpegError(f"No audio stream in {path.name}")
    s = streams[0]
    duration = data.get("format", {}).get("duration")
    return {
        "sample_rate": int(s.get("sample_rate", 0) or 0),
        "channels": int(s.get("channels", 0) or 0),
        "codec": s.get("codec_name", ""),
        "duration": float(duration) if duration not in (None, "N/A") else 0.0,
    }


_JSON_BLOCK = re.compile(r"\{[^{}]*\}", re.S)


def last_json_block(text: str) -> dict:
    """ffmpeg's loudnorm filter prints a JSON block at the end of stderr — extract it."""
    blocks = _JSON_BLOCK.findall(text)
    if not blocks:
        raise FFmpegError("Could not find loudnorm measurement in ffmpeg output")
    return json.loads(blocks[-1])


def find_audio_files(folder: Path, recursive: bool) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        p for p in folder.glob(pattern)
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )
