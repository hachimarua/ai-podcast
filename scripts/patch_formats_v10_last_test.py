"""Patch the last stale v9 editorial assertion in the broad regression suite."""
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "tests" / "test_episode_formats.py"
text = path.read_text(encoding="utf-8")
replacements = {
    "def test_lab_uses_one_official_theme_without_forced_steps_or_sections(self):":
        "def test_weekly_allows_multiple_topics_without_forced_steps_or_sections(self):",
    'self.assertIn("章立てやチェックリスト", instruction)':
        'self.assertIn("実装テーマに限定しない", instruction)',
}
for old, new in replacements.items():
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one occurrence, found {count}: {old!r}")
    text = text.replace(old, new)
path.write_text(text, encoding="utf-8")
print("last stale v9 assertion updated")
