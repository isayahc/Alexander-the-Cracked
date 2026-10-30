"""SQLite-backed claim registry: the swarm's single coordination invariant.

Claim-before-build is the only shared state between Alexander instances.
Claiming is one ``INSERT OR IGNORE`` on the event-slug primary key, so even
racing processes cannot both win; results are recorded on the same row,
which also makes the registry the report's aggregation source.
"""

import os
import socket
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from alexander.builder import BuildStatus

_CLAIMED = "claimed"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    event_slug    TEXT PRIMARY KEY,
    event_name    TEXT NOT NULL,
    rank          INTEGER NOT NULL,
    owner         TEXT NOT NULL,
    claimed_at    REAL NOT NULL,
    status        TEXT NOT NULL,
    artifact_path TEXT,
    test_summary  TEXT,
    error         TEXT,
    attempts_used INTEGER NOT NULL DEFAULT 0
)
"""


@dataclass(frozen=True)
class ClaimRow:
    """One registry row: a claim and, once recorded, its build outcome."""

    event_slug: str
    event_name: str
    rank: int
    owner: str
    claimed_at: float
    status: str
    artifact_path: str | None = None
    test_summary: str | None = None
    error: str | None = None
    attempts_used: int = 0


class ClaimRegistry:
    """Claim registry over stdlib sqlite3 in WAL mode.

    One claimant per ``owner``; the default owner is ``hostname:pid`` so two
    terminals on one machine are distinct. The clock is injectable for tests.
    """

    def __init__(
        self,
        db_path: Path,
        owner: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db_path = Path(db_path)
        self.owner = owner if owner is not None else f"{socket.gethostname()}:{os.getpid()}"
        self._clock = clock
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def claim(self, event_slug: str, event_name: str, rank: int) -> bool:
        """Atomically claim an event. True iff this call won the race."""
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO claims"
            " (event_slug, event_name, rank, owner, claimed_at, status)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (event_slug, event_name, rank, self.owner, self._clock(), _CLAIMED),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def record_result(
        self,
        event_slug: str,
        status: BuildStatus,
        artifact_path: Path | None,
        test_summary: str | None,
        error: str | None,
        attempts_used: int,
    ) -> None:
        """Write the build outcome. Owner-checked: only the claimant records."""
        cursor = self._conn.execute(
            "UPDATE claims SET status = ?, artifact_path = ?, test_summary = ?,"
            " error = ?, attempts_used = ? WHERE event_slug = ? AND owner = ?",
            (
                status.value,
                str(artifact_path) if artifact_path is not None else None,
                test_summary,
                error,
                attempts_used,
                event_slug,
                self.owner,
            ),
        )
        self._conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"no claim on {event_slug!r} owned by {self.owner!r}")

    def release(self, event_slug: str) -> None:
        """Return an unfinished claim to the pool (crash/timeout recovery).

        Terminal results are never released; a coordinator recovering a dead
        worker's claim must decide that explicitly rather than through here.
        """
        self._conn.execute(
            "DELETE FROM claims WHERE event_slug = ? AND status = ?",
            (event_slug, _CLAIMED),
        )
        self._conn.commit()

    def results(self) -> list[ClaimRow]:
        """All claims with their lifecycle state and outcomes — the report's source."""
        rows = self._conn.execute(
            "SELECT event_slug, event_name, rank, owner, claimed_at, status,"
            " artifact_path, test_summary, error, attempts_used FROM claims"
            " ORDER BY rank, event_slug"
        ).fetchall()
        return [ClaimRow(*row) for row in rows]

    def pending(self) -> list[str]:
        """Slugs claimed but without a terminal result — the report's warning list."""
        return [
            row[0]
            for row in self._conn.execute(
                "SELECT event_slug FROM claims WHERE status = ?", (_CLAIMED,)
            )
        ]

    def close(self) -> None:
        """Close the connection; WAL checkpointing happens automatically."""
        self._conn.close()
