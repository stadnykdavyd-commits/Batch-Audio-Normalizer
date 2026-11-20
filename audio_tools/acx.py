"""ACX (Audible) audiobook submission checks."""

from __future__ import annotations

from dataclasses import dataclass, field

from .analyze import Levels

ACX_RMS_MIN = -23.0
ACX_RMS_MAX = -18.0
ACX_PEAK_MAX = -3.0
ACX_NOISE_MAX = -60.0


@dataclass
class AcxResult:
    passed: bool
    problems: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "PASS" if self.passed else "FAIL"


def check(levels: Levels, sample_rate: int | None = None) -> AcxResult:
    problems: list[str] = []
    if not (ACX_RMS_MIN <= levels.rms_db <= ACX_RMS_MAX):
        problems.append(f"RMS {levels.rms_db:.1f} dB (need {ACX_RMS_MIN:.0f}..{ACX_RMS_MAX:.0f})")
    if levels.peak_db > ACX_PEAK_MAX:
        problems.append(f"peak {levels.peak_db:.1f} dB (need <= {ACX_PEAK_MAX:.0f})")
    if levels.noise_floor_db > ACX_NOISE_MAX:
        problems.append(f"noise floor {levels.noise_floor_db:.1f} dB (need <= {ACX_NOISE_MAX:.0f})")
    if sample_rate and sample_rate != 44100:
        problems.append(f"sample rate {sample_rate} Hz (ACX wants 44100)")
    return AcxResult(passed=not problems, problems=problems)
