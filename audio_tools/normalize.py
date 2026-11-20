"""Two-pass EBU R128 loudness normalization with ffmpeg's loudnorm filter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .analyze import Loudness, measure_loudness
from .ffmpeg_utils import last_json_block, run


@dataclass(frozen=True)
class Target:
    lufs: float
    true_peak: float
    lra: float = 11.0
    description: str = ""


PRESETS: dict[str, Target] = {
    "spotify":   Target(-14.0, -1.0, 11.0, "Spotify / streaming"),
    "youtube":   Target(-14.0, -1.0, 11.0, "YouTube"),
    "apple":     Target(-16.0, -1.0, 11.0, "Apple Music / Apple Podcasts"),
    "podcast":   Target(-16.0, -1.0, 11.0, "Podcast, stereo"),
    "podcast-mono": Target(-19.0, -1.0, 11.0, "Podcast, mono"),
    "broadcast": Target(-23.0, -1.0, 15.0, "EBU R128 broadcast"),
    "acx":       Target(-20.0, -3.5, 11.0, "Audiobook (ACX / Audible), check with --acx-check"),
}

FORMATS = ("wav", "flac", "mp3")


@dataclass
class NormalizeResult:
    output: Path
    gain_db: float
    mode: str  # "linear" (clean gain) or "dynamic" (loudnorm had to compress/limit)


def _codec_args(fmt: str, bits: int, mp3_bitrate: str) -> list[str]:
    if fmt == "wav":
        codec = {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_f32le"}[bits]
        return ["-c:a", codec]
    if fmt == "flac":
        return ["-c:a", "flac", "-sample_fmt", "s16" if bits == 16 else "s32"]
    if fmt == "mp3":
        return ["-c:a", "libmp3lame", "-b:a", mp3_bitrate]
    raise ValueError(f"Unsupported format: {fmt}")


def normalize_file(
    src: Path,
    dst: Path,
    target: Target,
    sample_rate: int,
    fmt: str = "wav",
    bits: int = 24,
    mp3_bitrate: str = "320k",
    mono: bool = False,
    measured: Loudness | None = None,
) -> NormalizeResult:
    """Pass 1 measures (unless `measured` is given), pass 2 applies the exact correction."""
    m = measured or measure_loudness(src, target.lufs, target.true_peak, target.lra)
    # ffmpeg treats measured_LRA=0 as "not set" and silently falls back to dynamic mode
    # (happens with perfectly steady signals such as tones) — use a tiny non-zero value.
    measured_lra = max(m.lra, 0.01)

    af = (
        f"loudnorm=I={target.lufs}:TP={target.true_peak}:LRA={target.lra}"
        f":measured_I={m.lufs}:measured_TP={m.true_peak}"
        f":measured_LRA={measured_lra}:measured_thresh={m.threshold}"
        f":offset={m.offset}:linear=true:print_format=json"
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-y", "-i", str(src),
        "-map", "0:a:0", "-af", af,
        # loudnorm works internally at 192 kHz — resample back to the wanted rate.
        "-ar", str(sample_rate),
    ]
    if mono:
        cmd += ["-ac", "1"]
    cmd += _codec_args(fmt, bits, mp3_bitrate)
    cmd += ["-map_metadata", "0", str(dst)]

    proc = run(cmd)
    info = last_json_block(proc.stderr)
    mode = str(info.get("normalization_type", "")).lower() or "unknown"
    return NormalizeResult(output=dst, gain_db=target.lufs - m.lufs, mode=mode)
