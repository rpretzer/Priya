# AI-GENERATED: 2026-03-03T16:57:33Z | pipeline/coach/memory.py | Copilot
"""CoachMemory — SQLite + FTS episodic memory for Hoopla Coach.

Stores session learnings (CrystalItems) and allows retrieval by semantic
similarity via SQLite FTS5 full-text search. No external vector store required.

Schema:
    sessions(id, created_at, summary)
    crystal_items(id, session_id, kind, text, confidence, turn_index, created_at)
    crystal_items_fts  — FTS5 virtual table over crystal_items.text

Usage:
    memory = CoachMemory(db_path="~/.hoopla/memory.db")
    memory.save_session(session_id, crystal_result)
    context = memory.recall(query="per-circulation budget constraint", top_k=5)
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.coach.crystallizer import CrystalItem, CrystalResult

_DEFAULT_DB_PATH = os.path.expanduser("~/.hoopla/memory.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS crystal_items (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    kind        TEXT NOT NULL,
    text        TEXT NOT NULL,
    confidence  REAL NOT NULL DEFAULT 1.0,
    turn_index  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS crystal_items_fts
USING fts5(
    text,
    kind,
    content='crystal_items',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS crystal_items_ai
AFTER INSERT ON crystal_items BEGIN
    INSERT INTO crystal_items_fts(rowid, text, kind)
    VALUES (new.rowid, new.text, new.kind);
END;

CREATE TRIGGER IF NOT EXISTS crystal_items_ad
AFTER DELETE ON crystal_items BEGIN
    INSERT INTO crystal_items_fts(crystal_items_fts, rowid, text, kind)
    VALUES ('delete', old.rowid, old.text, old.kind);
END;

-- Conversation turns: every user/assistant message persisted for crash recovery
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    turn_index  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS conversations_session_idx
    ON conversations(session_id, turn_index);

-- Artifacts: generated business-case.md / epics.md / stories-draft.md
CREATE TABLE IF NOT EXISTS artifacts (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    artifact_type   TEXT NOT NULL,
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS artifacts_session_idx
    ON artifacts(session_id, created_at);
"""


