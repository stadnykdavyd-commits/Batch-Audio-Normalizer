"""CSV report writer."""

from __future__ import annotations

import csv
import math
from pathlib import Path

COLUMNS = [
    "file",
    "in_LUFS", "in_TP", "in_LRA", "in_RMS", "in_peak", "in_noise_floor",
    "out_LUFS", "out_TP", "out_RMS", "out_peak", "out_noise_floor",
    "gain_dB", "mode", "acx_status", "notes",
]


def fmt(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        if math.isinf(value):
            return "-inf" if value < 0 else "inf"
        if math.isnan(value):
            return ""
        return f"{value:.1f}"
    return str(value)


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so Excel on Windows opens umlauts / Cyrillic file names correctly
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: fmt(row.get(k)) for k in COLUMNS})
