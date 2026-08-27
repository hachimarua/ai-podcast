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


if __name__ == "__main__":
    unittest.main()
