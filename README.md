# context-bridge — Universal Session Memory for AI Agents

**Capture. Index. Retrieve.** A local-first context layer that works with any AI coding agent.

[![CI](https://github.com/yunaremaia/context-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/yunaremaia/context-bridge/actions) [![License](https://img.shields.io/github/license/yunaremaia/context-bridge)](https://github.com/yunaremaia/context-bridge/blob/main/LICENSE) [![Stars](https://img.shields.io/github/stars/yunaremaia/context-bridge)](https://github.com/yunaremaia/context-bridge) [![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/) [![Release](https://img.shields.io/github/v/release/yunaremaia/context-bridge)](https://github.com/yunaremaia/context-bridge/releases/latest)

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
pip install git+https://github.com/yunaremaia/context-bridge.git

# Initialize in your project
context-bridge init

# Index existing agent sessions
context-bridge index ~/.claude/projects/

# Query memory
context-bridge recall "How did we handle authentication?"

# Inject context into new session
context-bridge inject --agent claude
```

> **Not yet on PyPI.** Install from git with the line above. The command you run
> is `context-bridge`; the distribution name on PyPI is `context-bridge-py`. The
> short `context-bridge` name on PyPI belongs to an unrelated project by another
> author, so it is not used here and never will be.

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

## Sponsoring

`context-bridge` is MIT licensed and free to use. If it earns a permanent place in your setup, you can support continued maintenance via GitHub Sponsors or by sending SOL to the project treasury wallet:

```text
Eeztv1nCYUt1fwGWpzKC948gaWfjejYCAuLtUMgzDWbW
```

Funding platforms are configured in [`.github/FUNDING.yml`](.github/FUNDING.yml).

If this tool is useful to you, a star helps other people find it.

## Related tools

- **[driftcheck](https://github.com/yunaremaia/driftcheck)** — detect version drift between docs and toolchain files
- **[mcp-guard](https://github.com/yunaremaia/mcp-guard)** — audit MCP servers for unsafe permissions
- **[memwatch](https://github.com/yunaremaia/memwatch)** — health-check and prune agent memory stores
- **[agent-workspace](https://github.com/yunaremaia/agent-workspace)** — isolated workspaces per AI agent session

Part of a family of focused, single-purpose developer tools — each one does one thing
and does it well.

## License

MIT
