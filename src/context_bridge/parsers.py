"""Parsers for different AI agent session logs."""

import json
import re
import warnings
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from .models import Session


def extract_text_content(content) -> list[str]:
    """Return the text fragments of a message ``content`` value.

    ``content`` is a list of blocks in most events, but a plain string is also
    valid and common for short replies. Iterating a string yields characters,
    so the string case is handled explicitly instead of being walked as blocks.
    Non-text blocks (tool calls, images) are dropped.
    """
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []

    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return parts


def parse_claude_code_jsonl(
    file_path: Path, agent: str = "claude"
) -> Iterator[Session]:
    """Parse Claude Code JSONL session logs."""
    with open(file_path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                # A half-written trailing line is normal for a third-party
                # writer that got killed, so keep parsing -- but say what was
                # dropped. Skipping corruption with no trace is what let `index`
                # report "no sessions found" for a file that had some.
                warnings.warn(
                    f"{file_path}:{line_num}: skipping unparsable JSONL line: {exc}",
                    stacklevel=2,
                )
                continue

            # Skip non-dict top-level elements (e.g. JSON arrays)
            if not isinstance(data, dict):
                continue

            # Claude Code stores events with type "user" or "assistant"
            event_type = data.get("type", "")
            if event_type not in ("user", "assistant"):
                continue

            timestamp = data.get("timestamp", datetime.now(tz=timezone.utc).isoformat())
            session_id = data.get("session_id", f"claude-{file_path.resolve()}")
            project_path = data.get("cwd", str(file_path.parent))

            # Extract text content from messages
            content_parts = []
            message = data.get("message", {})
            if isinstance(message, dict):
                content_parts = extract_text_content(message.get("content"))
            content = "\n".join(content_parts)
            if not content.strip():
                content = json.dumps(data, ensure_ascii=False)

            yield Session(
                session_id=session_id,
                agent=agent,
                project_path=project_path,
                file_path=str(file_path),
                content=content[:10000],  # Cap per-event size
                indexed=False,
                created_at=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
            )


def parse_codex_json(file_path: Path, agent: str = "codex") -> Iterator[Session]:
    """Parse Codex JSON session logs."""
    with open(file_path) as f:
        data = json.load(f)

    # Skip non-dict top-level elements (e.g. JSON arrays)
    if not isinstance(data, dict):
        return

    session_id = data.get("session_id", str(file_path.resolve()))
    project_path = data.get("project_path", str(file_path.parent))
    timestamp = data.get("timestamp", datetime.now(tz=timezone.utc).isoformat())

    for entry in data.get("entries", []):
        content = entry.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        yield Session(
            session_id=session_id,
            agent=agent,
            project_path=project_path,
            file_path=str(file_path),
            content=str(content)[:10000],
            indexed=False,
            created_at=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
        )


def parse_opencode_jsonl(file_path: Path, agent: str = "opencode") -> Iterator[Session]:
    """Parse OpenCode JSONL session logs."""
    session_id = str(file_path.resolve())
    with open(file_path) as f:
        content_parts = []
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                # Same contract as parse_claude_code_jsonl: keep the good lines,
                # but never drop a corrupt one without naming it.
                warnings.warn(
                    f"{file_path}:{line_num}: skipping unparsable JSONL line: {exc}",
                    stacklevel=2,
                )
                continue

            # Skip non-dict top-level elements (e.g. JSON arrays)
            if not isinstance(data, dict):
                continue
            msg = data.get("message", {})
            if isinstance(msg, dict):
                content_parts.extend(extract_text_content(msg.get("content")))
        content = "\n".join(content_parts)
        if content.strip():
            yield Session(
                session_id=session_id,
                agent=agent,
                project_path=str(file_path.parent),
                file_path=str(file_path),
                content=content[:10000],
                indexed=False,
            )


def parse_hermes_log(file_path: Path, agent: str = "hermes") -> Iterator[Session]:
    """Parse Hermes agent session logs (markdown/text format)."""
    content = file_path.read_text(errors="replace")
    # Split by session markers
    sessions = re.split(r"(?:^|\n)## Session: (.+?)\n", content)
    if len(sessions) <= 1:
        yield Session(
            session_id=str(file_path.resolve()),
            agent=agent,
            project_path=str(file_path.parent),
            file_path=str(file_path),
            content=content[:10000],
            indexed=False,
        )
    else:
        for i in range(1, len(sessions), 2):
            session_id = sessions[i].strip()
            body = sessions[i + 1] if i + 1 < len(sessions) else ""
            yield Session(
                session_id=session_id,
                agent=agent,
                project_path=str(file_path.parent),
                file_path=str(file_path),
                content=body[:10000],
                indexed=False,
            )


class ParserNotDetectedError(Exception):
    """No agent format could be recognised for a file."""


# Extensions whose content is JSON, and therefore decides the format.
_JSON_SUFFIXES = frozenset({".json", ".jsonl"})


def _json_head(file_path: Path) -> dict | None:
    """Return the file's first JSON object, or None if there is none.

    A ``.json`` file holds one document, so it is read whole; a ``.jsonl`` file
    is read line by line, and its first object is the one that identifies the
    writer.
    """
    try:
        if file_path.suffix.lower() == ".json":
            text = file_path.read_text(errors="replace")
        else:
            with open(file_path) as f:
                text = next((line for line in f if line.strip()), "")
    except OSError:
        return None

    if not text.strip():
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def auto_detect_parser(file_path: Path):
    """Detect agent type from file content and return the appropriate parser.

    The format marker lives inside the file. The path is not a signal: matching
    a substring of the absolute path routed ``/srv/hermes-data/plain.jsonl`` to
    the Hermes parser, and matching a whole path component only moves the same
    false positive one level up (anything under ``/root/.hermes/`` matched, even
    a file another agent wrote into a scratch directory). Every format below is
    fully described by its own markers, so the content decides alone, and an
    unmarked JSON file raises instead of being handed to a parser that would
    read it, find nothing and let the session go silently unindexed.
    """
    if file_path.suffix.lower() not in _JSON_SUFFIXES:
        # Markdown/text: the Hermes reader is the only one that handles it.
        return parse_hermes_log

    data = _json_head(file_path)
    if data is not None:
        # Claude Code events carry a top-level "type", OpenCode lines only ever
        # carry a "message", and a Codex session carries an "entries" list.
        if data.get("type") in ("user", "assistant"):
            return parse_claude_code_jsonl
        if isinstance(data.get("entries"), list):
            return parse_codex_json
        if isinstance(data.get("message"), dict):
            return parse_opencode_jsonl

    raise ParserNotDetectedError(
        f"{file_path}: could not detect a session format from its content. "
        f"Call the parser for this agent directly instead."
    )
