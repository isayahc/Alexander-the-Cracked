"""Leaderboard rendering for the swarm claim registry.

Pure functions over :class:`ClaimRow` lists — no I/O beyond the one JSON
write — so the CLI stays thin and the table/JSON shapes are unit-testable.
The registry is the aggregation source: pending claims (claimed but never
recorded) are reported explicitly rather than hidden, so a crashed
coordinator's state is visible to a human.
"""

import json
import os
from dataclasses import asdict
from pathlib import Path

from alexander.builder import BuildStatus
from alexander.swarm.registry import CLAIMED, ClaimRow

_REPORT_FILENAME = "swarm-report.json"


def pending_slugs(rows: list[ClaimRow]) -> list[str]:
    """Slugs claimed but without a terminal result."""
    return [row.event_slug for row in rows if row.status == CLAIMED]


def has_failed_build(rows: list[ClaimRow]) -> bool:
    """True if any claim reached a terminal non-success outcome."""
    failed = {BuildStatus.BUDGET_EXHAUSTED, BuildStatus.ERROR}
    return any(row.status in failed for row in rows)


def _display_status(status: str) -> str:
    if status == BuildStatus.SUCCESS:
        return "✅ success"
    if status == BuildStatus.BUDGET_EXHAUSTED:
        return "❌ budget_exhausted"
    if status == BuildStatus.ERROR:
        return "❌ error"
    return "⚠️ pending"


def render_leaderboard(rows: list[ClaimRow]) -> str:
    """Render the swarm leaderboard table.

    Pending rows show no worker, tests, or build dir — nobody has recorded
    an outcome yet. Terminal rows show the owning claimant (the registry
    stores owners, not worker ids).
    """
    if not rows:
        return "No claims recorded yet."

    pending = set(pending_slugs(rows))
    lines = [
        f"{'Rank':>4}  {'Event':<30}  {'Worker':<24}  {'Status':<20}"
        f"  {'Attempts':>8}  {'Tests':<24}  Build dir"
    ]
    for row in rows:
        is_pending = row.event_slug in pending
        worker = "—" if is_pending else row.owner
        tests = row.test_summary or "—"
        build_dir = "—" if row.artifact_path is None else row.artifact_path
        lines.append(
            f"{row.rank:>4}  {row.event_name[:30]:<30}  {worker:<24}"
            f"  {_display_status(row.status):<20}  {row.attempts_used:>8}"
            f"  {tests[:24]:<24}  {build_dir}"
        )
    return "\n".join(lines)


def report_payload(rows: list[ClaimRow]) -> dict[str, object]:
    """Serialize full claim rows (plus the pending list) for swarm-report.json."""
    return {
        "rows": [asdict(row) for row in rows],
        "pending": pending_slugs(rows),
    }


def write_report(rows: list[ClaimRow], out_root: Path) -> Path:
    """Write ``<out-root>/swarm-report.json`` atomically and return its path."""
    out_root.mkdir(parents=True, exist_ok=True)
    path = out_root / _REPORT_FILENAME
    tmp = out_root / (_REPORT_FILENAME + ".tmp")
    tmp.write_text(json.dumps(report_payload(rows), indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path
