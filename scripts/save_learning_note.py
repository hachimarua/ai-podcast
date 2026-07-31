#!/usr/bin/env python3
"""Save a study answer from any AI chat as a promoted Obsidian learning note.

The clipboard text is written into the vault's Learning directory with the
frontmatter that obsidian_inbox_adapter.py requires.  Nothing else in the vault
is read or modified.

A clipboard that opens with `# 用語名` is already in the final shape and is kept
verbatim (`format: structured`).  Plain prose from a side chat is accepted too
and marked `format: raw`, so the intake stage can name and organise it later.
Only an empty or oversized clipboard is refused here: judging what is worth
keeping happens downstream, where the whole text is available.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

DEFAULT_VAULT = Path.home() / "Documents" / "Obsidian" / "MainVault"
LEARNING_RELATIVE_PATH = Path("20_Dev_開発") / "Learning"
MAX_NOTE_CHARACTERS = 20_000
UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
FENCE_LINE = re.compile(r"^```[\w-]*$")
PROVISIONAL_TITLE_CHARACTERS = 40
FALLBACK_TITLE = "学習メモ"
LIST_MARKER = re.compile(r"^\s*(?:[-*+•・>]|\d+[.)])\s+")
INLINE_MARKUP = re.compile(r"[*_`#\[\]]+")
SENTENCE_BREAK = re.compile(r"[。．.!?！？:：、,]")


class SaveNoteError(RuntimeError):
    pass


def read_clipboard() -> str:
    result = subprocess.run(
        ["/usr/bin/pbpaste"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise SaveNoteError("クリップボードを読めませんでした")
    return result.stdout


def strip_outer_fence(text: str) -> str:
    """Unwrap a whole answer that was copied as a single fenced code block."""
    lines = text.strip().splitlines()
    if len(lines) >= 2 and FENCE_LINE.match(lines[0].strip()) and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text.strip()


def provisional_title(line: str) -> str:
    """Name a headingless note from its opening line, for the filename only."""
    text = INLINE_MARKUP.sub("", LIST_MARKER.sub("", line)).strip(" 　-–—:：")
    if not text:
        return FALLBACK_TITLE
    head = text[: PROVISIONAL_TITLE_CHARACTERS + 1]
    boundary = SENTENCE_BREAK.search(head)
    if boundary and boundary.start():
        return head[: boundary.start()]
    return text[:PROVISIONAL_TITLE_CHARACTERS].strip() or FALLBACK_TITLE


def derive_title(body: str) -> tuple[str, bool]:
    """Return the note title and whether the clipboard was already structured.

    `# 用語名` on the first line means the保存用ブロック shape, which downstream
    registers verbatim.  Anything else keeps a provisional title and is handed
    to the intake stage to be named properly.
    """
    for line in body.splitlines():
        if not line.strip():
            continue
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip()[:120], True
        return provisional_title(line), False
    raise SaveNoteError("クリップボードが空です")


def safe_stem(title: str) -> str:
    stem = UNSAFE_FILENAME_CHARS.sub("_", title).strip(" ._")
    return stem[:60] or "learning_note"


def build_note(body: str, created: date, *, structured: bool) -> str:
    return (
        "---\n"
        "type: learning_note\n"
        "ai_radio: true\n"
        f"created: {created.isoformat()}\n"
        "source: clipboard\n"
        f"format: {'structured' if structured else 'raw'}\n"
        "---\n"
        f"{body.strip()}\n"
    )


def unique_path(directory: Path, stem: str) -> Path:
    candidate = directory / f"{stem}.md"
    if not candidate.exists():
        return candidate
    for suffix in range(2, 100):
        candidate = directory / f"{stem}-{suffix}.md"
        if not candidate.exists():
            return candidate
    raise SaveNoteError(f"同名ノートが多すぎます: {stem}")


def write_atomic(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, prefix=".learning-note-"
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def save_note(text: str, *, vault: Path, today: date | None = None) -> Path:
    today = today or date.today()
    body = strip_outer_fence(text)
    if not body:
        raise SaveNoteError("クリップボードが空です")
    if len(body) > MAX_NOTE_CHARACTERS:
        raise SaveNoteError(f"本文が{MAX_NOTE_CHARACTERS}文字を超えています")

    learning_root = (vault.expanduser() / LEARNING_RELATIVE_PATH).resolve()
    if not learning_root.is_dir():
        raise SaveNoteError(f"Learningフォルダが見つかりません: {learning_root}")

    title, structured = derive_title(body)
    path = unique_path(learning_root, f"{today.isoformat()}_{safe_stem(title)}")
    write_atomic(path, build_note(body, today, structured=structured))
    return path


def run_import(workspace: Path) -> str:
    python = workspace / "venv" / "bin" / "python"
    script = workspace / "obsidian_inbox_adapter.py"
    result = subprocess.run(
        [str(python), str(script)],
        cwd=workspace,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        raise SaveNoteError(f"Notion取り込みが失敗しました (exit {result.returncode})")
    return result.stdout.strip()


def notify(message: str, title: str = "AI学習ラジオ") -> None:
    subprocess.run(
        [
            "/usr/bin/osascript",
            "-e",
            "on run argv",
            "-e",
            "display notification (item 1 of argv) with title (item 2 of argv)",
            "-e",
            "end run",
            message,
            title,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )


def main() -> None:
    workspace_default = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", type=Path, default=Path(os.getenv("OBSIDIAN_VAULT_PATH", DEFAULT_VAULT)))
    parser.add_argument("--workspace", type=Path, default=workspace_default)
    parser.add_argument("--stdin", action="store_true", help="クリップボードではなく標準入力から読む")
    parser.add_argument("--no-import", action="store_true", help="Notion受信箱への取り込みを行わない")
    parser.add_argument("--no-notify", action="store_true", help="通知を出さない")
    args = parser.parse_args()

    try:
        text = sys.stdin.read() if args.stdin else read_clipboard()
        path = save_note(text, vault=args.vault)
    except SaveNoteError as exc:
        print(f"保存しませんでした: {exc}", file=sys.stderr)
        if not args.no_notify:
            notify(str(exc), "保存しませんでした")
        raise SystemExit(1) from exc

    print(f"保存しました: {path}")
    message = path.stem
    if not args.no_import:
        try:
            summary = run_import(args.workspace)
            print(summary or "Notion取り込み完了")
            message = f"{path.stem} / Notion受信箱へ送信"
        except SaveNoteError as exc:
            print(f"取り込みは次回へ延期します: {exc}", file=sys.stderr)
            message = f"{path.stem} / 取り込みは次回へ延期"
    if not args.no_notify:
        notify(message, "学習ノートを保存")


if __name__ == "__main__":
    main()
