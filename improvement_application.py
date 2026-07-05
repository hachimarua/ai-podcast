"""Validate and record the application of an explicitly agreed proposal."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


APPLICATION_LEVELS = {"A", "B", "C"}


def mark_proposal_applied(
    proposal: dict,
    *,
    level: str,
    changed_files: list[str],
    verification: list[str],
    applied_at: str | None = None,
) -> dict:
    """Return an applied proposal without trusting proposal text as instructions."""
    normalized_level = level.upper()
    if normalized_level not in APPLICATION_LEVELS:
        raise ValueError(f"Unsupported application level: {level}")
    if proposal.get("status") != "agreed":
        raise ValueError("Only an agreed proposal can be marked as applied")
    if normalized_level == "A" and not proposal.get("safe_auto_apply", False):
        raise ValueError("Level A requires safe_auto_apply=true")

    files = sorted({path.strip() for path in changed_files if path.strip()})
    checks = [item.strip() for item in verification if item.strip()]
    if not files:
        raise ValueError("At least one changed file is required")
    if not checks:
        raise ValueError("At least one verification result is required")

    updated = dict(proposal)
    updated["status"] = "applied"
    updated["application"] = {
        "level": normalized_level,
        "applied_at": applied_at or datetime.now(timezone.utc).isoformat(),
        "changed_files": files,
        "verification": checks,
    }
    return updated


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, prefix=".application-"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("proposal", type=Path)
    parser.add_argument("--level", choices=sorted(APPLICATION_LEVELS), required=True)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--verification", action="append", default=[])
    args = parser.parse_args()

    proposal = json.loads(args.proposal.read_text(encoding="utf-8"))
    updated = mark_proposal_applied(
        proposal,
        level=args.level,
        changed_files=args.changed_file,
        verification=args.verification,
    )
    write_json_atomic(args.proposal, updated)
    print(f"Proposal marked applied: {updated['proposal_id']} (Level {args.level})")


if __name__ == "__main__":
    main()
