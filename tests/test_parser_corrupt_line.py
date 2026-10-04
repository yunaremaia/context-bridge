"""A corrupt JSONL line must leave a trace.

Both JSONL readers swallowed ``json.JSONDecodeError`` with a bare ``continue``.
Because they are generators consumed inside a ``try/except`` in
``context-bridge index``, a file whose lines were all corrupt indexed as zero
sessions -- indistinguishable from an empty file. The line number was already
being enumerated and thrown away by the linter (B007); it is now reported.

Contract pinned here: the corrupt line is *reported* (warning naming file and
line number), not raised, because a half-written trailing line is routine for a
third-party writer that was killed mid-write, and the valid lines around it
must still index. Raising would hand the CLI's blanket ``except`` a whole file
to discard -- strictly more data loss than before.
"""

import json

import pytest

from context_bridge.parsers import parse_claude_code_jsonl, parse_opencode_jsonl

VALID_CLAUDE_EVENT = {
    "type": "assistant",
    "timestamp": "2026-01-01T00:00:00Z",
    "session_id": "s1",
    "cwd": "/test",
    "message": {"role": "assistant", "content": "Use SQLite for the index."},
}

VALID_OPENCODE_EVENT = {
    "message": {"role": "assistant", "content": "Use SQLite for the index."}
}


def test_corrupt_claude_line_warns_with_line_number_and_keeps_neighbours(tmp_path):
    f = tmp_path / "session.jsonl"
    # Line 3 is corrupt; lines 1, 2 and 4 are valid and must still be indexed.
    f.write_text(
        json.dumps(VALID_CLAUDE_EVENT)
        + "\n"
        + '{"type": "assistant", "message": {"content": "trunca'
        + "\n"
        + json.dumps(VALID_CLAUDE_EVENT)
        + "\n"
    )

    with pytest.warns(UserWarning) as record:
        sessions = list(parse_claude_code_jsonl(f))

    messages = [str(w.message) for w in record]
    assert any(f"{f}:2:" in m for m in messages), messages
    assert any("skipping unparsable JSONL line" in m for m in messages), messages
    # Reporting the bad line must not cost the good ones.
    assert len(sessions) == 2


def test_corrupt_opencode_line_warns_with_line_number(tmp_path):
    f = tmp_path / "opencode-session.jsonl"
    f.write_text(json.dumps(VALID_OPENCODE_EVENT) + "\n" + "not json at all" + "\n")

    with pytest.warns(UserWarning, match=r"skipping unparsable JSONL line"):
        sessions = list(parse_opencode_jsonl(f))

    assert len(sessions) == 1
    assert sessions[0].content == "Use SQLite for the index."
