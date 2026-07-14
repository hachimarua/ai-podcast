"""Deterministic, model-free quality checks for generated podcast audio."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioThresholds:
    min_duration_seconds: float = 180.0
    max_duration_seconds: float = 600.0
    min_mean_volume_db: float = -28.0
    max_mean_volume_db: float = -10.0
    max_peak_volume_db: float = -0.1
    max_long_silence_ratio: float = 0.15
    silence_noise_db: float = -45.0
    silence_min_seconds: float = 2.0


class AudioQualityError(RuntimeError):
    """Raised when FFmpeg cannot inspect an audio file."""


def _run(command: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioQualityError(f"Audio inspection command failed: {type(exc).__name__}") from exc


def _probe_duration(path: Path) -> float:
    result = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(path),
    ])
    if result.returncode != 0:
        raise AudioQualityError("ffprobe could not decode the generated audio")
    try:
        payload = json.loads(result.stdout)
        return float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AudioQualityError("ffprobe returned an invalid duration") from exc


def _volume_metrics(path: Path) -> tuple[float, float]:
    result = _run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", "volumedetect", "-f", "null", "-",
    ])
    if result.returncode != 0:
        raise AudioQualityError("ffmpeg could not decode the generated audio")
    mean_match = re.search(r"mean_volume:\s*(-?[\d.]+) dB", result.stderr)
    max_match = re.search(r"max_volume:\s*(-?[\d.]+) dB", result.stderr)
    if not mean_match or not max_match:
        raise AudioQualityError("ffmpeg did not return volume metrics")
    return float(mean_match.group(1)), float(max_match.group(1))


def _long_silence_seconds(path: Path, thresholds: AudioThresholds) -> float:
    result = _run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af",
        f"silencedetect=noise={thresholds.silence_noise_db}dB:d={thresholds.silence_min_seconds}",
        "-f", "null", "-",
    ])
    if result.returncode != 0:
        raise AudioQualityError("ffmpeg silence detection failed")
    durations = re.findall(r"silence_duration:\s*([\d.]+)", result.stderr)
    return sum(float(value) for value in durations)


def inspect_audio(
    audio_path: str | os.PathLike[str], thresholds: AudioThresholds | None = None
) -> dict:
    thresholds = thresholds or AudioThresholds()
    path = Path(audio_path)
    if not path.is_file():
        raise AudioQualityError("Generated audio file does not exist")
    if path.stat().st_size == 0:
        raise AudioQualityError("Generated audio file is empty")

    duration = _probe_duration(path)
    mean_volume, max_volume = _volume_metrics(path)
    silence_seconds = _long_silence_seconds(path, thresholds)
    silence_ratio = silence_seconds / duration if duration > 0 else 1.0

    issues = []
    if duration < thresholds.min_duration_seconds:
        issues.append("duration_too_short")
    if duration > thresholds.max_duration_seconds:
        issues.append("duration_too_long")
    if mean_volume < thresholds.min_mean_volume_db:
        issues.append("mean_volume_too_quiet")
    if mean_volume > thresholds.max_mean_volume_db:
        issues.append("mean_volume_too_loud")
    if max_volume > thresholds.max_peak_volume_db:
        issues.append("peak_too_high")
    if silence_ratio > thresholds.max_long_silence_ratio:
        issues.append("too_much_long_silence")

    return {
        "passed": not issues,
        "issues": issues,
        "duration_seconds": round(duration, 3),
        "mean_volume_db": round(mean_volume, 2),
        "max_volume_db": round(max_volume, 2),
        "long_silence_seconds": round(silence_seconds, 3),
        "long_silence_ratio": round(silence_ratio, 4),
        "file_size_bytes": path.stat().st_size,
        "thresholds": asdict(thresholds),
    }


def require_audio_quality(
    audio_path: str | os.PathLike[str], thresholds: AudioThresholds | None = None
) -> dict:
    result = inspect_audio(audio_path, thresholds)
    if not result["passed"]:
        raise AudioQualityError(
            "Generated audio failed deterministic checks: " + ", ".join(result["issues"])
        )
    return result
