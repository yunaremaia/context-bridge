"""SQLite-backed memory store with full-text search."""
import sqlite3
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

from .models import Memory, MemoryType, Session, Query


def _sanitize_fts5_query(query: str) -> str:
    """Sanitize FTS5 input while preserving supported query syntax."""
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

    sanitized = []

    for index, token in enumerate(tokens):
        if (
            token in {"AND", "OR", "NOT"}
            and index > 0
            and index < len(tokens) - 1
        ):
            sanitized.append(token)
        elif token.startswith('"') and token.endswith('"') and len(token) >= 2:
            phrase = token[1:-1].replace('"', '""')
            sanitized.append(f'"{phrase}"')
        elif token.endswith("*") and token[:-1].replace("_", "").isalnum():
            sanitized.append(token)
        else:
            sanitized.append(f'"{token.replace(chr(34), chr(34) * 2)}"')

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
        cur = self.conn.execute("""
            INSERT INTO memories (content, memory_type, source_agent, session_id,
                                  project_path, relevance_score, importance,
                                  access_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (memory.content, memory.memory_type.value, memory.source_agent,
              memory.session_id, memory.project_path, memory.relevance_score,
              memory.importance, memory.access_count,
              memory.created_at.isoformat(), memory.updated_at.isoformat()))
        rowid = cur.lastrowid or 0
        self.conn.execute("""
            INSERT INTO memories_fts(rowid, content) VALUES (?, ?)
        """, (rowid, memory.content))
        self.conn.commit()
        return rowid

    def add_session(self, session: Session) -> int:
        cur = self.conn.execute("""
            INSERT OR IGNORE INTO sessions (session_id, agent, project_path,
                                           file_path, content, indexed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session.session_id, session.agent, session.project_path,
              session.file_path, session.content, session.indexed,
              session.created_at.isoformat()))
        self.conn.commit()
        return cur.lastrowid or 0

    @staticmethod
    def _escape_fts5_query(text: str) -> str:
        """Escape special FTS5 characters in user query to prevent query syntax errors."""
        if not text:
            return ""
        clean = re.sub(r'[^\w\s]', ' ', text)
        tokens = []
        for word in clean.split():
            if word:
                tokens.append(f'"{word}"')
        return " ".join(tokens)

    def search(self, query: Query) -> list[Memory]:
        escaped_query = self._escape_fts5_query(query.text)
        if not escaped_query:
            return []

        sql = """
            SELECT m.* FROM memories m
            JOIN memories_fts f ON m.id = f.rowid
            WHERE memories_fts MATCH ?
        """
        params: list = [_sanitize_fts5_query(query.text)]

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
                id=r["id"], content=r["content"], memory_type=MemoryType(r["memory_type"]),
                source_agent=r["source_agent"], session_id=r["session_id"],
                project_path=r["project_path"], relevance_score=r["relevance_score"],
                importance=r["importance"], access_count=r["access_count"],
                created_at=datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.fromisoformat(r["updated_at"]),
            )
            for r in rows
        ]

    def mark_indexed(self, session_id: str):
        self.conn.execute(
            "UPDATE sessions SET indexed = 1 WHERE session_id = ?",
            (session_id,)
        )
        self.conn.commit()

    def is_indexed(self, session_id: str) -> bool:
        row = self.conn.execute(
            "SELECT indexed FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return bool(row and row["indexed"])

    def get_stats(self) -> dict:
        memories = self.conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
        sessions = self.conn.execute("SELECT COUNT(*) as c FROM sessions").fetchone()["c"]
        agents = self.conn.execute(
            "SELECT DISTINCT agent FROM sessions"
        ).fetchall()
        return {
            "total_memories": memories,
            "total_sessions": sessions,
            "agents": [a["agent"] for a in agents],
        }

    def close(self):
        self.conn.close()