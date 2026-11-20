# Batch Audio Normalizer

Measure and normalize a whole folder of audio files to a loudness standard — Spotify, YouTube, podcasts, broadcast or audiobooks (ACX / Audible) — and get a CSV report with before/after values.

Built on FFmpeg's two-pass EBU R128 `loudnorm` filter. Pure Python standard library, no paid dependencies.

## Features

- **Loudness analysis** — integrated loudness (LUFS), true peak (dBTP), loudness range (LRA), RMS, sample peak and noise floor
- **Two-pass normalization** — first pass measures, second pass applies an exact *linear* gain (no pumping, typically within ±0.5 LU of target). If the target can't be reached without passing the true-peak ceiling, the report says so.
- **Platform presets** — Spotify / YouTube (−14 LUFS), Apple (−16), podcast stereo (−16) / mono (−19), EBU R128 broadcast (−23), audiobook (−20 LUFS / −3.5 dBTP), or any custom target
- **ACX audiobook check** — PASS / FAIL per chapter with the exact reason (RMS −23…−18 dB, peak ≤ −3 dB, noise floor ≤ −60 dB, 44.1 kHz)
- **Batch-friendly** — folders and subfolders, parallel processing, broken files are reported and skipped, originals are never overwritten
- **Output formats** — WAV (16/24/32-bit), FLAC, MP3 (any bitrate), optional resampling and mono downmix
- **CSV report** — opens directly in Excel

## Requirements

- Python 3.10+
- FFmpeg on PATH
  - Windows: `winget install ffmpeg`
  - macOS: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg`

### Windows: one-click install

Double-click **`Установить.bat`** (Install). It installs Python and FFmpeg via `winget` if missing, runs the tests and creates an **Audio Normalizer** shortcut on the desktop. Drag a folder onto the shortcut (or double-click it to pick one) and choose a preset from the menu — the output folder opens automatically.

## Usage

```bash
# Normalize a podcast folder to -16 LUFS and export MP3
python normalize.py ./podcast_raw --preset podcast --format mp3

# Custom target for music masters
python normalize.py ./tracks --lufs -12 --tp -0.5 --format wav --bits 24

# Only check audiobook chapters against ACX rules (no files written)
python normalize.py ./audiobook --analyze --acx-check

# Prepare audiobook chapters for ACX: 192 kbps MP3, 44.1 kHz, mono
python normalize.py ./audiobook --preset acx --format mp3 --mp3-bitrate 192k --sr 44100 --mono --acx-check
```

Results go to `<input>/normalized/` (or `--out`), together with `report.csv`.

Run `python normalize.py --help` for all options.

## Example output

```
Normalizing to -20 LUFS / -3.5 dBTP -> MP3: 4 file(s), 2 worker(s)
[1/4] OK    Chapter 01.wav: -41.4 LUFS -> -20.3 LUFS  ACX PASS
[2/4] ERROR broken.wav: ffprobe: Invalid data found when processing input
[3/4] OK    Chapter 02.wav: -19.1 LUFS -> -20.4 LUFS  ACX FAIL
...
```

`report.csv`:

| file | in_LUFS | in_TP | out_LUFS | out_TP | out_RMS | out_peak | out_noise_floor | gain_dB | mode | acx_status | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Chapter 01.wav | -41.4 | -27.3 | -20.3 | -6.2 | -20.5 | -6.1 | -73.1 | 21.4 | linear | PASS | |
| Chapter 02.wav | -19.1 | -6.1 | -20.4 | -7.2 | -19.9 | -7.3 | -20.8 | -0.9 | linear | FAIL | noise floor -20.8 dB (need <= -60) |

## How it works

1. `ffprobe` reads sample rate, channels and duration.
2. **Pass 1:** `loudnorm` measures integrated loudness, true peak, LRA and gating threshold.
3. **Pass 2:** `loudnorm` runs again with the measured values and `linear=true`, so the whole file gets one constant gain. Output is resampled back to the source rate (loudnorm works at 192 kHz internally).
4. Level statistics are computed from 50 ms `astats` windows: overall RMS, sample peak, and the noise floor as the quietest 0.5 s stretch (ACX measures room tone between phrases).
5. The output file is measured again, so the report shows the real result, not just the intended one.

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests generate signals with known levels and check that the output lands within ±0.5 LU of the target, that the true-peak ceiling is respected, that steady signals get clean linear gain, and that the RMS / peak / noise-floor measurements match the known values.

## Project structure

```
normalize.py            CLI
audio_tools/
  ffmpeg_utils.py       ffmpeg/ffprobe helpers, file discovery
  analyze.py            loudness + level measurements
  normalize.py          presets and two-pass normalization
  acx.py                ACX rule checks
  report.py             CSV report
tests/                  unittest accuracy tests
```

## Notes

- ACX also requires room tone at the start/end of each chapter and a consistent sound across chapters; this tool checks the measurable numbers, a human still listens.
- If a chapter fails only on noise floor, normalize first, then apply noise reduction (e.g. iZotope RX, Audacity) and re-check with `--analyze --acx-check`.

## License

MIT
