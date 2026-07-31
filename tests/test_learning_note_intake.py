import importlib.util
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import obsidian_inbox_adapter
import process_inbox

_SPEC = importlib.util.spec_from_file_location(
    "save_learning_note", Path(__file__).resolve().parents[1] / "scripts" / "save_learning_note.py"
)
save_learning_note = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(save_learning_note)


GEM_ANSWER = """# CQRS Read Model

## ひとことで言うと
更新用と参照用のモデルを分ける設計。

## 噛み砕いた解説
- Write Model は整合性を最優先する。
- Read Model は表示速度を最優先する。

## 関連用語
- 結果整合性: 反映まで僅かなタイムラグがある状態。
"""


class SaveLearningNoteTests(unittest.TestCase):
    def make_vault(self, root: Path) -> Path:
        vault = root / "MainVault"
        (vault / "20_Dev_開発" / "Learning").mkdir(parents=True)
        return vault

    def test_saved_note_is_picked_up_by_the_existing_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self.make_vault(Path(tmp))
            path = save_learning_note.save_note(
                GEM_ANSWER, vault=vault, today=date(2026, 7, 28)
            )
            notes = obsidian_inbox_adapter.scan_promoted_notes(vault)

        self.assertEqual(path.name, "2026-07-28_CQRS Read Model.md")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].title, "CQRS Read Model")
        self.assertIn("学習日: 2026-07-28", notes[0].content)
        self.assertIn("結果整合性", notes[0].content)

    def test_plain_text_without_a_heading_is_saved_as_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self.make_vault(Path(tmp))
            path = save_learning_note.save_note(
                "サイドチャットの回答をそのままコピーした。見出しは付いていない。",
                vault=vault,
                today=date(2026, 8, 1),
            )
            text = path.read_text(encoding="utf-8")
            notes = obsidian_inbox_adapter.scan_promoted_notes(vault)

        self.assertEqual(path.name, "2026-08-01_サイドチャットの回答をそのままコピーした.md")
        self.assertIn("format: raw\n", text)
        self.assertIn("サイドチャットの回答", text)
        self.assertEqual(len(notes), 1)
        self.assertFalse(notes[0].structured)
        self.assertTrue(notes[0].notion_inbox_title.startswith("Obsidian未整形｜"))

    def test_a_headed_note_still_takes_the_structured_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self.make_vault(Path(tmp))
            save_learning_note.save_note(GEM_ANSWER, vault=vault, today=date(2026, 7, 28))
            notes = obsidian_inbox_adapter.scan_promoted_notes(vault)
        self.assertTrue(notes[0].structured)
        self.assertEqual(notes[0].notion_inbox_title.split("｜")[0], "Obsidian")

    def test_a_provisional_title_never_swallows_a_whole_paragraph(self):
        long_line = "あ" * 200
        self.assertEqual(
            len(save_learning_note.provisional_title(long_line)),
            save_learning_note.PROVISIONAL_TITLE_CHARACTERS,
        )
        self.assertEqual(save_learning_note.provisional_title("- **要点**: 冪等性の話"), "要点")
        self.assertEqual(save_learning_note.provisional_title("   "), save_learning_note.FALLBACK_TITLE)

    def test_empty_and_oversized_clipboards_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self.make_vault(Path(tmp))
            with self.assertRaises(save_learning_note.SaveNoteError):
                save_learning_note.save_note("   \n  ", vault=vault)
            oversized = "# 用語\n" + "あ" * save_learning_note.MAX_NOTE_CHARACTERS
            with self.assertRaises(save_learning_note.SaveNoteError):
                save_learning_note.save_note(oversized, vault=vault)

    def test_answer_copied_as_a_code_block_is_unwrapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self.make_vault(Path(tmp))
            path = save_learning_note.save_note(
                f"```markdown\n{GEM_ANSWER}```", vault=vault, today=date(2026, 7, 28)
            )
            text = path.read_text(encoding="utf-8")
        self.assertNotIn("```", text)
        self.assertTrue(text.startswith("---\ntype: learning_note\nai_radio: true\n"))

    def test_second_note_on_the_same_term_never_overwrites_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self.make_vault(Path(tmp))
            first = save_learning_note.save_note(GEM_ANSWER, vault=vault, today=date(2026, 7, 28))
            original = first.read_bytes()
            second = save_learning_note.save_note(
                GEM_ANSWER.replace("更新用と参照用", "書き込みと読み出し"),
                vault=vault,
                today=date(2026, 7, 28),
            )
            unchanged = first.read_bytes()
        self.assertNotEqual(first, second)
        self.assertEqual(second.name, "2026-07-28_CQRS Read Model-2.md")
        self.assertEqual(original, unchanged)

    def test_slashes_in_a_term_do_not_escape_the_learning_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self.make_vault(Path(tmp))
            path = save_learning_note.save_note(
                "# ../../etc/passwd\n本文。\n", vault=vault, today=date(2026, 7, 28)
            )
        self.assertEqual(path.parent, (vault / "20_Dev_開発" / "Learning").resolve())


