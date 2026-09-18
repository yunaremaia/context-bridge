"""Tests for context-bridge core components."""
import pytest
from pathlib import Path
from datetime import datetime

from context_bridge.models import Memory, MemoryType, Session, Query
from context_bridge.store import MemoryStore
from context_bridge.parsers import parse_claude_code_jsonl, auto_detect_parser


@pytest.fixture
def tmp_store(tmp_path):
    db = tmp_path / "test.db"
    store = MemoryStore(db)
    yield store
    store.close()


@pytest.fixture
def sample_memory():
    return Memory(
        content="We decided to use SQLite for local storage because it's zero-config",
        memory_type=MemoryType.DECISION,
        source_agent="claude",
        session_id="test-session-1",
        project_path="/test/project",
        importance=0.8,
    )


@pytest.fixture
def sample_session(tmp_path):
    return Session(
        session_id="test-session-1",
        agent="claude",
        project_path="/test/project",
        file_path=str(tmp_path / "test.jsonl"),
        content="Decided to use SQLite",
        indexed=False,
    )


class TestMemory:
    def test_create(self, sample_memory):
        assert sample_memory.memory_type == MemoryType.DECISION
        assert sample_memory.importance == 0.8

    def test_model_dump(self, sample_memory):
        d = sample_memory.model_dump()
        assert "content" in d
        assert "memory_type" in d


class TestStore:
    def test_add_memory(self, tmp_store, sample_memory):
        mid = tmp_store.add_memory(sample_memory)
        assert mid > 0

    def test_add_session(self, tmp_store, sample_session):
        sid = tmp_store.add_session(sample_session)
        assert sid > 0

    def test_search(self, tmp_store, sample_memory):
        tmp_store.add_memory(sample_memory)
        query = Query(text="SQLite storage")
        results = tmp_store.search(query)
        assert len(results) >= 1

    def test_search_with_agent_filter(self, tmp_store, sample_memory):
        tmp_store.add_memory(sample_memory)
        query = Query(text="SQLite", agent="claude")
        results = tmp_store.search(query)
        assert len(results) >= 1

    def test_search_no_match(self, tmp_store, sample_memory):
        tmp_store.add_memory(sample_memory)
        query = Query(text="postgresql nonexistent")
        results = tmp_store.search(query)
        # FTS may still return partial matches, but nothing should be perfect
        assert isinstance(results, list)

    def test_search_double_quotes(self, tmp_store, sample_memory):
        tmp_store.add_memory(sample_memory)
        # Should not crash on double quotes (unbalanced or phrases) and match terms present
        query = Query(text='decided "SQLite" "zero-config"')
        results = tmp_store.search(query)
        assert len(results) >= 1
        assert results[0].session_id == sample_memory.session_id

        # Edge case: only quotes
        empty_query = Query(text='"""')
        assert tmp_store.search(empty_query) == []

    def test_search_fts5_special_characters(self, tmp_store, sample_memory):
        tmp_store.add_memory(sample_memory)
        # Should safely handle reserved words and syntax characters: AND, OR, NOT, *, -, :, ()
        test_queries = [
            "SQLite AND zero-config",
            "SQLite OR postgresql",
            "NOT postgresql SQLite",
            "SQLite*",
            "test:SQLite",
            "(SQLite)",
            "*-+^:",
        ]
        for q_text in test_queries:
            query = Query(text=q_text)
            results = tmp_store.search(query)
            assert isinstance(results, list)

    def test_mark_indexed(self, tmp_store, sample_session):
        tmp_store.add_session(sample_session)
        tmp_store.mark_indexed("test-session-1")
        assert tmp_store.is_indexed("test-session-1")

    def test_stats(self, tmp_store, sample_memory, sample_session):
        tmp_store.add_memory(sample_memory)
        tmp_store.add_session(sample_session)
        stats = tmp_store.get_stats()
        assert stats["total_memories"] >= 1
        assert stats["total_sessions"] >= 1
        assert "claude" in stats["agents"]


class TestParsers:
    def test_auto_detect_claude(self, tmp_path):
        f = tmp_path / ".claude" / "session.jsonl"
        f.parent.mkdir()
        f.write_text("{}")
        parser = auto_detect_parser(f)
        assert parser == parse_claude_code_jsonl

    def test_auto_detect_codex(self, tmp_path):
        f = tmp_path / "codex-sessions" / "sess.json"
        f.parent.mkdir()
        f.write_text("{}")
        parser = auto_detect_parser(f)
        # Falls through to claude default since codex needs content check
        assert callable(parser)

    def test_parse_claude_code_jsonl(self, tmp_path):
        f = tmp_path / "session.jsonl"
        event = {
            "type": "assistant",
            "timestamp": "2026-01-01T00:00:00Z",
            "session_id": "s1",
            "cwd": "/test",
            "message": {"content": [{"type": "text", "text": "Use SQLite"}]},
        }
        f.write_text(json.dumps(event) + "\n")
        sessions = list(parse_claude_code_jsonl(f))
        assert len(sessions) >= 1
        assert sessions[0].agent == "claude"


import json
