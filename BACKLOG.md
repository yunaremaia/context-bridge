# Backlog

Open questions that are deliberately not decided here. Each entry says what was
observed, why it is not a bug fix, and what the options are.

## `auto_detect_parser` substring-matches the absolute parent path

`src/context_bridge/parsers.py` picks a parser by testing substrings against
`str(file_path.parent)` and `file_path.name`. The parent test is the problem: it
sees the whole absolute path, including directories that have nothing to do with
the agent that wrote the log.

Reproduced with the real function:

```text
/root/.hermes/sessions/whatever.jsonl  -> parse_hermes_log
/home/dana/.hermes/logs/abc.jsonl      -> parse_hermes_log
/srv/hermes-data/plain.jsonl           -> parse_hermes_log
/opt/hermes/queue.jsonl                -> parse_hermes_log
/tmp/notrelated/claude/x.jsonl         -> parse_claude_code_jsonl
```

Every path above reaches the wrong parser except the last one, and the reason is
that `".hermes"` and `"hermes"` appear in a parent directory that has nothing to
do with the log's format. `parse_hermes_log` then reads a Claude Code JSONL file
and finds nothing in it, so a session is silently not indexed — the same failure
mode #117 removed for corrupt lines, one level up.

Two options, and picking either changes what `context-bridge index` does with a
file it currently reads:

- Match on the file name and on path components that are *agent* directories,
  e.g. `.claude`, `codex`, `opencode`, instead of any substring of the parent
  string. This is the narrow fix, but it changes routing for every file that
  today relies on a loose parent match (a repo checkout named `claude-tools`,
  for instance).
- Keep the parent match but exclude dotfile/home segments (`.hermes`) and
  require a word-boundary match on directory names. Narrower behaviour change,
  more special cases, and it still misroutes `/opt/hermes/queue.jsonl`.

This is left unchanged here because it is a routing contract, not a bug fix:
whichever way it goes, a file that used to index can stop indexing, and that
belongs in its own PR with routing tests per agent. It was found while fixing
the corrupt-line reporting in #117 and is recorded rather than fixed so that PR
stays a single, reviewable change.