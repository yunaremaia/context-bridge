"""Parsers for different AI agent session logs."""

import json
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from .models import Session


def parse_claude_code_jsonl(
    file_path: Path, agent: str = "claude"
) -> Iterator[Session]:
    """Parse Claude Code JSONL session logs."""
    with open(file_path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Claude Code stores events with type "user" or "assistant"
            event_type = data.get("type", "")
            if event_type not in ("user", "assistant"):
                continue

            timestamp = data.get("timestamp", datetime.now(tz=timezone.utc).isoformat())
            session_id = data.get("session_id", f"claude-{file_path.stem}")
            project_path = data.get("cwd", str(file_path.parent))

            # Extract text content from messages
            content_parts = []
            message = data.get("message", {})
            if isinstance(message, dict):
                for block in message.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        content_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        content_parts.append(block)
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
    with open(file_path, "r") as f:
        data = json.load(f)

    session_id = data.get("session_id", file_path.stem)
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
    session_id = file_path.stem
    with open(file_path, "r") as f:
        content_parts = []
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = data.get("message", {})
            if isinstance(msg, dict):
                for block in msg.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "text":
                        content_parts.append(block.get("text", ""))
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
            session_id=file_path.stem,
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


def auto_detect_parser(file_path: Path):
    """Detect agent type from file path/name and return appropriate parser."""
    name = file_path.name.lower()
    parent = str(file_path.parent).lower()

    if "claude" in parent or ".claude" in parent:
        return parse_claude_code_jsonl
    if "codex" in parent or "codex" in name:
        return parse_codex_json
    if "opencode" in parent or "opencode" in name:
        return parse_opencode_jsonl
    if "hermes" in parent or "hermes" in name:
        return parse_hermes_log
    # Default: try Claude Code format (most common)
    return parse_claude_code_jsonl
