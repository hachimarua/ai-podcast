import json
import tempfile
import unittest
from pathlib import Path

import idempotency


class TestIdempotency(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.manifests_dir = self.base_dir / "manifests"
        self.manifests_dir.mkdir()
        self.episodes_dir = self.base_dir / "episodes"
        self.episodes_dir.mkdir()
        self.feed_file = self.base_dir / "podcast.xml"
        self.feed_file.write_text("<channel></channel>", encoding="utf-8")

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

    def _setup_complete_published_episode(
        self,
        filename: str = "podcast_20260828_062042.json",
        broadcast_date: str = "2026-08-28",
        status: str = "published",
        mp3_content: bytes = b"dummy mp3 data",
        include_in_feed: bool = True,
    ):
        self._create_manifest(filename, broadcast_date, status)
        episode_id = filename.replace(".json", "")
        mp3_path = self.episodes_dir / f"{episode_id}.mp3"
        mp3_path.write_bytes(mp3_content)
        if include_in_feed:
            feed_content = f"<channel><item><guid>{episode_id}.mp3</guid></item></channel>"
            self.feed_file.write_text(feed_content, encoding="utf-8")

    def test_no_manifests_directory(self):
        non_existent = self.base_dir / "does_not_exist"
        self.assertFalse(
            idempotency.is_today_episode_published(
                non_existent, "2026-08-28", episodes_dir=self.episodes_dir, feed_path=self.feed_file
            )
        )

    def test_empty_manifests_directory(self):
        self.assertFalse(
            idempotency.is_today_episode_published(
                self.manifests_dir, "2026-08-28", episodes_dir=self.episodes_dir, feed_path=self.feed_file
            )
        )

    def test_no_episodes_directory(self):
        self._create_manifest("podcast_20260828_062042.json", "2026-08-28", "published")
        non_existent_episodes = self.base_dir / "no_episodes"
        self.assertFalse(
            idempotency.is_today_episode_published(
                self.manifests_dir, "2026-08-28", episodes_dir=non_existent_episodes, feed_path=self.feed_file
            )
        )

    def test_no_feed_file(self):
        self._create_manifest("podcast_20260828_062042.json", "2026-08-28", "published")
        (self.episodes_dir / "podcast_20260828_062042.mp3").write_bytes(b"data")
        non_existent_feed = self.base_dir / "no_podcast.xml"
        self.assertFalse(
            idempotency.is_today_episode_published(
                self.manifests_dir, "2026-08-28", episodes_dir=self.episodes_dir, feed_path=non_existent_feed
            )
        )

    def test_empty_feed_file(self):
        self._setup_complete_published_episode()
        self.feed_file.write_text("", encoding="utf-8")
        self.assertFalse(
            idempotency.is_today_episode_published(
                self.manifests_dir, "2026-08-28", episodes_dir=self.episodes_dir, feed_path=self.feed_file
            )
        )

    def test_complete_published_episode_exists(self):
        self._setup_complete_published_episode()
        self.assertTrue(
            idempotency.is_today_episode_published(
                self.manifests_dir, "2026-08-28", episodes_dir=self.episodes_dir, feed_path=self.feed_file
            )
        )

    def test_different_date_manifest(self):
        self._setup_complete_published_episode(
            filename="podcast_20260827_062233.json", broadcast_date="2026-08-27"
        )
        self.assertFalse(
            idempotency.is_today_episode_published(
                self.manifests_dir, "2026-08-28", episodes_dir=self.episodes_dir, feed_path=self.feed_file
            )
        )

    def test_unpublished_manifest(self):
        self._setup_complete_published_episode(status="failed")
        self.assertFalse(
            idempotency.is_today_episode_published(
                self.manifests_dir, "2026-08-28", episodes_dir=self.episodes_dir, feed_path=self.feed_file
            )
        )

    def test_corrupted_json_file(self):
        corrupted_file = self.manifests_dir / "bad.json"
        corrupted_file.write_text("invalid json", encoding="utf-8")
        self.assertFalse(
            idempotency.is_today_episode_published(
                self.manifests_dir, "2026-08-28", episodes_dir=self.episodes_dir, feed_path=self.feed_file
            )
        )

    def test_missing_mp3(self):
        self._create_manifest("podcast_20260828_062042.json", "2026-08-28", "published")
        self.feed_file.write_text("<channel><item><guid>podcast_20260828_062042.mp3</guid></item></channel>", encoding="utf-8")
        self.assertFalse(
            idempotency.is_today_episode_published(
                self.manifests_dir, "2026-08-28", episodes_dir=self.episodes_dir, feed_path=self.feed_file
            )
        )

    def test_empty_mp3(self):
        self._setup_complete_published_episode(mp3_content=b"")
        self.assertFalse(
            idempotency.is_today_episode_published(
                self.manifests_dir, "2026-08-28", episodes_dir=self.episodes_dir, feed_path=self.feed_file
            )
        )

    def test_missing_from_feed(self):
        self._setup_complete_published_episode(include_in_feed=False)
        self.feed_file.write_text("<channel><item><guid>other_episode.mp3</guid></item></channel>", encoding="utf-8")
        self.assertFalse(
            idempotency.is_today_episode_published(
                self.manifests_dir, "2026-08-28", episodes_dir=self.episodes_dir, feed_path=self.feed_file
            )
        )

    def test_cli_output(self):
        self._setup_complete_published_episode()
        output_file = self.base_dir / "github_output.txt"

        code = idempotency.main([
            "--manifests-dir", str(self.manifests_dir),
            "--episodes-dir", str(self.episodes_dir),
            "--feed-path", str(self.feed_file),
            "--date", "2026-08-28",
            "--github-output", str(output_file),
        ])
        self.assertEqual(code, 0)
        content = output_file.read_text(encoding="utf-8")
        self.assertIn("skip=true", content)
        self.assertIn("target_date=2026-08-28", content)

    def test_cli_output_when_not_published(self):
        output_file = self.base_dir / "github_output.txt"

        code = idempotency.main([
            "--manifests-dir", str(self.manifests_dir),
            "--episodes-dir", str(self.episodes_dir),
            "--feed-path", str(self.feed_file),
            "--date", "2026-08-28",
            "--github-output", str(output_file),
        ])
        self.assertEqual(code, 0)
        content = output_file.read_text(encoding="utf-8")
        self.assertIn("skip=false", content)
        self.assertIn("target_date=2026-08-28", content)


if __name__ == "__main__":
    unittest.main()
