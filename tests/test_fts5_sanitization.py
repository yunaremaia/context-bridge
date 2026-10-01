"""Regression tests for FTS5 query sanitization in MemoryStore.

Issue #104 reported that user input reached the FTS5 MATCH clause unsanitized.
The store now builds every MATCH expression from a single sanitizer, and these
tests pin that security contract:

* injection payloads are neutralized and never leak rows
* every generated expression is syntactically valid FTS5
* legitimate queries (phrases, prefixes, boolean operators) still work

The syntax checks execute the sanitized expression against a real FTS5 table so
they stay meaningful even though ``search()`` also defends itself at runtime.
"""

import sqlite3

import pytest

from context_bridge.models import Memory, MemoryType, Query
from context_bridge.store import MemoryStore, _sanitize_fts5_query

# Payloads that must never change the shape of the generated MATCH expression.
INJECTION_PAYLOADS = [
    # tautologies / filter bypasses
    '" OR 1=1 --',
    "tag:secret OR 1=1",
    '" OR ""="',
    "1=1",
    "1 OR 1=1",
    "a OR b -- x",
    # statement termination
    "foo; DROP TABLE memories",
    "'; DROP TABLE memories; --",
    "/*comment*/",
    # column filters and other FTS5 syntax
    "content MATCH 'x'",
    "NEAR(a b)",
    "a:b:c",
    ":",
    "::",
    "^",
    "^a",
    "a^b",
    # unbalanced or duplicated quotes
    '"',
    '""',
    '"""',
    '"" OR ""',
    'hello "world',
    # unbalanced parentheses
    "(",
    ")",
    "()",
    "a AND (b OR c",
    # operators in positions FTS5 rejects
    "a AND AND b",
    "a AND OR b",
    "a OR NOT b",
    "a NOT OR b",
    "x AND NOT y",
    "AND",
    "OR",
    "NOT",
    "AND OR NOT",
    "a OR",
    "OR a",
    # prefix search built on a reserved word
    "AND*",
    "OR*",
    "NOT*",
    "a AND* b",
    "a OR* b",
    "NOT* b",
    # bare punctuation and globs
    "*",
    "**",
    "*)*",
    "-",
    "--",
    "a-",
    "%",
    "_",
    "\\",
    "a\\b",
]

# Payloads that try to widen a match to every row in the table.
TAUTOLOGY_PAYLOADS = [
    '" OR 1=1 --',
    "tag:secret OR 1=1",
    "1=1",
    "1 OR 1=1",
    "a OR b -- x",
]


def make_memory(
    content: str, session_id: str = "s1", importance: float = 0.5
) -> Memory:
    return Memory(
        content=content,
        memory_type=MemoryType.DECISION,
        source_agent="claude",
        session_id=session_id,
        project_path="/test/project",
        importance=importance,
    )


