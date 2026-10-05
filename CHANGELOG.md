# Changelog

## [Unreleased]

### Fixed
- **`context-bridge index` no longer picks a parser from a substring of the
  absolute path.** `auto_detect_parser` tested `"hermes" in str(parent)`, so a
  log at `/srv/hermes-data/plain.jsonl` was parsed as a Hermes markdown log, no
  sessions were found in it, and the run reported success with the session
  silently unindexed — the same failure mode #117 removed for corrupt lines,
  one level up. Routing now follows the markers inside the file (`type` for
  Claude Code, `entries` for Codex, `message` for OpenCode), and a JSON file
  carrying no marker raises `ParserNotDetectedError` instead of falling through
  to a default parser. `index` names every file it could not route.

  Behaviour change: a marker-less JSON file used to be handed to the Claude Code
  parser by default and index nothing; it is now reported as unroutable, and a
  caller that wants it parsed can call the parser directly.

## [0.2.0] - 2026-10-02

### Changed
- **BREAKING (install name only): the distribution is renamed to
  `context-bridge-py`.** The bare `context-bridge` name on PyPI belongs to
  Ganzzi/context_bridge, an unrelated RAG documentation crawler, so this
  project could never be published under its own name and a documented
  `pip install context-bridge` silently installed that other author's
  package. The import package (`context_bridge`) and the console script
  (`context-bridge`) are unchanged.

## [0.1.0] - 2026-09-26

### Added
- Initial release