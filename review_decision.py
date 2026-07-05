"""Record an explicit Agreed / Disagree / Later decision through GitHub."""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
from datetime import datetime, timezone


REPOSITORY = "hachimarua/ai-podcast"
PROPOSAL_ID_PATTERN = re.compile(r"^qa-[A-Za-z0-9_-]+$")
DECISION_STATUS = {
    "agreed": "agreed",
    "disagreed": "disagreed",
    "later": "later",
}


class DecisionError(RuntimeError):
    pass


def update_proposal_decision(
    proposal: dict,
    decision: str,
    reason: str,
    *,
    decided_at: str | None = None,
) -> dict:
    if decision not in DECISION_STATUS:
        raise ValueError(f"Unsupported decision: {decision}")
    if proposal.get("status") not in {"pending", "later"}:
        raise ValueError(f"Proposal is already decided: {proposal.get('status')}")
    updated = dict(proposal)
    updated["status"] = DECISION_STATUS[decision]
    updated["decision_reason"] = reason.strip()[:1000] or None
    updated["decided_at"] = decided_at or datetime.now(timezone.utc).isoformat()
    return updated


def _gh_json(arguments: list[str], *, input_text: str | None = None) -> dict:
    result = subprocess.run(
        ["gh", *arguments],
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise DecisionError(f"GitHub update failed: gh {arguments[0]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DecisionError("GitHub returned invalid JSON") from exc


def record_decision(proposal_id: str, decision: str, reason: str) -> str:
    if not PROPOSAL_ID_PATTERN.fullmatch(proposal_id):
        raise ValueError("Invalid proposal ID")
    path = f"quality_reports/pending/{proposal_id}.json"
    current = _gh_json([
        "api", f"repos/{REPOSITORY}/contents/{path}?ref=main",
    ])
    try:
        proposal = json.loads(base64.b64decode(current["content"]).decode("utf-8"))
        sha = current["sha"]
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise DecisionError("Could not decode the current proposal") from exc

    updated = update_proposal_decision(proposal, decision, reason)
    encoded = base64.b64encode(
        (json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    ).decode("ascii")
    response = _gh_json([
        "api", "--method", "PUT", f"repos/{REPOSITORY}/contents/{path}",
        "-f", f"message=chore: record {decision} for {proposal_id}",
        "-f", f"content={encoded}",
        "-f", f"sha={sha}",
        "-f", "branch=main",
    ])
    return response.get("commit", {}).get("sha", "")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal-id", required=True)
    parser.add_argument("--decision", choices=sorted(DECISION_STATUS), required=True)
    parser.add_argument("--reason", default="")
    args = parser.parse_args()
    commit_sha = record_decision(args.proposal_id, args.decision, args.reason)
    print(f"Decision recorded: {args.proposal_id} -> {args.decision} ({commit_sha[:12]})")


if __name__ == "__main__":
    main()
