"""Regression tests for how ``auto_detect_parser`` picks a parser.

The function tested substrings against ``str(file_path.parent)`` -- the whole
absolute path -- so any directory whose name merely *contained* an agent name
selected that agent's parser::

    /srv/hermes-data/plain.jsonl  ->  parse_hermes_log

``parse_hermes_log`` then looked for ``## Session:`` markers in a Claude Code
JSONL file, found none, and ``context-bridge index`` reported success while the
session was never stored. Routing to the wrong parser is silent data loss one
level up from the corrupt-line case #117 fixed.

What actually identifies the format is the content, so these tests pin the
content-first contract:

* a JSONL/JSON marker in the file picks the parser regardless of the path,
* a whole path component naming an agent directory (``~/.hermes``, ``.claude``)
  is the fallback when the content says nothing,
* markdown/text is what the Hermes reader handles,
* a JSON file with no marker at all raises instead of falling through to a
  parser that would silently yield nothing.
"""

import json

import pytest

from context_bridge.cli import cli
from context_bridge.parsers import (
    ParserNotDetectedError,
    auto_detect_parser,
    parse_claude_code_jsonl,
    parse_codex_json,
    parse_hermes_log,
    parse_opencode_jsonl,
)

# A Claude Code event: top-level "type", no "entries".
CLAUDE_EVENT = {
    "type": "assistant",
    "timestamp": "2026-10-01T00:00:00Z",
    "session_id": "s1",
    "cwd": "/test",
    "message": {"role": "assistant", "content": "Use SQLite for the index."},
}

# An OpenCode line: a "message" object and no "type".
OPENCODE_EVENT = {
    "id": "msg_1",
    "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
}

# A Codex session: one JSON document with an "entries" list.
CODEX_SESSION = {
    "session_id": "s1",
    "project_path": "/test",
    "timestamp": "2026-10-01T00:00:00Z",
    "entries": [{"content": "Use SQLite for the index."}],
}


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload)
    elif isinstance(payload, list):
        path.write_text("".join(json.dumps(item) + "\n" for item in payload))
    else:
        path.write_text(json.dumps(payload) + "\n")
    return path


# The false positive from the report: a directory named after something else
# that happens to contain "hermes". The content is Claude Code, so Claude Code
# must win.
@pytest.mark.parametrize(
    "path,parser",
    [
        ("/srv/hermes-data/plain.jsonl", parse_claude_code_jsonl),
        ("/opt/hermes/queue.jsonl", parse_claude_code_jsonl),
        ("/tmp/claude-tools/run.log.jsonl", parse_claude_code_jsonl),
        ("/srv/hermes-data/opencode.jsonl", parse_opencode_jsonl),
        ("/srv/hermes-data/codex.json", parse_codex_json),
    ],
)
def test_parent_path_substring_does_not_route(tmp_path, path, parser):
    """A `hermes-data`-style directory must not select the Hermes parser."""
    relative = path.lstrip("/")
    suffix = path.rsplit(".", 1)[1]
    payload = {"jsonl": [CLAUDE_EVENT], "log": [CLAUDE_EVENT], "json": CODEX_SESSION}
    if path.endswith("opencode.jsonl"):
        payload["jsonl"] = [OPENCODE_EVENT]
    f = _write(tmp_path / relative, payload[suffix])

    assert auto_detect_parser(f) is parser


@pytest.mark.parametrize(
    "path,parser",
    [
        ("/home/u/.hermes/sessions/2026-10-01.md", parse_hermes_log),
        ("/home/u/.claude/projects/proj/session.jsonl", parse_claude_code_jsonl),
        ("/home/u/.codex/sessions/sess.json", parse_codex_json),
        ("/home/u/.local/share/opencode/storage/s.jsonl", parse_opencode_jsonl),
    ],
)
def test_real_agent_directories_still_route(tmp_path, path, parser):
    """No over-correction: a real agent directory still routes to its parser."""
    relative = path.lstrip("/")
    if path.endswith(".md"):
        f = _write(tmp_path / relative, "## Session: s1\nhello\n")
    elif path.endswith(".json"):
        f = _write(tmp_path / relative, CODEX_SESSION)
    elif "opencode" in path:
        f = _write(tmp_path / relative, [OPENCODE_EVENT])
    else:
        f = _write(tmp_path / relative, [CLAUDE_EVENT])

    assert auto_detect_parser(f) is parser


def test_markdown_and_text_are_read_by_the_hermes_parser(tmp_path):
    """Plain text is what parse_hermes_log handles, whatever the directory."""
    for name in ("notes.md", "run.log", "transcript"):
        f = _write(tmp_path / "srv" / "data" / name, "## Session: s1\nhello\n")
        assert auto_detect_parser(f) is parse_hermes_log


@pytest.mark.parametrize(
    "name,payload",
    [
        ("notes.json", '{"hello": "world"}'),
        ("events.jsonl", '{"event": "ping"}\n'),
        ("session.json", '[{"entries": []}]'),
        ("broken.jsonl", "not json at all\n"),
        ("empty.jsonl", ""),
    ],
)
def test_unmarked_json_raises_instead_of_guessing(tmp_path, name, payload):
    """Ambiguous input must fail loudly, never land on a default parser."""
    f = _write(tmp_path / "srv" / "data" / name, payload)

    with pytest.raises(ParserNotDetectedError, match="could not detect"):
        auto_detect_parser(f)


def test_index_stores_a_session_under_a_false_positive_directory(tmp_path):
    """End to end: the session that used to vanish is indexed."""
    from click.testing import CliRunner

    f = _write(tmp_path / "hermes-data" / "plain.jsonl", [CLAUDE_EVENT])
    db = tmp_path / "index.db"

    result = CliRunner().invoke(cli, ["--db", str(db), "index", str(f.parent)])

    assert result.exit_code == 0, result.output
    assert "Indexed 1 sessions" in result.output

    from context_bridge.store import MemoryStore

    store = MemoryStore(db)
    try:
        assert store.get_stats()["total_sessions"] == 1
    finally:
        store.close()


def test_index_reports_files_it_could_not_route(tmp_path):
    """An unroutable file is named in the output, not swallowed."""
    from click.testing import CliRunner

    _write(tmp_path / "data" / "notes.json", {"hello": "world"})
    db = tmp_path / "index.db"

    result = CliRunner().invoke(cli, ["--db", str(db), "index", str(tmp_path / "data")])

    assert result.exit_code == 0, result.output
    assert "could not detect" in result.output