class NotionRoundTripTests(unittest.TestCase):
    def test_markdown_survives_the_notion_paragraph_round_trip(self):
        body = "\n".join(f"## 見出し{index}\n- 箇条書き{index}" for index in range(200))
        chunks = obsidian_inbox_adapter._split_on_line_boundaries(body)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("\n".join(chunks), body)

    def test_a_single_long_line_is_still_split(self):
        line = "あ" * 4000
        chunks = obsidian_inbox_adapter._split_on_line_boundaries(line)
        self.assertTrue(all(len(chunk) <= 1800 for chunk in chunks))
        self.assertEqual("".join(chunks), line)


class PromotedNoteParsingTests(unittest.TestCase):
    def test_term_is_recovered_from_the_receiving_box_title(self):
        self.assertEqual(
            process_inbox.obsidian_term_from_title("Obsidian｜CQRS Read Model｜ob-1234"),
            "CQRS Read Model",
        )
        self.assertIsNone(process_inbox.obsidian_term_from_title("手入力のメモ"))

    def test_injected_date_and_heading_are_removed_from_the_body(self):
        raw = "学習日: 2026-07-28\n\n# CQRS Read Model\n\n## ひとことで言うと\n分離する。"
        study_date, body = process_inbox.split_promoted_note(raw)
        self.assertEqual(study_date, "2026-07-28")
        self.assertEqual(body, "## ひとことで言うと\n分離する。")

    def test_placeholder_titles_are_recognised_as_junk(self):
        for junk in ("No content found", "情報なし", "・", "  ", "N/A", None):
            self.assertTrue(process_inbox.is_junk_value(junk), junk)
        for real in ("CQRS", "qlmanage", "正本"):
            self.assertFalse(process_inbox.is_junk_value(real), real)


class PageContentReadingTests(unittest.TestCase):
    def fake_children(self, responses):
        def _request_json(_session, _method, url, **_kwargs):
            block_id = url.split("/blocks/")[1].split("/children")[0]
            return {"results": responses.get(block_id, []), "has_more": False}

        return _request_json

    def test_pasted_table_rows_are_read_instead_of_being_dropped(self):
        def cell(text):
            return [{"plain_text": text}]

        responses = {
            "page-1": [
                {"id": "table-1", "type": "table", "table": {}, "has_children": True},
            ],
            "table-1": [
                {
                    "id": "row-1",
                    "type": "table_row",
                    "table_row": {"cells": [cell("用語"), cell("意味"), cell("例え")]},
                },
                {
                    "id": "row-2",
                    "type": "table_row",
                    "table_row": {"cells": [cell("CQRS"), cell("読み書き分離"), cell("カルテと要約")]},
                },
            ],
        }
        with patch.object(process_inbox, "request_json", self.fake_children(responses)):
            content = process_inbox.fetch_page_content("page-1")
        self.assertEqual(content, "用語 | 意味 | 例え\nCQRS | 読み書き分離 | カルテと要約")

    def test_a_page_with_no_blocks_reads_as_empty(self):
        with patch.object(process_inbox, "request_json", self.fake_children({"page-1": []})):
            self.assertEqual(process_inbox.fetch_page_content("page-1"), "")


