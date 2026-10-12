import json
import tempfile
import unittest
from pathlib import Path

import idempotency


class TestIdempotency(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manifests_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_manifest(self, filename: str, broadcast_date: str, status: str = "published"):
        manifest_path = self.manifests_dir / filename
        data = {
            "broadcast_date": broadcast_date,
            "publish_status": status,
            "episode_id": filename.replace(".json", ""),
        }
        manifest_path.write_text(json.dumps(data), encoding="utf-8")

    def test_no_manifests_directory(self):
        non_existent = self.manifests_dir / "does_not_exist"
        self.assertFalse(idempotency.is_today_episode_published(non_existent, "2026-08-28"))

    def test_empty_manifests_directory(self):
        self.assertFalse(idempotency.is_today_episode_published(self.manifests_dir, "2026-08-28"))

    def test_published_episode_exists(self):
        self._create_manifest("podcast_20260828_062042.json", "2026-08-28", "published")
        self.assertTrue(idempotency.is_today_episode_published(self.manifests_dir, "2026-08-28"))

    def test_different_date_manifest(self):
        self._create_manifest("podcast_20260827_062233.json", "2026-08-27", "published")
        self.assertFalse(idempotency.is_today_episode_published(self.manifests_dir, "2026-08-28"))

    def test_unpublished_manifest(self):
        self._create_manifest("podcast_20260828_062042.json", "2026-08-28", "failed")
        self.assertFalse(idempotency.is_today_episode_published(self.manifests_dir, "2026-08-28"))

    def test_corrupted_json_file(self):
        corrupted_file = self.manifests_dir / "bad.json"
        corrupted_file.write_text("invalid json", encoding="utf-8")
        self.assertFalse(idempotency.is_today_episode_published(self.manifests_dir, "2026-08-28"))

    def test_cli_output(self):
        self._create_manifest("podcast_20260828_062042.json", "2026-08-28", "published")
        output_file = Path(self.temp_dir.name) / "github_output.txt"
        
        code = idempotency.main([
            "--manifests-dir", str(self.manifests_dir),
            "--date", "2026-08-28",
            "--github-output", str(output_file)
        ])
        self.assertEqual(code, 0)
        content = output_file.read_text(encoding="utf-8")
        self.assertIn("skip=true", content)
        self.assertIn("target_date=2026-08-28", content)

    def test_cli_output_when_not_published(self):
        output_file = Path(self.temp_dir.name) / "github_output.txt"
        
        code = idempotency.main([
            "--manifests-dir", str(self.manifests_dir),
            "--date", "2026-08-28",
            "--github-output", str(output_file)
        ])
        self.assertEqual(code, 0)
        content = output_file.read_text(encoding="utf-8")
        self.assertIn("skip=false", content)
        self.assertIn("target_date=2026-08-28", content)

    def test_published_but_missing_or_empty_mp3(self):
        self._create_manifest("podcast_20260828_062042.json", "2026-08-28", "published")
        episodes_dir = Path(self.temp_dir.name) / "episodes"
        episodes_dir.mkdir()
        # MP3 file does not exist yet -> should return False
        self.assertFalse(idempotency.is_today_episode_published(
            self.manifests_dir, "2026-08-28", episodes_dir=episodes_dir
        ))
        # Empty MP3 file -> should return False
        empty_mp3 = episodes_dir / "podcast_20260828_062042.mp3"
        empty_mp3.write_bytes(b"")
        self.assertFalse(idempotency.is_today_episode_published(
            self.manifests_dir, "2026-08-28", episodes_dir=episodes_dir
        ))
        # Non-empty MP3 file -> should return True
        empty_mp3.write_bytes(b"dummy mp3 data")
        self.assertTrue(idempotency.is_today_episode_published(
            self.manifests_dir, "2026-08-28", episodes_dir=episodes_dir
        ))

    def test_published_with_rss_feed_check(self):
        self._create_manifest("podcast_20260828_062042.json", "2026-08-28", "published")
        episodes_dir = Path(self.temp_dir.name) / "episodes"
        episodes_dir.mkdir()
        (episodes_dir / "podcast_20260828_062042.mp3").write_bytes(b"dummy")
        feed_file = Path(self.temp_dir.name) / "podcast.xml"
        # Feed file does not contain episode_id -> should return False
        feed_file.write_text("<channel><item><title>Old</title></item></channel>", encoding="utf-8")
        self.assertFalse(idempotency.is_today_episode_published(
            self.manifests_dir, "2026-08-28", episodes_dir=episodes_dir, feed_path=feed_file
        ))
        # Feed file contains episode_id -> should return True
        feed_file.write_text("<channel><item><guid>podcast_20260828_062042.mp3</guid></item></channel>", encoding="utf-8")
        self.assertTrue(idempotency.is_today_episode_published(
            self.manifests_dir, "2026-08-28", episodes_dir=episodes_dir, feed_path=feed_file
        ))


if __name__ == "__main__":
    unittest.main()
