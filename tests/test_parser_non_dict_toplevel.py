"""Regression tests for non-dict top-level JSON elements in session parsers.

Every parser assumed the decoded top-level value was a JSON object and called
``.get()`` on it directly. That holds for a well-formed session file, but the
same readers are pointed at arbitrary files under the indexed directory, where a
top-level array, string, number, or ``null`` is entirely legitimate::

    [{"session_id": "s1", "entries": []}]

On such a file the call to ``.get()`` raised ``AttributeError``, which aborted
the whole ``context-bridge index`` run -- one stray exported array took out
indexing for every other file in the directory, not just its own.

These tests pin both halves of the contract:

* the parsers skip a non-dict element and keep going (no exception), and
* valid dict elements in the *same* file are still parsed, so skipping one bad
  element never discards the good ones around it.
"""

import json

import pytest

from context_bridge.parsers import (
    parse_claude_code_jsonl,
    parse_codex_json,
    parse_opencode_jsonl,
)

# A valid event/session, used to prove that neighbouring valid dicts survive.
VALID_EVENT = {
    "type": "assistant",
    "timestamp": "2026-01-01T00:00:00Z",
    "session_id": "s1",
    "cwd": "/test",
    "message": {"role": "assistant", "content": "Use SQLite for the index."},
}

VALID_CODEX = {
    "session_id": "s1",
    "project_path": "/test",
    "timestamp": "2026-01-01T00:00:00Z",
    "entries": [{"content": "Use SQLite for the index."}],
}

# Every non-dict top-level value a JSON document can legally hold.
NON_DICT_PAYLOADS = {
    "array": json.dumps([{"session_id": "s1", "entries": []}]),
    "string": json.dumps("just a string"),
    "number": json.dumps(42),
    "float": json.dumps(3.14),
    "bool": json.dumps(True),
    "null": json.dumps(None),
    "empty_array": json.dumps([]),
}


class TestCodexJson:
    """``parse_codex_json`` reads the whole file with ``json.load``."""

    @pytest.mark.parametrize("case,payload", NON_DICT_PAYLOADS.items())
    def test_non_dict_toplevel_is_skipped_without_raising(
        self, tmp_path, case, payload
    ):
        f = tmp_path / "session.json"
        f.write_text(payload)
        assert list(parse_codex_json(f)) == []

    def test_valid_dict_is_still_parsed(self, tmp_path):
        f = tmp_path / "session.json"
        f.write_text(json.dumps(VALID_CODEX))
        sessions = list(parse_codex_json(f))
        assert len(sessions) == 1
        assert sessions[0].content == "Use SQLite for the index."

    def test_malformed_json_still_raises_for_the_caller_to_skip(self, tmp_path):
        """Malformed JSON stays a JSONDecodeError; the CLI catches it.

        The parser must not swallow genuinely corrupt files -- that would hide
        real data loss behind a silent skip.
        """
        f = tmp_path / "session.json"
        f.write_text("{not json")
        with pytest.raises(json.JSONDecodeError):
            list(parse_codex_json(f))


class TestClaudeCodeJsonl:
    @pytest.mark.parametrize("case,payload", NON_DICT_PAYLOADS.items())
    def test_non_dict_line_is_skipped_without_raising(self, tmp_path, case, payload):
        f = tmp_path / "session.jsonl"
        f.write_text(payload + "\n")
        assert list(parse_claude_code_jsonl(f)) == []

    def test_non_dict_line_does_not_discard_valid_neighbours(self, tmp_path):
        """The reported bug: one array line must not abort the whole file."""
        f = tmp_path / "session.jsonl"
        f.write_text(
            json.dumps(VALID_EVENT)
            + "\n"
            + json.dumps([{"type": "user"}])
            + "\n"
            + json.dumps(VALID_EVENT)
            + "\n"
        )
        sessions = list(parse_claude_code_jsonl(f))
        assert len(sessions) == 2
        assert all(s.content == "Use SQLite for the index." for s in sessions)

    def test_valid_dict_is_still_parsed(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text(json.dumps(VALID_EVENT) + "\n")
        assert len(list(parse_claude_code_jsonl(f))) == 1


class TestOpencodeJsonl:
    @pytest.mark.parametrize("case,payload", NON_DICT_PAYLOADS.items())
    def test_non_dict_line_is_skipped_without_raising(self, tmp_path, case, payload):
        f = tmp_path / "opencode-session.jsonl"
        f.write_text(payload + "\n")
        assert list(parse_opencode_jsonl(f)) == []

    def test_valid_dict_is_still_parsed(self, tmp_path):
        f = tmp_path / "opencode-session.jsonl"
        f.write_text(json.dumps({"message": {"content": "Use SQLite"}}) + "\n")
        sessions = list(parse_opencode_jsonl(f))
        assert len(sessions) == 1
        assert sessions[0].content == "Use SQLite"
