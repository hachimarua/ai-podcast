"""Trusted Daily Brief / AI implementation lab format configuration."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from audio_quality import AudioThresholds


FORMATS_PATH = Path(__file__).resolve().parent / "config" / "episode_formats.json"
JST = ZoneInfo("Asia/Tokyo")
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class EpisodeFormatError(ValueError):
    """Raised when format configuration or a requested format is unsafe."""


class AudioThresholdConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_duration_seconds: float = Field(gt=0)
    max_duration_seconds: float = Field(gt=0)
    min_mean_volume_db: float
    max_mean_volume_db: float
    max_peak_volume_db: float
    max_long_silence_ratio: float = Field(ge=0, le=1)
    silence_noise_db: float
    silence_min_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.min_duration_seconds >= self.max_duration_seconds:
            raise ValueError("audio duration minimum must be below maximum")
        if self.min_mean_volume_db >= self.max_mean_volume_db:
            raise ValueError("mean volume minimum must be below maximum")
        return self

    def to_runtime(self) -> AudioThresholds:
        return AudioThresholds(**self.model_dump())


class FormatSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: Literal["Daily Brief", "AI実装ラボ"]
    duration_label: Literal["4〜6分", "8〜12分"]
    prompt_character_min: int = Field(gt=0)
    prompt_character_max: int = Field(gt=0)
    hard_character_min: int = Field(gt=0)
    hard_character_max: int = Field(gt=0)
    max_news_items: int = Field(ge=1, le=4)
    max_review_terms: int = Field(ge=0, le=3)
    speech_rate: Literal["+10%", "0%"]
    audio_thresholds: AudioThresholdConfig

    @model_validator(mode="after")
    def validate_character_ranges(self):
        if self.prompt_character_min >= self.prompt_character_max:
            raise ValueError("prompt character minimum must be below maximum")
        if self.hard_character_min >= self.hard_character_max:
            raise ValueError("hard character minimum must be below maximum")
        if not (
            self.hard_character_min
            <= self.prompt_character_min
            < self.prompt_character_max
            <= self.hard_character_max
        ):
            raise ValueError("prompt character target must fit inside the hard range")
        return self


class WeeklyLabConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    weekday: Literal[tuple(WEEKDAYS)]


class EpisodeFormatsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    config_version: str
    timezone: Literal["Asia/Tokyo"]
    default_format: Literal["daily"]
    weekly_lab: WeeklyLabConfig
    formats: dict[Literal["daily", "lab"], FormatSpec]

    @model_validator(mode="after")
    def validate_closed_formats(self):
        if set(self.formats) != {"daily", "lab"}:
            raise ValueError("formats must contain exactly daily and lab")
        if self.formats["daily"].display_name != "Daily Brief":
            raise ValueError("daily display name is fixed")
        if self.formats["lab"].display_name != "AI実装ラボ":
            raise ValueError("lab display name is fixed")
        daily = self.formats["daily"]
        lab = self.formats["lab"]
        if daily.duration_label != "4〜6分" or (
            daily.audio_thresholds.min_duration_seconds,
            daily.audio_thresholds.max_duration_seconds,
        ) != (240.0, 360.0):
            raise ValueError("daily label and audio thresholds must remain 4-6 minutes")
        if daily.speech_rate != "+10%":
            raise ValueError("daily speech rate is fixed at +10%")
        if lab.duration_label != "8〜12分" or (
            lab.audio_thresholds.min_duration_seconds,
            lab.audio_thresholds.max_duration_seconds,
        ) != (480.0, 720.0):
            raise ValueError("lab label and audio thresholds must remain 8-12 minutes")
        if lab.speech_rate != "0%":
            raise ValueError("lab speech rate is fixed at 0%")
        if not re.fullmatch(r"formats-v[1-9][0-9]*", self.config_version):
            raise ValueError("config_version must use formats-vN")
        return self


def load_episode_formats() -> EpisodeFormatsConfig:
    path = FORMATS_PATH
    if path.is_symlink() or path.parent.is_symlink():
        raise EpisodeFormatError("episode format path must not use symbolic links")
    if not path.is_file():
        raise EpisodeFormatError("episode format config must be a regular committed file")
    try:
        return EpisodeFormatsConfig.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise EpisodeFormatError("episode format config is malformed or unsafe") from exc


def resolve_episode_format(
    config: EpisodeFormatsConfig,
    *,
    now_jst: datetime | None = None,
    override: str | None = None,
    existing_format: str | None = None,
) -> Literal["daily", "lab"]:
    """Resolve once per run, locking to an existing same-day format when present."""

    if existing_format is not None:
        if existing_format not in {"daily", "lab"}:
            raise EpisodeFormatError("existing episode has an unknown format")
        return existing_format

    requested = (override or os.getenv("PODCAST_EPISODE_FORMAT", "auto")).strip().lower()
    if requested not in {"auto", "daily", "lab"}:
        raise EpisodeFormatError("PODCAST_EPISODE_FORMAT must be auto, daily, or lab")
    if requested != "auto":
        return requested

    now_jst = now_jst or datetime.now(JST)
    if now_jst.tzinfo is None:
        raise EpisodeFormatError("format resolution requires a timezone-aware datetime")
    if (
        config.weekly_lab.enabled
        and now_jst.astimezone(JST).weekday() == WEEKDAYS[config.weekly_lab.weekday]
    ):
        return "lab"
    return config.default_format


def count_script_characters(script: str) -> int:
    return len(re.sub(r"\s+", "", script or ""))


def validate_script_length(script: str, spec: FormatSpec) -> dict:
    count = count_script_characters(script)
    result = {
        "passed": spec.hard_character_min <= count <= spec.hard_character_max,
        "character_count": count,
        "hard_min": spec.hard_character_min,
        "hard_max": spec.hard_character_max,
        "target_min": spec.prompt_character_min,
        "target_max": spec.prompt_character_max,
    }
    if not result["passed"]:
        raise EpisodeFormatError(
            f"generated script length {count} is outside "
            f"{spec.hard_character_min}-{spec.hard_character_max}"
        )
    return result
