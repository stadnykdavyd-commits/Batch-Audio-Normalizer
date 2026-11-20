"""Measure loudness (LUFS / true peak / LRA) and level statistics (RMS / peak / noise floor)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict
from pathlib import Path

from .ffmpeg_utils import last_json_block, run

WINDOW_SEC = 0.05          # 50 ms analysis windows for the level statistics
NOISE_BLOCK_SEC = 0.5      # noise floor = quietest 0.5 s stretch (ACX measures room tone)
DIGITAL_SILENCE_DB = -120  # ignore pure digital silence when estimating the noise floor


@dataclass
class Loudness:
    lufs: float           # integrated loudness, LUFS
    true_peak: float      # dBTP
    lra: float            # loudness range, LU
    threshold: float      # gating threshold, LUFS
    offset: float         # loudnorm target offset

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Levels:
    rms_db: float          # overall RMS, dBFS
    peak_db: float         # sample peak, dBFS
    noise_floor_db: float  # quietest 0.5 s stretch, dBFS RMS


def _num(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return float("-inf")
    return v


def measure_loudness(path: Path, target_i=-23.0, target_tp=-1.0, target_lra=11.0) -> Loudness:
    """First loudnorm pass: measures the file (targets only affect the 'offset' value)."""
    proc = run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json",
        "-f", "null", "-",
    ])
    data = last_json_block(proc.stderr)
    return Loudness(
        lufs=_num(data.get("input_i")),
        true_peak=_num(data.get("input_tp")),
        lra=_num(data.get("input_lra")),
        threshold=_num(data.get("input_thresh")),
        offset=_num(data.get("target_offset")),
    )


_RMS_RE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(\S+)")
_PEAK_RE = re.compile(r"lavfi\.astats\.Overall\.Peak_level=(\S+)")


def measure_levels(path: Path) -> Levels:
    """RMS / peak / noise floor from 50 ms windows (one ffmpeg pass, no extra libraries)."""
    sr = 44100
    n = int(sr * WINDOW_SEC)
    af = (
        f"aresample={sr},asetnsamples=n={n}:p=0,"
        "astats=metadata=1:reset=1:measure_perchannel=none,"
        "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level,"
        "ametadata=mode=print:key=lavfi.astats.Overall.Peak_level"
    )
    proc = run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", af, "-f", "null", "-",
    ])
    rms = [_num(x) for x in _RMS_RE.findall(proc.stderr)]
    peaks = [_num(x) for x in _PEAK_RE.findall(proc.stderr)]
    if not rms:
        return Levels(float("-inf"), float("-inf"), float("-inf"))

    # Overall RMS = average power over all windows.
    powers = [10 ** (r / 10) if math.isfinite(r) else 0.0 for r in rms]
    mean_power = sum(powers) / len(powers)
    rms_db = 10 * math.log10(mean_power) if mean_power > 0 else float("-inf")

    peak_db = max(peaks) if peaks else float("-inf")

    # Noise floor: the quietest 0.5 s block that is not pure digital silence.
    per_block = max(1, int(round(NOISE_BLOCK_SEC / WINDOW_SEC)))
    floor = float("inf")
    for i in range(0, max(1, len(powers) - per_block + 1)):
        block = powers[i:i + per_block]
        p = sum(block) / len(block)
        if p <= 0:
            continue
        db = 10 * math.log10(p)
        if db > DIGITAL_SILENCE_DB:
            floor = min(floor, db)
    noise_floor_db = floor if math.isfinite(floor) else float("-inf")

    return Levels(rms_db=rms_db, peak_db=peak_db, noise_floor_db=noise_floor_db)
