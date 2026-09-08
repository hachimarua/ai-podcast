import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import audio_quality
import episode_formats


class FormatsV10ConfigTests(unittest.TestCase):
    def test_formats_v10_has_explicit_targets_and_hard_duration_caps(self):
        config = episode_formats.load_episode_formats()
        self.assertEqual(config.config_version, "formats-v10")

        daily = config.formats["daily"].audio_thresholds
        self.assertEqual(
            (
                daily.min_duration_seconds,
                daily.target_duration_seconds,
                daily.max_duration_seconds,
                daily.hard_max_duration_seconds,
            ),
            (180.0, 240.0, 360.0, 600.0),
        )

        weekly = config.formats["lab"].audio_thresholds
        self.assertEqual(
            (
                weekly.min_duration_seconds,
                weekly.target_duration_seconds,
                weekly.max_duration_seconds,
                weekly.hard_max_duration_seconds,
            ),
            (210.0, 480.0, 600.0, 1200.0),
        )


class AsymmetricDurationGateTests(unittest.TestCase):
    def inspect_at(self, duration, thresholds=None):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "episode.mp3"
            audio.write_bytes(b"synthetic-audio")
            with (
                patch.object(audio_quality, "_probe_duration", return_value=duration),
                patch.object(audio_quality, "_volume_metrics", return_value=(-18.0, -1.0)),
                patch.object(audio_quality, "_long_silence_seconds", return_value=0.0),
            ):
                return audio_quality.inspect_audio(audio, thresholds)

    def test_daily_long_episode_is_warning_not_failure(self):
        thresholds = episode_formats.load_episode_formats().formats["daily"].audio_thresholds.to_runtime()
        result = self.inspect_at(420.0, thresholds)
        self.assertTrue(result["passed"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["warnings"], ["duration_long_warning"])
        self.assertTrue(result["long_duration_warning"])
        self.assertEqual(result["target_duration_seconds"], 240.0)
        self.assertEqual(result["duration_headroom_seconds"], 240.0)

    def test_daily_extreme_long_episode_still_fails(self):
        thresholds = episode_formats.load_episode_formats().formats["daily"].audio_thresholds.to_runtime()
        result = self.inspect_at(601.0, thresholds)
        self.assertFalse(result["passed"])
        self.assertIn("duration_too_long", result["issues"])
        self.assertEqual(result["warnings"], [])

    def test_daily_short_episode_remains_hard_failure(self):
        thresholds = episode_formats.load_episode_formats().formats["daily"].audio_thresholds.to_runtime()
        result = self.inspect_at(179.0, thresholds)
        self.assertFalse(result["passed"])
        self.assertIn("duration_too_short", result["issues"])

    def test_weekly_ordinary_long_episode_is_warning_not_failure(self):
        thresholds = episode_formats.load_episode_formats().formats["lab"].audio_thresholds.to_runtime()
        result = self.inspect_at(720.0, thresholds)
        self.assertTrue(result["passed"])
        self.assertEqual(result["warnings"], ["duration_long_warning"])
        self.assertEqual(result["target_duration_seconds"], 480.0)


if __name__ == "__main__":
    unittest.main()
