#!/usr/bin/env python3
"""
Batch Audio Normalizer
======================
Measure and normalize a whole folder of audio files to a loudness standard
(Spotify, YouTube, podcasts, broadcast, audiobooks) and get a CSV report.

Examples
--------
  python normalize.py ./podcast_raw --preset podcast --format mp3
  python normalize.py ./tracks --lufs -12 --tp -0.5 --out ./ready
  python normalize.py ./audiobook --analyze --acx-check
  python normalize.py ./audiobook --preset acx --format mp3 --acx-check
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from audio_tools import __version__
from audio_tools import acx
from audio_tools.analyze import measure_levels, measure_loudness
from audio_tools.ffmpeg_utils import FFmpegError, find_audio_files, probe, require_tools
from audio_tools.normalize import FORMATS, PRESETS, Target, normalize_file
from audio_tools.report import write_csv


def parse_args(argv=None) -> argparse.Namespace:
    preset_help = "\n".join(
        f"  {name:<13} {t.lufs:>5.0f} LUFS, TP {t.true_peak:>4} dBTP  {t.description}"
        for name, t in PRESETS.items()
    )
    p = argparse.ArgumentParser(
        prog="normalize.py",
        description="Batch loudness analysis and normalization (LUFS / True Peak / ACX).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Presets:\n" + preset_help,
    )
    p.add_argument("input", type=Path, help="Folder with audio files (or a single file)")
    p.add_argument("--out", type=Path, help="Output folder (default: <input>/normalized)")
    p.add_argument("--preset", choices=PRESETS.keys(), default="spotify",
                   help="Loudness target preset (default: spotify)")
    p.add_argument("--lufs", type=float, help="Custom integrated loudness target, overrides preset")
    p.add_argument("--tp", type=float, help="Custom true-peak ceiling in dBTP, overrides preset")
    p.add_argument("--analyze", action="store_true",
                   help="Only measure and write the report, do not create new files")
    p.add_argument("--acx-check", action="store_true",
                   help="Check ACX/Audible rules (RMS -23..-18 dB, peak <= -3 dB, noise <= -60 dB)")
    p.add_argument("--format", choices=FORMATS, default="wav", help="Output format (default: wav)")
    p.add_argument("--bits", type=int, choices=(16, 24, 32), default=24,
                   help="Bit depth for wav/flac (default: 24)")
    p.add_argument("--mp3-bitrate", default="320k", help="MP3 bitrate (default: 320k; ACX: 192k)")
    p.add_argument("--sr", type=int, help="Output sample rate (default: same as source)")
    p.add_argument("--mono", action="store_true", help="Downmix to mono")
    p.add_argument("--recursive", "-r", action="store_true", help="Include subfolders")
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // 2),
                   help="Files processed in parallel (default: half of CPU cores)")
    p.add_argument("--report", type=Path, help="CSV report path (default: <out>/report.csv)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


def resolve_target(args) -> Target:
    base = PRESETS[args.preset]
    return Target(
        lufs=args.lufs if args.lufs is not None else base.lufs,
        true_peak=args.tp if args.tp is not None else base.true_peak,
        lra=base.lra,
        description="custom" if (args.lufs is not None or args.tp is not None) else base.description,
    )


def process_one(src: Path, root: Path, out_dir: Path, target: Target, args) -> dict:
    row: dict = {"file": str(src.relative_to(root)) if src != root else src.name}
    notes: list[str] = []
    info = probe(src)

    loud_in = measure_loudness(src, target.lufs, target.true_peak, target.lra)
    row.update(in_LUFS=loud_in.lufs, in_TP=loud_in.true_peak, in_LRA=loud_in.lra)

    if args.acx_check or args.analyze:
        lv = measure_levels(src)
        row.update(in_RMS=lv.rms_db, in_peak=lv.peak_db, in_noise_floor=lv.noise_floor_db)
        if args.analyze and args.acx_check:
            res = acx.check(lv, info["sample_rate"])
            row["acx_status"] = res.status
            notes += res.problems

    if not args.analyze:
        rel = src.relative_to(root) if src != root else Path(src.name)
        dst = (out_dir / rel).with_suffix("." + args.format)
        sr = args.sr or info["sample_rate"] or 44100
        result = normalize_file(
            src, dst, target, sample_rate=sr, fmt=args.format, bits=args.bits,
            mp3_bitrate=args.mp3_bitrate, mono=args.mono, measured=loud_in,
        )
        row.update(gain_dB=result.gain_db, mode=result.mode)
        if result.mode == "dynamic":
            notes.append("true-peak limit reached: loudnorm used dynamic mode (light limiting)")

        loud_out = measure_loudness(dst, target.lufs, target.true_peak, target.lra)
        row.update(out_LUFS=loud_out.lufs, out_TP=loud_out.true_peak)
        lv_out = measure_levels(dst)
        row.update(out_RMS=lv_out.rms_db, out_peak=lv_out.peak_db,
                   out_noise_floor=lv_out.noise_floor_db)
        if args.acx_check:
            res = acx.check(lv_out, sr)
            row["acx_status"] = res.status
            notes += res.problems

    if loud_in.lufs < -70:
        notes.append("file is (almost) silent")
    row["notes"] = "; ".join(notes)
    return row


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        require_tools()
    except FFmpegError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    src = args.input.resolve()
    if not src.exists():
        print(f"ERROR: not found: {src}", file=sys.stderr)
        return 2

    if src.is_file():
        files, root = [src], src.parent
    else:
        files, root = find_audio_files(src, args.recursive), src
    out_dir = (args.out or (root / "normalized")).resolve()
    # never pick up our own output files on a second run
    files = [f for f in files if out_dir not in f.resolve().parents]
    if not files:
        print("No audio files found.", file=sys.stderr)
        return 1

    target = resolve_target(args)
    mode = "Analyzing" if args.analyze else (
        f"Normalizing to {target.lufs:g} LUFS / {target.true_peak:g} dBTP -> {args.format.upper()}"
    )
    print(f"{mode}: {len(files)} file(s), {args.workers} worker(s)")

    rows: list[dict] = []
    failed = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_one, f, root, out_dir, target, args): f for f in files}
        for i, fut in enumerate(as_completed(futures), 1):
            f = futures[fut]
            name = f.name
            try:
                row = fut.result()
                rows.append(row)
                summary = f"{row['in_LUFS']:.1f} LUFS"
                if "out_LUFS" in row:
                    summary += f" -> {row['out_LUFS']:.1f} LUFS"
                if row.get("acx_status"):
                    summary += f"  ACX {row['acx_status']}"
                print(f"[{i}/{len(files)}] OK    {name}: {summary}")
            except Exception as e:  # keep going on broken files
                failed += 1
                rows.append({"file": name, "notes": f"ERROR: {e}".splitlines()[0]})
                print(f"[{i}/{len(files)}] ERROR {name}: {str(e).splitlines()[0]}")

    rows.sort(key=lambda r: r["file"].lower())
    report = args.report or (out_dir / "report.csv")
    write_csv(rows, report)

    print(f"\nDone in {time.time() - t0:.1f}s. {len(files) - failed} ok, {failed} failed.")
    if not args.analyze:
        print(f"Output: {out_dir}")
    print(f"Report: {report}")
    if args.acx_check:
        n_fail = sum(1 for r in rows if r.get("acx_status") == "FAIL")
        print(f"ACX: {len(rows) - n_fail - failed} pass, {n_fail} fail")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
