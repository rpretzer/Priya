# AI-GENERATED: 2026-03-03T16:57:33Z | pipeline/coach/memory.py | Copilot
"""CoachMemory — SQLite + FTS episodic memory for Hoopla Coach.

Stores session learnings (CrystalItems) and allows retrieval by semantic
similarity via SQLite FTS5 full-text search. No external vector store required.

Schema:
    sessions(id, created_at, summary)
    crystal_items(id, session_id, kind, text, confidence, turn_index, created_at)
    crystal_items_fts  — FTS5 virtual table over crystal_items.text
    features(id, session_id, feature_name, feature_name_normalized, problem_statement,
             mode, artifact_content, created_at)
    features_fts  — FTS5 virtual table over features.feature_name + problem_statement

Usage:
    memory = CoachMemory(db_path="~/.hoopla/memory.db")
    memory.save_session(session_id, crystal_result)
    context = memory.recall(query="per-circulation budget constraint", top_k=5)

    # Phase B — Active Memory Tools
    memory.save_feature(session_id, "BingePass Borrow Limit UI", problem_statement="...", mode="intake")
    analogues = memory.recall_similar_feature("borrow limit patron confusion", top_k=3)
    outcome = memory.lookup_feature_outcome("BingePass Borrow Limit UI")
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

-- Feature index: one row per named feature/initiative discussed in a session.
-- Powers Phase B active memory: recall_similar_feature() and lookup_feature_outcome().
CREATE TABLE IF NOT EXISTS features (
    id                      TEXT PRIMARY KEY,
    session_id              TEXT NOT NULL REFERENCES sessions(id),
    feature_name            TEXT NOT NULL,
    feature_name_normalized TEXT NOT NULL,
    problem_statement       TEXT NOT NULL DEFAULT '',
    mode                    TEXT NOT NULL DEFAULT 'intake',
    artifact_content        TEXT NOT NULL DEFAULT '',
    created_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS features_session_idx
    ON features(session_id);

CREATE INDEX IF NOT EXISTS features_name_idx
    ON features(feature_name_normalized);

CREATE VIRTUAL TABLE IF NOT EXISTS features_fts
USING fts5(
    feature_name,
    problem_statement,
    content='features',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS features_ai
AFTER INSERT ON features BEGIN
    INSERT INTO features_fts(rowid, feature_name, problem_statement)
    VALUES (new.rowid, new.feature_name, new.problem_statement);
END;

CREATE TRIGGER IF NOT EXISTS features_ad
AFTER DELETE ON features BEGIN
    INSERT INTO features_fts(features_fts, rowid, feature_name, problem_statement)
    VALUES ('delete', old.rowid, old.feature_name, old.problem_statement);
END;
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
            conn.execute("DELETE FROM features")
            conn.execute("DELETE FROM crystal_items")
            conn.execute("DELETE FROM sessions")

    # ------------------------------------------------------------------
    # Phase B — Feature index (Active Memory Tools)
    # ------------------------------------------------------------------

    def save_feature(
        self,
        session_id: str,
        feature_name: str,
        problem_statement: str = "",
        mode: str = "intake",
        artifact_content: str = "",
    ) -> str:
        """Index a named feature from a session for later analogue recall.

        Creates a stub session row if needed. If a feature with the same
        normalized name already exists for this session, it is upserted
        (artifact_content updated) to avoid duplicates.

        Args:
            session_id: The session this feature came from.
            feature_name: Human-readable name of the feature or initiative.
            problem_statement: Short statement of the problem it addresses.
            mode: The session mode when this feature was discussed.
            artifact_content: Full text of any generated artifact for this feature.

        Returns:
            The feature row ID.
        """
        now = _now()
        normalized = _normalize_name(feature_name)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions(id, created_at, summary) VALUES (?, ?, '')",
                (session_id, now),
            )
            # Upsert: if same (session_id, normalized_name) exists, update content
            existing = conn.execute(
                "SELECT id FROM features WHERE session_id = ? AND feature_name_normalized = ?",
                (session_id, normalized),
            ).fetchone()
            if existing:
                feature_id = existing[0]
                conn.execute(
                    "UPDATE features SET artifact_content = ?, problem_statement = ? WHERE id = ?",
                    (artifact_content, problem_statement or "", feature_id),
                )
            else:
                feature_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO features
                       (id, session_id, feature_name, feature_name_normalized,
                        problem_statement, mode, artifact_content, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        feature_id,
                        session_id,
                        feature_name,
                        normalized,
                        problem_statement,
                        mode,
                        artifact_content,
                        now,
                    ),
                )
        return feature_id

    def recall_similar_feature(
        self,
        query: str,
        top_k: int = 3,
        exclude_session_id: str | None = None,
    ) -> str:
        """Return a formatted context string of past features relevant to query.

        Uses FTS5 over feature_name + problem_statement. Returns empty string
        if no results. Suitable for injection into the system prompt as
        analogical context.

        Args:
            query: Natural-language description of the current feature/problem.
            top_k: Maximum number of features to surface.
            exclude_session_id: If set, exclude features from this session
                                 (avoids surfacing the current session back).

        Returns:
            Formatted markdown suitable for Layer 6 of the system prompt.
        """
        # Use OR-style query for feature analogue matching: we want broad coverage
        # (any significant term counts) and rely on BM25 for relevance ranking.
        or_query = _fts_query_or(query)
        if not or_query:
            return ""

        with self._connect() as conn:
            if exclude_session_id:
                sql = """
                    SELECT f.feature_name, f.problem_statement, f.mode,
                           f.artifact_content, f.created_at
                    FROM features_fts fts
                    JOIN features f ON f.rowid = fts.rowid
                    WHERE features_fts MATCH ? AND f.session_id != ?
                    ORDER BY bm25(features_fts)
                    LIMIT ?
                """
                rows = conn.execute(sql, (or_query, exclude_session_id, top_k)).fetchall()
            else:
                sql = """
                    SELECT f.feature_name, f.problem_statement, f.mode,
                           f.artifact_content, f.created_at
                    FROM features_fts fts
                    JOIN features f ON f.rowid = fts.rowid
                    WHERE features_fts MATCH ?
                    ORDER BY bm25(features_fts)
                    LIMIT ?
                """
                rows = conn.execute(sql, (or_query, top_k)).fetchall()

        if not rows:
            return ""

        lines = ["## Analogous Past Features\n"]
        for name, problem, mode, artifact, created_at in rows:
            lines.append(f"### {name}  _(mode: {mode}, {created_at[:10]})_")
            if problem:
                lines.append(f"Problem: {problem}")
            if artifact:
                # Include only a brief excerpt to avoid overwhelming the context window
                excerpt = artifact[:600].rstrip()
                if len(artifact) > 600:
                    excerpt += " …[truncated]"
                lines.append(f"\nArtifact excerpt:\n```\n{excerpt}\n```")
            lines.append("")

        return "\n".join(lines)

    def lookup_feature_outcome(
        self,
        feature_name: str,
        fuzzy: bool = True,
    ) -> str:
        """Look up a specific past feature by name and return its full record.

        Used by RETROSPECT mode to surface the prior spec for a named feature.
        Tries exact normalized match first; if fuzzy=True, falls back to FTS.

        Args:
            feature_name: Name to look up (exact or approximate).
            fuzzy: If True, fall back to FTS search when exact match fails.

        Returns:
            Formatted markdown with the feature's stored artifact and crystal
            items from its session. Empty string if not found.
        """
        normalized = _normalize_name(feature_name)
        with self._connect() as conn:
            # Exact normalized match (most recent if multiple)
            row = conn.execute(
                """SELECT f.id, f.feature_name, f.problem_statement, f.mode,
                          f.artifact_content, f.session_id, f.created_at
                   FROM features f
                   WHERE f.feature_name_normalized = ?
                   ORDER BY f.created_at DESC
                   LIMIT 1""",
                (normalized,),
            ).fetchone()

            if row is None and fuzzy:
                safe_query = _sanitize_fts_query(feature_name)
                if safe_query:
                    row = conn.execute(
                        """SELECT f.id, f.feature_name, f.problem_statement, f.mode,
                                  f.artifact_content, f.session_id, f.created_at
                           FROM features_fts fts
                           JOIN features f ON f.rowid = fts.rowid
                           WHERE features_fts MATCH ?
                           ORDER BY bm25(features_fts)
                           LIMIT 1""",
                        (safe_query,),
                    ).fetchone()

            if row is None:
                return ""

            _fid, fname, problem, mode, artifact, session_id, created_at = (
                row[0], row[1], row[2], row[3], row[4], row[5], row[6]
            )

            # Fetch crystal items for the session
            crystal_rows = conn.execute(
                """SELECT kind, text, confidence FROM crystal_items
                   WHERE session_id = ?
                   ORDER BY kind, confidence DESC""",
                (session_id,),
            ).fetchall()

        lines = [f"## Prior Spec: {fname}  _(mode: {mode}, {created_at[:10]})_\n"]
        if problem:
            lines.append(f"**Problem:** {problem}\n")
        if artifact:
            lines.append("**Artifact:**\n```\n" + artifact + "\n```\n")
        if crystal_rows:
            lines.append("**Session Learnings:**")
            for kind, text, conf in crystal_rows:
                conf_str = f" ({conf:.0%})" if conf < 0.9 else ""
                lines.append(f"- [{kind.upper()}]{conf_str} {text}")

        return "\n".join(lines)

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
    """Remove FTS5 special characters to prevent parse errors.

    Returns a sanitized AND-style FTS5 query (default FTS5 behavior).
    Use _fts_query_or() for OR-style matching across multiple terms.
    """
    import re
    # Keep alphanumerics, spaces, hyphens
    cleaned = re.sub(r'[^\w\s\-]', ' ', query, flags=re.UNICODE)
    return cleaned.strip()


def _fts_query_or(query: str) -> str:
    """Convert a multi-word query to FTS5 OR form for broad matching.

    Used by recall_similar_feature() where we want any matching term
    to contribute (BM25 ranking handles relevance weighting).

    Single-word queries are returned as-is.
    Terms shorter than 3 chars are dropped as stop-word-like noise.
    """
    import re
    cleaned = re.sub(r'[^\w\s\-]', ' ', query, flags=re.UNICODE)
    tokens = [t for t in cleaned.split() if len(t) >= 3]
    if not tokens:
        return ""
    if len(tokens) == 1:
        return tokens[0]
    return " OR ".join(tokens)


def generate_session_id() -> str:
    """Generate a new unique session ID."""
    return str(uuid.uuid4())


def _normalize_name(name: str) -> str:
    """Normalize a feature name for exact-match lookup.

    Lowercases, strips punctuation, and collapses whitespace so that
    "BingePass Borrow Limit UI" and "bingepass borrow limit ui" resolve
    to the same key.
    """
    import re as _re
    lowered = name.lower()
    no_punct = _re.sub(r"[^\w\s]", " ", lowered)
    return _re.sub(r"\s+", " ", no_punct).strip()
