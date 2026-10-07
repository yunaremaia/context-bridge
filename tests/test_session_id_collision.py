"""Tests for session_id collision fix (issue #119)."""
import json
from pathlib import Path

from context_bridge.models import Session
from context_bridge.parsers import (
    parse_claude_code_jsonl,
    parse_hermes_log,
    parse_opencode_jsonl,
)
from context_bridge.store import MemoryStore


def test_same_basename_different_dirs_both_indexed(tmp_path):
    """Two files with same basename in different dirs must both be indexed."""
    dir_a = tmp_path / "work" / "api"
    dir_b = tmp_path / "work" / "web"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    # Create two JSONL files with the same basename
    file_a = dir_a / "session.jsonl"
    file_b = dir_b / "session.jsonl"

    event_a = {
        "type": "assistant",
        "timestamp": "2026-01-01T00:00:00Z",
        "message": {"content": [{"type": "text", "text": "API session"}]},
    }
    event_b = {
        "type": "assistant",
        "timestamp": "2026-01-01T00:00:00Z",
        "message": {"content": [{"type": "text", "text": "Web session"}]},
    }

    file_a.write_text(json.dumps(event_a) + "\n")
    file_b.write_text(json.dumps(event_b) + "\n")

    store = MemoryStore(tmp_path / "test.db")

    sessions_a = list(parse_claude_code_jsonl(file_a))
    sessions_b = list(parse_claude_code_jsonl(file_b))

    # Both should have different session_ids
    assert sessions_a[0].session_id != sessions_b[0].session_id

    # Both should be indexed
    for s in sessions_a + sessions_b:
        if not store.is_indexed(s.session_id):
            store.add_session(s)
            store.mark_indexed(s.session_id)

    # Both should be recoverable
    assert store.is_indexed(sessions_a[0].session_id)
    assert store.is_indexed(sessions_b[0].session_id)

    store.close()


def test_add_session_returns_zero_for_duplicate(tmp_path):
    """add_session must return 0 when INSERT OR IGNORE skips a duplicate."""
    store = MemoryStore(tmp_path / "test.db")

    session = Session(
        session_id="dup-test",
        agent="claude",
        project_path="/test",
        file_path="/test/session.jsonl",
        content="test content",
        indexed=False,
    )

    rowid1 = store.add_session(session)
    assert rowid1 > 0

    rowid2 = store.add_session(session)
    assert rowid2 == 0

    store.close()


def test_claude_fallback_uses_resolved_path(tmp_path):
    """parse_claude_code_jsonl fallback session_id uses resolved path."""
    f = tmp_path / "subdir" / "session.jsonl"
    f.parent.mkdir()
    # No session_id in data — triggers fallback
    event = {
        "type": "assistant",
        "timestamp": "2026-01-01T00:00:00Z",
        "message": {"content": [{"type": "text", "text": "hello"}]},
    }
    f.write_text(json.dumps(event) + "\n")

    sessions = list(parse_claude_code_jsonl(f))
    assert len(sessions) == 1
    assert sessions[0].session_id == f"claude-{f.resolve()}"


def test_opencode_uses_resolved_path(tmp_path):
    """parse_opencode_jsonl uses resolved path as session_id."""
    f = tmp_path / "subdir" / "session.jsonl"
    f.parent.mkdir()
    event = {"message": {"content": [{"type": "text", "text": "hello"}]}}
    f.write_text(json.dumps(event) + "\n")

    sessions = list(parse_opencode_jsonl(f))
    assert len(sessions) == 1
    assert sessions[0].session_id == str(f.resolve())


def test_hermes_fallback_uses_resolved_path(tmp_path):
    """parse_hermes_log fallback (no session markers) uses resolved path."""
    f = tmp_path / "subdir" / "session.log"
    f.parent.mkdir()
    f.write_text("Just some log content without session markers.\n")

    sessions = list(parse_hermes_log(f))
    assert len(sessions) == 1
    assert sessions[0].session_id == str(f.resolve())