@pytest.fixture
def fts5_table():
    """A bare FTS5 table used to validate generated MATCH expressions."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE probe USING fts5(content)")
    yield conn
    conn.close()


def assert_valid_fts5(conn: sqlite3.Connection, expression: str) -> None:
    """Execute ``expression`` against FTS5, failing on any syntax error."""
    try:
        conn.execute(
            "SELECT count(*) FROM probe WHERE probe MATCH ?", (expression,)
        ).fetchone()
    except sqlite3.OperationalError as exc:
        pytest.fail(f"invalid FTS5 expression {expression!r}: {exc}")


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(tmp_path / "sanitize.db")
    yield s
    s.close()


@pytest.fixture
def seeded_store(store):
    """Store holding two rows that share no term with the injection payloads."""
    store.add_memory(make_memory("We decided to use SQLite for local storage", "s1"))
    store.add_memory(make_memory("Deployment notes live in the runbook", "s2"))
    return store


class TestSanitizerAlwaysProducesValidFts5:
    """The sanitizer output must always be executable FTS5 syntax."""

    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_injection_payload_yields_valid_fts5(self, fts5_table, payload):
        assert_valid_fts5(fts5_table, _sanitize_fts5_query(payload))

    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_injection_payload_does_not_raise(self, fts5_table, payload):
        expression = _sanitize_fts5_query(payload)
        if not expression:
            return
        assert_valid_fts5(fts5_table, expression)

    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_reserved_operators_never_appear_unquoted(self, payload):
        """A bare AND/OR/NOT may only be emitted where FTS5 accepts one."""
        tokens = _sanitize_fts5_query(payload).split()
        for index, token in enumerate(tokens):
            if token not in {"AND", "OR", "NOT"}:
                continue
            assert index > 0, f"leading operator in {payload!r}"
            assert index < len(tokens) - 1, f"trailing operator in {payload!r}"
            assert tokens[index - 1] not in {"AND", "OR", "NOT"}, (
                f"stacked operator in {payload!r}"
            )
            assert tokens[index + 1] not in {"AND", "OR", "NOT"}, (
                f"stacked operator in {payload!r}"
            )

    def test_empty_query_sanitizes_to_empty(self):
        assert _sanitize_fts5_query("") == ""
        assert _sanitize_fts5_query("   ") == ""

    def test_sanitizer_neutralizes_semicolon_payload(self):
        assert ";" not in _sanitize_fts5_query("foo; DROP TABLE memories").replace(
            '"foo;"', ""
        )

    def test_sanitizer_does_not_emit_reserved_word_prefix(self):
        for payload in ("AND*", "OR*", "NOT*"):
            assert _sanitize_fts5_query(payload).strip() != payload

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            # A bare operator needs an operand on both sides.
            ("a AND b", '"a" AND "b"'),
            ("a OR b", '"a" OR "b"'),
            ("a NOT b", '"a" NOT "b"'),
            ("AND a", '"AND" "a"'),
            ("a AND", '"a" "AND"'),
            ("OR a", '"OR" "a"'),
            ("a OR", '"a" "OR"'),
            ("NOT", '"NOT"'),
            # FTS5's NOT is already an AND-NOT, so it subsumes a preceding AND.
            ("a AND NOT b", '"a" NOT "b"'),
            ("a OR NOT b", '"a" NOT "b"'),
            ("a AND AND b", '"a" AND "b"'),
            ("a AND OR b", '"a" AND "b"'),
            ("a NOT OR b", '"a" NOT "b"'),
            # Phrases and prefixes keep working.
            ('"two words"', '"two words"'),
            ("SQL*", "SQL*"),
            ("SQLite AND local", '"SQLite" AND "local"'),
            ("zero-config", '"zero-config"'),
        ],
    )
    def test_sanitizer_output_is_exact(self, payload, expected):
        assert _sanitize_fts5_query(payload) == expected


class TestSearchIsNotInjectable:
    """End-to-end behaviour of search() against injection payloads."""

    @pytest.mark.parametrize("payload", INJECTION_PAYLOADS)
    def test_search_does_not_raise(self, seeded_store, payload):
        try:
            results = seeded_store.search(Query(text=payload))
        except (sqlite3.Error, ValueError, RuntimeError) as exc:
            pytest.fail(f"search() raised on payload {payload!r}: {exc}")
        assert isinstance(results, list)

    @pytest.mark.parametrize("payload", TAUTOLOGY_PAYLOADS)
    def test_injection_does_not_leak_all_rows(self, seeded_store, payload):
        total = seeded_store.get_stats()["total_memories"]
        assert total == 2
        assert len(seeded_store.search(Query(text=payload))) < total

    @pytest.mark.parametrize("payload", TAUTOLOGY_PAYLOADS)
    def test_injection_matches_nothing(self, seeded_store, payload):
        assert seeded_store.search(Query(text=payload)) == []

    @pytest.mark.parametrize(
        "payload",
        ["foo; DROP TABLE memories", "'; DROP TABLE memories; --", "/*comment*/"],
    )
    def test_memories_table_survives(self, seeded_store, payload):
        seeded_store.search(Query(text=payload))
        assert seeded_store.get_stats()["total_memories"] == 2

    def test_empty_query_returns_no_results(self, seeded_store):
        for text in ("", "   ", '"', "*", "-", "::"):
            assert seeded_store.search(Query(text=text)) == []


class TestSingleSanitizerIsUsed:
    """Issue #104 requires one sanitizer to cover every search path."""

    def test_competing_escaper_is_removed(self):
        assert not hasattr(MemoryStore, "_escape_fts5_query")

    def test_matched_expression_is_the_sanitized_query(self, seeded_store):
        """The string handed to FTS5 is exactly what the sanitizer produced."""
        traced = []
        seeded_store.conn.set_trace_callback(traced.append)
        try:
            seeded_store.search(Query(text="SQLite AND local"))
        finally:
            seeded_store.conn.set_trace_callback(None)

        statements = [s for s in traced if "MATCH" in s]
        assert statements, "search() never issued a MATCH statement"
        assert _sanitize_fts5_query("SQLite AND local") in statements[-1]
        assert "_escape_fts5_query" not in "".join(traced)


class TestLegitimateQueriesStillWork:
    """Sanitizing must not break queries users actually type."""

    def test_multi_word_search(self, seeded_store):
        results = seeded_store.search(Query(text="SQLite local storage"))
        assert len(results) == 1
        assert "SQLite" in results[0].content

    def test_phrase_search(self, seeded_store):
        results = seeded_store.search(Query(text='"SQLite for local storage"'))
        assert len(results) == 1

    def test_prefix_search(self, seeded_store):
        results = seeded_store.search(Query(text="SQL*"))
        assert len(results) == 1
        assert "SQLite" in results[0].content

    def test_and_operator(self, seeded_store):
        assert len(seeded_store.search(Query(text="SQLite AND local"))) == 1

    def test_or_operator(self, seeded_store):
        assert len(seeded_store.search(Query(text="SQLite OR runbook"))) == 2

    def test_not_operator(self, seeded_store):
        results = seeded_store.search(Query(text="SQLite NOT runbook"))
        assert len(results) == 1
        assert "SQLite" in results[0].content

    def test_operator_with_prefix(self, seeded_store):
        assert len(seeded_store.search(Query(text="SQL* OR runbook"))) == 2

    def test_hyphenated_term(self, seeded_store):
        seeded_store.add_memory(make_memory("The zero-config build is fast", "s3"))
        results = seeded_store.search(Query(text="zero-config"))
        assert len(results) == 1

    def test_filters_still_apply(self, seeded_store):
        assert len(seeded_store.search(Query(text="SQLite", agent="claude"))) == 1
        assert seeded_store.search(Query(text="SQLite", agent="nobody")) == []
        assert (
            len(
                seeded_store.search(
                    Query(text="SQLite", memory_type=MemoryType.DECISION)
                )
            )
            == 1
        )
        assert (
            seeded_store.search(Query(text="SQLite", memory_type=MemoryType.LESSON))
            == []
        )

    def test_limit_is_respected(self, seeded_store):
        assert len(seeded_store.search(Query(text="SQLite OR runbook", limit=1))) == 1
