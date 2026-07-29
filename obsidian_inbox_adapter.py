"""Import explicitly promoted Obsidian learning notes into the Notion Inbox.

The source vault is read-only.  Import state is stored outside the vault, and
Notion remains the canonical structured learning database used by the podcast.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests
from dotenv import load_dotenv

from api_client import request_json


load_dotenv()

DEFAULT_VAULT = Path.home() / "Documents" / "Obsidian" / "MainVault"
LEARNING_RELATIVE_PATH = Path("20_Dev_開発") / "Learning"
MAX_NOTE_CHARACTERS = 20_000


class ObsidianIntakeError(RuntimeError):
    pass


@dataclass(frozen=True)
class PromotedNote:
    path: Path
    relative_path: str
    source_key: str
    title: str
    content: str
    content_sha256: str

    @property
    def notion_inbox_title(self) -> str:
        return f"Obsidian｜{self.title}｜{self.source_key}"[:200]


def _frontmatter_and_body(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    metadata: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        metadata[key.strip().casefold()] = value.strip().strip('"\'').casefold()
    return metadata, text[end + 5 :]


def _note_title(path: Path, body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip()[:120]
    return path.stem[:120]


def scan_promoted_notes(vault: Path) -> list[PromotedNote]:
    """Read only opted-in notes from the development Learning directory."""
    vault = vault.expanduser().resolve()
    learning_root = (vault / LEARNING_RELATIVE_PATH).resolve()
    if not learning_root.is_dir():
        raise ObsidianIntakeError(f"Learning directory not found: {learning_root}")

    notes: list[PromotedNote] = []
    for path in sorted(learning_root.rglob("*.md")):
        if path.name.casefold() == "readme.md" or path.is_symlink():
            continue
        resolved = path.resolve()
        if learning_root not in resolved.parents:
            continue
        raw = path.read_text(encoding="utf-8")
        metadata, body = _frontmatter_and_body(raw)
        if metadata.get("ai_radio") not in {"true", "ready"}:
            continue
        if metadata.get("clinical") in {"true", "yes"}:
            raise ObsidianIntakeError(f"Clinical note cannot be promoted: {path.name}")
        body = body.strip()
        if not body:
            raise ObsidianIntakeError(f"Promoted note is empty: {path.name}")
        created = metadata.get("created", "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", created):
            body = f"学習日: {created}\n\n{body}"
        if len(body) > MAX_NOTE_CHARACTERS:
            raise ObsidianIntakeError(f"Promoted note exceeds {MAX_NOTE_CHARACTERS} characters: {path.name}")

        relative = resolved.relative_to(vault).as_posix()
        source_key = "ob-" + hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
        notes.append(
            PromotedNote(
                path=resolved,
                relative_path=relative,
                source_key=source_key,
                title=_note_title(path, body),
                content=body,
                content_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            )
        )
    return notes


def default_state_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "AIRadio" / "obsidian-import-state.json"


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "imports": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObsidianIntakeError(f"Could not read import state: {path}") from exc
    if payload.get("schema_version") != 1 or not isinstance(payload.get("imports"), dict):
        raise ObsidianIntakeError("Unsupported Obsidian import state")
    return payload


def save_state_atomic(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, prefix=".obsidian-import-"
    ) as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _notion_session(api_key: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
    )
    return session


def _database_has_title(
    session: requests.Session,
    database_id: str,
    *,
    property_name: str,
    property_type: str,
    title: str,
) -> bool:
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    payload = {
        "page_size": 1,
        "filter": {"property": property_name, property_type: {"equals": title}},
    }
    data = request_json(session, "POST", url, json=payload, safe_to_retry=True)
    return bool(data.get("results"))


def already_in_notion(
    session: requests.Session,
    note: PromotedNote,
    *,
    inbox_database_id: str,
    learning_database_id: str,
) -> bool:
    return _database_has_title(
        session,
        inbox_database_id,
        property_name="名前",
        property_type="title",
        title=note.notion_inbox_title,
    ) or _database_has_title(
        session,
        learning_database_id,
        property_name="元のページ名",
        property_type="rich_text",
        title=note.notion_inbox_title,
    )


def _split_on_line_boundaries(text: str, limit: int = 1800) -> list[str]:
    """Chunk without cutting a line, so Notion round-trips the markdown intact."""
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append("\n".join(current))
                current, length = [], 0
            chunks.append(line[:limit])
            line = line[limit:]
        addition = len(line) + (1 if current else 0)
        if current and length + addition > limit:
            chunks.append("\n".join(current))
            current, length = [], 0
            addition = len(line)
        current.append(line)
        length += addition
    if current:
        chunks.append("\n".join(current))
    return chunks or [""]


def _paragraph_blocks(text: str) -> list[dict]:
    chunks = _split_on_line_boundaries(text)
    return [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
        }
        for chunk in chunks[:100]
    ]


def create_notion_inbox_page(
    session: requests.Session,
    note: PromotedNote,
    *,
    inbox_database_id: str,
) -> str:
    payload = {
        "parent": {"database_id": inbox_database_id},
        "properties": {
            "名前": {"title": [{"text": {"content": note.notion_inbox_title}}]},
        },
        "children": _paragraph_blocks(note.content),
    }
    data = request_json(
        session,
        "POST",
        "https://api.notion.com/v1/pages",
        json=payload,
        safe_to_retry=False,
    )
    page_id = data.get("id")
    if not page_id:
        raise ObsidianIntakeError("Notion did not return a page ID")
    return str(page_id)


def import_promoted_notes(
    *,
    vault: Path,
    state_path: Path,
    api_key: str,
    inbox_database_id: str,
    learning_database_id: str,
    dry_run: bool = False,
) -> dict:
    notes = scan_promoted_notes(vault)
    state = load_state(state_path)
    pending = [note for note in notes if note.source_key not in state["imports"]]
    if dry_run:
        return {"discovered": len(notes), "pending": len(pending), "imported": 0, "skipped": 0}
    if not api_key or not inbox_database_id or not learning_database_id:
        raise ObsidianIntakeError("Notion settings are incomplete")

    session = _notion_session(api_key)
    imported = 0
    skipped = 0
    for note in pending:
        if already_in_notion(
            session,
            note,
            inbox_database_id=inbox_database_id,
            learning_database_id=learning_database_id,
        ):
            page_id = "existing"
            skipped += 1
        else:
            page_id = create_notion_inbox_page(
                session, note, inbox_database_id=inbox_database_id
            )
            imported += 1
        state["imports"][note.source_key] = {
            "relative_path": note.relative_path,
            "content_sha256": note.content_sha256,
            "notion_page_id": page_id,
        }
        save_state_atomic(state_path, state)
    return {
        "discovered": len(notes),
        "pending": len(pending),
        "imported": imported,
        "skipped": skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", type=Path, default=Path(os.getenv("OBSIDIAN_VAULT_PATH", DEFAULT_VAULT)))
    parser.add_argument("--state", type=Path, default=default_state_path())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = import_promoted_notes(
        vault=args.vault,
        state_path=args.state,
        api_key=os.getenv("NOTION_API_KEY", ""),
        inbox_database_id=os.getenv("NOTION_INBOX_DATABASE_ID", ""),
        learning_database_id=os.getenv("NOTION_DATABASE_ID", ""),
        dry_run=args.dry_run,
    )
    print(
        "Obsidian intake complete: "
        f"discovered={result['discovered']} pending={result['pending']} "
        f"imported={result['imported']} skipped={result['skipped']}"
    )


if __name__ == "__main__":
    main()