class InboxProcessingTests(unittest.TestCase):
    def inbox_item(self, title):
        return {"id": "page-1", "properties": {"名前": {"title": [{"plain_text": title}]}}}

    def run_inbox(self, *, title, body, gemini_payload=None):
        class FakeModels:
            @staticmethod
            def generate_content(**_kwargs):
                if gemini_payload is None:
                    raise AssertionError("Gemini must not be called for promoted notes")

                class Response:
                    text = json.dumps(gemini_payload)

                return Response()

        class FakeClient:
            models = FakeModels()

        created = []
        stdout = io.StringIO()
        with (
            patch.object(process_inbox, "is_notion_configured", return_value=True),
            patch.object(process_inbox, "NOTION_INBOX_DATABASE_ID", "configured"),
            patch.object(process_inbox, "get_gemini_client", return_value=FakeClient()),
            patch.object(process_inbox, "fetch_inbox_items", return_value=[self.inbox_item(title)]),
            patch.object(process_inbox, "fetch_page_content", return_value=body),
            patch.object(process_inbox, "register_study_log", side_effect=lambda **kw: created.append(kw)),
            patch.object(process_inbox, "archive_inbox_item") as archive,
            patch("sys.stdout", stdout),
        ):
            process_inbox.process_inbox()
        return created, archive, stdout.getvalue()

    def test_promoted_note_is_registered_verbatim_without_calling_gemini(self):
        created, archive, _ = self.run_inbox(
            title="Obsidian｜CQRS Read Model｜ob-1234",
            body="学習日: 2026-07-28\n\n# CQRS Read Model\n\n## ひとことで言うと\n分離する。",
        )
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["title"], "CQRS Read Model")
        self.assertEqual(created[0]["study_date_str"], "2026-07-28")
        self.assertEqual(created[0]["summary"], "## ひとことで言うと\n分離する。")
        archive.assert_called_once()

    def test_placeholder_summary_stays_in_the_inbox_instead_of_becoming_a_row(self):
        created, archive, output = self.run_inbox(
            title="手入力のメモ",
            body="ほとんど中身のない貼り付け",
            gemini_payload={"title": "No content found", "summary": "情報なし", "study_date": "today"},
        )
        self.assertEqual(created, [])
        archive.assert_not_called()
        self.assertIn("受信箱へ残します", output)
        self.assertNotIn("手入力のメモ", output)

    def test_empty_page_never_becomes_a_row_invented_from_its_title(self):
        created, archive, output = self.run_inbox(title="CQRS", body="")
        self.assertEqual(created, [])
        archive.assert_not_called()
        self.assertIn("本文が空", output)

    def test_unstructured_promoted_note_is_named_and_organised_by_gemini(self):
        created, archive, _ = self.run_inbox(
            title="Obsidian未整形｜サイドチャットの回答をそのままコピーした｜ob-1234",
            body="学習日: 2026-08-01\n\n冪等性のある設計にすると再送しても壊れない。",
            gemini_payload={
                "title": "冪等性",
                "summary": "- 同じ要求を何度送っても結果が変わらない設計。",
                "study_date": "2026-08-01",
                "is_learning_material": True,
            },
        )
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["title"], "冪等性")
        self.assertEqual(created[0]["initial_title"].split("｜")[0], "Obsidian未整形")
        archive.assert_called_once()

    def test_content_judged_unrelated_is_ignored_instead_of_registered(self):
        created, archive, output = self.run_inbox(
            title="Obsidian未整形｜今日は朝から雨で気分が乗らない｜ob-5678",
            body="今日は朝から雨で気分が乗らない。夕飯は鍋にした。",
            gemini_payload={
                "title": "日記",
                "summary": "- 天気と夕飯の記録。",
                "study_date": "today",
                "is_learning_material": False,
            },
        )
        self.assertEqual(created, [])
        archive.assert_not_called()
        self.assertIn("学習素材ではない", output)

    def test_a_missing_relevance_judgement_still_registers(self):
        created, archive, _ = self.run_inbox(
            title="手入力のメモ",
            body="ベクトル検索の話",
            gemini_payload={"title": "ベクトル検索", "summary": "- 近い意味を探す。", "study_date": "today"},
        )
        self.assertEqual(len(created), 1)
        archive.assert_called_once()

    def test_malformed_promoted_note_stays_in_the_inbox(self):
        created, archive, _ = self.run_inbox(
            title="Obsidian｜情報なし｜ob-9999",
            body="学習日: 2026-07-28\n\n# 情報なし\n",
        )
        self.assertEqual(created, [])
        archive.assert_not_called()


if __name__ == "__main__":
    unittest.main()
