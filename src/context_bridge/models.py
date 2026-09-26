"""Core data models for context-bridge."""

import enum
from datetime import datetime, timezone

from pydantic import BaseModel


class MemoryType(str, enum.Enum):
    DECISION = "decision"
    PATTERN = "pattern"
    LESSON = "lesson"
    PREFERENCE = "preference"
    ARCHITECTURE = "architecture"


class Memory(BaseModel):
    id: int | None = None
    content: str
    memory_type: MemoryType
    source_agent: str  # claude, codex, opencode, hermes, aider
    session_id: str
    project_path: str
    relevance_score: float = 0.0
    created_at: datetime = datetime.now(tz=timezone.utc)
    updated_at: datetime = datetime.now(tz=timezone.utc)
    access_count: int = 0
    importance: float = 0.5


class Session(BaseModel):
    id: int | None = None
    session_id: str
    agent: str
    project_path: str
    file_path: str
    content: str
    indexed: bool = False
    created_at: datetime = datetime.now(tz=timezone.utc)


class Query(BaseModel):
    text: str
    agent: str | None = None
    memory_type: MemoryType | None = None
    limit: int = 10