class CoachMemory:
    """SQLite + FTS episodic memory store.

    Saves CrystalItems from completed sessions and retrieves relevant
    context for new sessions using full-text search.

    Thread safety: Each call opens and closes its own connection.
    Not designed for concurrent writes from multiple processes.
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = os.path.expanduser(db_path or _DEFAULT_DB_PATH)
        self._ensure_db()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_session(
        self,
        session_id: str,
        crystal_result: "CrystalResult",
    ) -> None:
        """Persist a completed session's CrystalResult to the database.

        Args:
            session_id: Unique identifier for this coaching session.
            crystal_result: Output from Crystallizer.extract().
        """
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions(id, created_at, summary) VALUES (?, ?, ?)",
                (session_id, now, crystal_result.session_summary),
            )
            for item in crystal_result.items:
                conn.execute(
                    """INSERT INTO crystal_items(id, session_id, kind, text, confidence, turn_index, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        session_id,
                        item.kind,
                        item.text,
                        item.confidence,
                        item.turn_index,
                        now,
                    ),
                )

    def recall(
        self,
        query: str,
        top_k: int = 10,
        kind_filter: str | None = None,
    ) -> str:
        """Return a formatted context string of relevant past learnings.

        Uses FTS5 BM25 ranking. Returns an empty string if no results.

        Args:
            query: Natural-language search query.
            top_k: Maximum number of items to return.
            kind_filter: If set, restrict to items of this kind
                         ("constraint", "decision", "assumption", "preference").

        Returns:
            Formatted markdown string suitable for injection into the system prompt.
        """
        rows = self._search(query, top_k=top_k, kind_filter=kind_filter)
        if not rows:
            return ""

        lines = ["## Relevant Past Session Learnings\n"]
        for kind, text, confidence, created_at in rows:
            conf_str = f" (confidence: {confidence:.0%})" if confidence < 0.9 else ""
            lines.append(f"- [{kind.upper()}]{conf_str} {text}  _(from {created_at[:10]})_")

        return "\n".join(lines)

    def list_sessions(self, limit: int = 20) -> list[dict]:
        """Return a list of recent session metadata dicts."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, summary FROM sessions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"id": r[0], "created_at": r[1], "summary": r[2]}
            for r in rows
        ]

    def delete_session(self, session_id: str) -> None:
        """Delete a session and all its crystal items."""
        with self._connect() as conn:
            conn.execute("DELETE FROM crystal_items WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def clear_all(self) -> None:
        """Delete all sessions and items. Use with caution."""
        with self._connect() as conn:
            conn.execute("DELETE FROM crystal_items")
            conn.execute("DELETE FROM sessions")

    # ------------------------------------------------------------------
    # Conversation persistence
    # ------------------------------------------------------------------

    def save_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        turn_index: int = 0,
    ) -> None:
        """Persist a single conversation turn.

        Creates a stub session row if one doesn't exist yet so the FK is
        satisfied before Crystallizer runs at session end.
        """
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions(id, created_at, summary) VALUES (?, ?, '')",
                (session_id, now),
            )
            conn.execute(
                """INSERT INTO conversations(id, session_id, role, content, turn_index, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), session_id, role, content, turn_index, now),
            )

    def get_conversation(self, session_id: str) -> list[dict]:
        """Return all turns for a session in order."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT role, content, turn_index, created_at
                   FROM conversations
                   WHERE session_id = ?
                   ORDER BY turn_index, created_at""",
                (session_id,),
            ).fetchall()
        return [
            {"role": r[0], "content": r[1], "turn_index": r[2], "created_at": r[3]}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Artifact persistence
    # ------------------------------------------------------------------

    def save_artifact(
        self,
        session_id: str,
        artifact_type: str,
        content: str,
    ) -> str:
        """Persist a generated artifact. Returns the artifact ID."""
        now = _now()
        artifact_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions(id, created_at, summary) VALUES (?, ?, '')",
                (session_id, now),
            )
            conn.execute(
                """INSERT INTO artifacts(id, session_id, artifact_type, content, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (artifact_id, session_id, artifact_type, content, now),
            )
        return artifact_id

    def get_artifacts(self, session_id: str) -> list[dict]:
        """Return all artifacts for a session, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, artifact_type, content, created_at
                   FROM artifacts
                   WHERE session_id = ?
                   ORDER BY created_at DESC""",
                (session_id,),
            ).fetchall()
        return [
            {"id": r[0], "artifact_type": r[1], "content": r[2], "created_at": r[3]}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_db(self) -> None:
        """Create the database file and schema if they don't exist."""
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _search(
        self,
        query: str,
        top_k: int,
        kind_filter: str | None,
    ) -> list[tuple]:
        """Execute FTS search and return (kind, text, confidence, created_at) tuples."""
        # Sanitize query for FTS5 (remove special chars that break parsing)
        safe_query = _sanitize_fts_query(query)
        if not safe_query:
            return []

        with self._connect() as conn:
            if kind_filter:
                sql = """
                    SELECT ci.kind, ci.text, ci.confidence, ci.created_at
                    FROM crystal_items_fts fts
                    JOIN crystal_items ci ON ci.rowid = fts.rowid
                    WHERE crystal_items_fts MATCH ? AND ci.kind = ?
                    ORDER BY bm25(crystal_items_fts)
                    LIMIT ?
                """
                rows = conn.execute(sql, (safe_query, kind_filter, top_k)).fetchall()
            else:
                sql = """
                    SELECT ci.kind, ci.text, ci.confidence, ci.created_at
                    FROM crystal_items_fts fts
                    JOIN crystal_items ci ON ci.rowid = fts.rowid
                    WHERE crystal_items_fts MATCH ?
                    ORDER BY bm25(crystal_items_fts)
                    LIMIT ?
                """
                rows = conn.execute(sql, (safe_query, top_k)).fetchall()

        return [(r[0], r[1], r[2], r[3]) for r in rows]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sanitize_fts_query(query: str) -> str:
    """Remove FTS5 special characters to prevent parse errors."""
    import re
    # Keep alphanumerics, spaces, hyphens
    cleaned = re.sub(r'[^\w\s\-]', ' ', query, flags=re.UNICODE)
    return cleaned.strip()


def generate_session_id() -> str:
    """Generate a new unique session ID."""
    return str(uuid.uuid4())
