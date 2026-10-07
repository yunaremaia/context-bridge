"""SQLite-backed memory store with full-text search."""

import sqlite3
from datetime import datetime
from pathlib import Path

from .models import Memory, MemoryType, Query, Session

FTS5_OPERATORS = frozenset({"AND", "OR", "NOT"})


def _quote_fts5_token(token: str) -> str:
    """Wrap a token as an inert FTS5 string literal."""
    return '"' + token.replace('"', '""') + '"'


def _collapse_operator_runs(tokens: list[str]) -> list[str]:
    """Reduce each run of adjacent operators to a single operator.

    FTS5 accepts a bare operator only between two operands, so ``a AND NOT b``
    would otherwise become ``"a" AND NOT "b"`` and raise a syntax error. FTS5's
    ``NOT`` is already an AND-NOT, so it subsumes any operator it follows.
    """
    collapsed: list[str] = []
    for token in tokens:
        if token in FTS5_OPERATORS and collapsed and collapsed[-1] in FTS5_OPERATORS:
            if token == "NOT":
                collapsed[-1] = "NOT"
            continue
        collapsed.append(token)
    return collapsed


def _sanitize_fts5_query(query: str) -> str:
    """Sanitize FTS5 input while preserving supported query syntax.

    Every token is emitted either as an inert quoted string or as a bare
    operator/prefix in a position where FTS5 accepts one, so the result is
    always syntactically valid and cannot be used to alter the surrounding
    query. This is the single sanitizer used by every search path.
    """
    tokens = []
    current = []
    in_quote = False

    for char in query:
        if char == '"':
            current.append(char)
            in_quote = not in_quote
        elif char.isspace() and not in_quote:
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(char)

    if current:
        tokens.append("".join(current))

    tokens = _collapse_operator_runs(tokens)
    sanitized = []

    for index, token in enumerate(tokens):
        if token in FTS5_OPERATORS:
            has_operand_before = index > 0 and tokens[index - 1] not in FTS5_OPERATORS
            has_operand_after = (
                index < len(tokens) - 1 and tokens[index + 1] not in FTS5_OPERATORS
            )
            # A bare operator is only valid with an operand on both sides.
            sanitized.append(
                token
                if has_operand_before and has_operand_after
                else _quote_fts5_token(token)
            )
        elif len(token) >= 2 and token.startswith('"') and token.endswith('"'):
            sanitized.append(_quote_fts5_token(token[1:-1]))
        else:
            stem = token[:-1] if token.endswith("*") else ""
            is_prefix = bool(stem) and stem.replace("_", "").isalnum()
            # AND*/OR*/NOT* are rejected by FTS5, so reserved words stay quoted.
            if is_prefix and stem.upper() not in FTS5_OPERATORS:
                sanitized.append(token)
            else:
                sanitized.append(_quote_fts5_token(token))

    return " ".join(sanitized)


class MemoryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                memory_type TEXT NOT NULL,
                source_agent TEXT NOT NULL,
                session_id TEXT NOT NULL,
                project_path TEXT NOT NULL,
                relevance_score REAL DEFAULT 0.0,
                importance REAL DEFAULT 0.5,
                access_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                agent TEXT NOT NULL,
                project_path TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content TEXT NOT NULL,
                indexed BOOLEAN DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                content='memories',
                content_rowid='id',
                tokenize='porter'
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent);
            CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
            CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_path);
        """)
        self.conn.commit()

    def add_memory(self, memory: Memory) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO memories (content, memory_type, source_agent, session_id,
                                  project_path, relevance_score, importance,
                                  access_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                memory.content,
                memory.memory_type.value,
                memory.source_agent,
                memory.session_id,
                memory.project_path,
                memory.relevance_score,
                memory.importance,
                memory.access_count,
                memory.created_at.isoformat(),
                memory.updated_at.isoformat(),
            ),
        )
        rowid = cur.lastrowid or 0
        self.conn.execute(
            """
            INSERT INTO memories_fts(rowid, content) VALUES (?, ?)
        """,
            (rowid, memory.content),
        )
        self.conn.commit()
        return rowid

    def add_session(self, session: Session) -> int:
        existing = self.conn.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?", (session.session_id,)
        ).fetchone()
        if existing:
            return 0
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO sessions (session_id, agent, project_path,
                                           file_path, content, indexed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                session.session_id,
                session.agent,
                session.project_path,
                session.file_path,
                session.content,
                session.indexed,
                session.created_at.isoformat(),
            ),
        )
        self.conn.commit()
        return cur.lastrowid or 0

    def search(self, query: Query) -> list[Memory]:
        sanitized = _sanitize_fts5_query(query.text)
        if not sanitized:
            return []

        sql = """
            SELECT m.* FROM memories m
            JOIN memories_fts f ON m.id = f.rowid
            WHERE memories_fts MATCH ?
        """
        params: list = [sanitized]

        if query.agent:
            sql += " AND m.source_agent = ?"
            params.append(query.agent)
        if query.memory_type:
            sql += " AND m.memory_type = ?"
            params.append(query.memory_type.value)

        sql += " ORDER BY m.importance DESC, m.relevance_score DESC LIMIT ?"
        params.append(query.limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [
            Memory(
                id=r["id"],
                content=r["content"],
                memory_type=MemoryType(r["memory_type"]),
                source_agent=r["source_agent"],
                session_id=r["session_id"],
                project_path=r["project_path"],
                relevance_score=r["relevance_score"],
                importance=r["importance"],
                access_count=r["access_count"],
                created_at=datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.fromisoformat(r["updated_at"]),
            )
            for r in rows
        ]

    def mark_indexed(self, session_id: str):
        self.conn.execute(
            "UPDATE sessions SET indexed = 1 WHERE session_id = ?", (session_id,)
        )
        self.conn.commit()

    def is_indexed(self, session_id: str) -> bool:
        row = self.conn.execute(
            "SELECT indexed FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return bool(row and row["indexed"])

    def get_stats(self) -> dict:
        memories = self.conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()[
            "c"
        ]
        sessions = self.conn.execute("SELECT COUNT(*) as c FROM sessions").fetchone()[
            "c"
        ]
        agents = self.conn.execute("SELECT DISTINCT agent FROM sessions").fetchall()
        return {
            "total_memories": memories,
            "total_sessions": sessions,
            "agents": [a["agent"] for a in agents],
        }

    def close(self):
        self.conn.close()
