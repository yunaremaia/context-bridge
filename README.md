# context-bridge — Universal Session Memory for AI Agents

**Capture. Index. Retrieve.** A local-first context layer that works with any AI coding agent.

![PyPI](https://badge.fury.io/py/context-bridge)
![CI](https://github.com/yunaremaia/context-bridge/workflows/CI/badge.svg) ![License](https://img.shields.io/endpoint?url=https://img.shields.io/licenses/MIT) ![Stars](https://img.shields.io/github/stars/yunaremaia/context-bridge)

---

## The Problem

Every AI coding agent (Claude Code, Codex, OpenCode, Hermes, Aider) forgets everything between sessions. You re-explain your project, re-state architecture decisions, and re-teach preferences every single time. Existing solutions are locked to one agent or require manual maintenance.

## The Solution

`context-bridge` is a universal, local-first memory layer that:

- **Captures** sessions from any agent automatically
- **Indexes** decisions, patterns, lessons in a local SQLite database
- **Retrieves** relevant context when you start a new session
- **Works with** Claude Code, Codex, OpenCode, Hermes, Aider — anything that writes logs

No cloud. No API keys. No vendor lock-in.

## Quick Start

```bash
pip install context-bridge

# Initialize in your project
context-bridge init

# Index existing agent sessions
context-bridge index ~/.claude/projects/

# Query memory
context-bridge recall "How did we handle authentication?"

# Inject context into new session
context-bridge inject --agent claude
```

## Architecture

```
~/.context-bridge/
├── sessions/           # Captured session transcripts
├── index.db            # SQLite FTS + metadata
├── memories/           # Consolidated memories
└── config.yaml         # Per-project config
```

## Why Now?

- 67k+ MCP servers deployed, AI agents everywhere
- No open-source universal memory layer exists
- Show HN validation: hmem, Engram, Memobase all trending
- Every developer using AI agents has this problem

## License

MIT
