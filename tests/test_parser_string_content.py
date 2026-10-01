"""Regression tests for string-valued message content in the session parsers.

Both JSONL parsers assumed ``message["content"]`` is always a list of content
blocks. Claude Code also emits it as a plain string, which is what most single
turn tool replies look like::

    {"message": {"role": "assistant", "content": "The deploy uses rsync."}}

Iterating a string yields its characters, so every character was collected as
its own "text block" and joined with newlines. The indexed memory became one
letter per line, which no FTS5 query can match -- the session was silently
unsearchable and unreadable.

These tests pin both halves of the contract: the parser must return the text
intact, and a memory indexed from it must be findable by FTS5.
"""

import json

import pytest

from context_bridge.models import Memory, MemoryType, Query
from context_bridge.parsers import parse_claude_code_jsonl, parse_opencode_jsonl
from context_bridge.store import MemoryStore

# Chosen because a per-character result is obviously wrong: any word longer than
# one character is unsearchable, and the text is unreadable.
SENTENCE = "The deploy script uses rsync not scp."


def _write_jsonl(path, event):
    path.write_text(json.dumps(event) + "\n")
    return path


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "index.db")
    yield s
    s.close()


class TestClaudeCodeStringContent:
    def test_string_content_is_preserved_intact(self, tmp_path):
        f = _write_jsonl(
            tmp_path / "session.jsonl",
            {
                "type": "assistant",
                "timestamp": "2026-01-01T00:00:00Z",
                "session_id": "s1",
                "cwd": "/test",
                "message": {"role": "assistant", "content": SENTENCE},
            },
        )
        sessions = list(parse_claude_code_jsonl(f))
        assert len(sessions) == 1
        assert sessions[0].content == SENTENCE

    def test_string_content_is_not_split_per_character(self, tmp_path):
        """Guards the exact regression: no newlines between characters."""
        f = _write_jsonl(
            tmp_path / "session.jsonl",
            {
                "type": "assistant",
                "timestamp": "2026-01-01T00:00:00Z",
                "session_id": "s1",
                "cwd": "/test",
                "message": {"content": SENTENCE},
            },
        )
        assert "\n" not in next(iter(parse_claude_code_jsonl(f))).content

    def test_string_content_stays_searchable(self, tmp_path, store):
        f = _write_jsonl(
            tmp_path / "session.jsonl",
            {
                "type": "assistant",
                "timestamp": "2026-01-01T00:00:00Z",
                "session_id": "s1",
                "cwd": "/test",
                "message": {"content": SENTENCE},
            },
        )
        session = next(iter(parse_claude_code_jsonl(f)))
        store.add_memory(
            Memory(
                content=session.content,
                memory_type=MemoryType.DECISION,
                source_agent=session.agent,
                session_id=session.session_id,
                project_path=session.project_path,
            )
        )
        for word in ("deploy", "rsync", "scp"):
            assert store.search(Query(text=word)), f"'{word}' must match"

    def test_block_content_still_works(self, tmp_path):
        """The list-of-blocks form must keep behaving exactly as before."""
        f = _write_jsonl(
            tmp_path / "session.jsonl",
            {
                "type": "assistant",
                "timestamp": "2026-01-01T00:00:00Z",
                "session_id": "s1",
                "cwd": "/test",
                "message": {
                    "content": [
                        {"type": "text", "text": "Use SQLite"},
                        {"type": "tool_use", "id": "t1", "name": "Bash"},
                    ]
                },
            },
        )
        assert next(iter(parse_claude_code_jsonl(f))).content == "Use SQLite"

    def test_mixed_blocks_and_string_are_joined(self, tmp_path):
        """A string entry inside the block list is kept, non-text is dropped."""
        f = _write_jsonl(
            tmp_path / "session.jsonl",
            {
                "type": "assistant",
                "timestamp": "2026-01-01T00:00:00Z",
                "session_id": "s1",
                "cwd": "/test",
                "message": {"content": ["first", {"type": "text", "text": "second"}]},
            },
        )
        assert next(iter(parse_claude_code_jsonl(f))).content == "first\nsecond"

    def test_empty_content_falls_back_to_raw_event(self, tmp_path):
        """A tool-only event has no text, so the raw JSON is stored instead."""
        event = {
            "type": "assistant",
            "timestamp": "2026-01-01T00:00:00Z",
            "session_id": "s1",
            "cwd": "/test",
            "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash"}]},
        }
        f = _write_jsonl(tmp_path / "session.jsonl", event)
        content = next(iter(parse_claude_code_jsonl(f))).content
        assert "tool_use" in content
        assert SENTENCE not in content

    def test_missing_message_key_does_not_raise(self, tmp_path):
        event = {
            "type": "assistant",
            "timestamp": "2026-01-01T00:00:00Z",
            "session_id": "s1",
            "cwd": "/test",
        }
        f = _write_jsonl(tmp_path / "session.jsonl", event)
        content = next(iter(parse_claude_code_jsonl(f))).content
        assert json.loads(content) == event


class TestOpencodeStringContent:
    def test_string_content_is_preserved_intact(self, tmp_path):
        f = _write_jsonl(
            tmp_path / "opencode-session.jsonl",
            {"message": {"content": SENTENCE}},
        )
        sessions = list(parse_opencode_jsonl(f))
        assert len(sessions) == 1
        assert sessions[0].content == SENTENCE

    def test_string_content_is_not_split_per_character(self, tmp_path):
        f = _write_jsonl(
            tmp_path / "opencode-session.jsonl",
            {"message": {"content": SENTENCE}},
        )
        assert "\n" not in next(iter(parse_opencode_jsonl(f))).content

    def test_block_content_still_works(self, tmp_path):
        f = _write_jsonl(
            tmp_path / "opencode-session.jsonl",
            {"message": {"content": [{"type": "text", "text": "Use SQLite"}]}},
        )
        assert next(iter(parse_opencode_jsonl(f))).content == "Use SQLite"
