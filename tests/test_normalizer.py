"""
Accuracy tests. Generates test signals with ffmpeg, normalizes them and checks the result.
Run:  python -m unittest discover -s tests -v
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from audio_tools import acx  # noqa: E402
from audio_tools.analyze import Levels, measure_levels, measure_loudness  # noqa: E402
from audio_tools.normalize import PRESETS, Target, normalize_file  # noqa: E402

TOLERANCE_LU = 0.5


def make_tone(path: Path, volume_db: float, seconds: float = 6, freq: int = 440, sr: int = 44100):
    """Sine with its PEAK at `volume_db` dBFS (ffmpeg's sine source is 1/8 = -18.06 dBFS)."""
    volume_db = volume_db + 18.0618
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}:sample_rate={sr}",
        "-af", f"volume={volume_db}dB", "-c:a", "pcm_s24le", str(path),
    ], check=True)


def make_speechlike(path: Path, seconds: float = 8):
    """Pink-noise bursts with quiet gaps — closer to speech than a pure sine.
    Gaps are 1 s long (> the 0.5 s noise-floor block) so frame-boundary jitter
    in ffmpeg's volume filter can't leak loud samples into the measured gap."""
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:duration={seconds}:sample_rate=44100:amplitude=0.3",
        "-af", "volume='if(lt(mod(t,3),2),1,0.0003)':eval=frame",
        "-c:a", "pcm_s16le", str(path),
    ], check=True)


@unittest.skipIf(shutil.which("ffmpeg") is None, "ffmpeg not installed")
class NormalizerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _normalize_and_measure(self, src: Path, target: Target, fmt="wav") -> float:
        dst = self.tmp / f"out_{src.stem}.{fmt}"
        normalize_file(src, dst, target, sample_rate=44100, fmt=fmt)
        self.assertTrue(dst.exists())
        return measure_loudness(dst).lufs

    def test_quiet_file_reaches_spotify_target(self):
        src = self.tmp / "quiet.wav"
        make_tone(src, -30)
        out = self._normalize_and_measure(src, PRESETS["spotify"])
        self.assertAlmostEqual(out, -14.0, delta=TOLERANCE_LU)

    def test_steady_tone_uses_clean_linear_gain(self):
        src = self.tmp / "tone.wav"
        make_tone(src, -25)
        res = normalize_file(src, self.tmp / "tone_out.wav", PRESETS["spotify"], sample_rate=44100)
        self.assertEqual(res.mode, "linear")

    def test_loud_file_is_turned_down_for_broadcast(self):
        src = self.tmp / "loud.wav"
        make_tone(src, -6)
        out = self._normalize_and_measure(src, PRESETS["broadcast"])
        self.assertAlmostEqual(out, -23.0, delta=TOLERANCE_LU)

    def test_custom_target_and_mp3_output(self):
        src = self.tmp / "mid.wav"
        make_tone(src, -20)
        out = self._normalize_and_measure(src, Target(-18.0, -2.0), fmt="mp3")
        self.assertAlmostEqual(out, -18.0, delta=TOLERANCE_LU)

    def test_true_peak_ceiling_respected(self):
        src = self.tmp / "speech.wav"
        make_speechlike(src)
        dst = self.tmp / "speech_out.wav"
        normalize_file(src, dst, PRESETS["podcast"], sample_rate=44100)
        self.assertLessEqual(measure_loudness(dst).true_peak, -1.0 + 0.3)

    def test_levels_of_known_sine(self):
        # a full-scale sine has RMS = peak - 3.01 dB
        src = self.tmp / "sine.wav"
        make_tone(src, -10)
        lv = measure_levels(src)
        self.assertAlmostEqual(lv.peak_db, -10.0, delta=0.2)
        self.assertAlmostEqual(lv.rms_db, -13.0, delta=0.3)

    def test_noise_floor_finds_quiet_gaps(self):
        src = self.tmp / "gaps.wav"
        make_speechlike(src)
        lv = measure_levels(src)
        self.assertLess(lv.noise_floor_db, lv.rms_db - 40)


class AcxRuleTests(unittest.TestCase):
    def test_pass(self):
        self.assertTrue(acx.check(Levels(-20.0, -4.0, -65.0), 44100).passed)

    def test_each_rule_fails(self):
        self.assertFalse(acx.check(Levels(-25.0, -4.0, -65.0)).passed)  # too quiet
        self.assertFalse(acx.check(Levels(-20.0, -1.0, -65.0)).passed)  # peak too high
        self.assertFalse(acx.check(Levels(-20.0, -4.0, -50.0)).passed)  # noisy
        self.assertFalse(acx.check(Levels(-20.0, -4.0, -65.0), 48000).passed)  # wrong rate


if __name__ == "__main__":
    unittest.main()
