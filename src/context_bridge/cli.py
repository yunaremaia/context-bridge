"""CLI interface for context-bridge."""

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .models import Memory, MemoryType, Query
from .parsers import auto_detect_parser
from .store import MemoryStore

console = Console()
DEFAULT_DB = Path.home() / ".context-bridge" / "index.db"


def get_store(ctx) -> MemoryStore:
    db_path = ctx.obj.get("db", DEFAULT_DB)
    return MemoryStore(Path(db_path))


@click.group()
@click.option("--db", type=click.Path(), help="Custom database path")
@click.pass_context
def cli(ctx, db):
    """Universal session memory for AI agents."""
    ctx.ensure_object(dict)
    ctx.obj["db"] = db or DEFAULT_DB


@cli.command()
@click.pass_context
def init(ctx):
    """Initialize context-bridge database."""
    db_path = ctx.obj["db"]
    store = MemoryStore(Path(db_path))
    stats = store.get_stats()
    store.close()
    console.print(f"[green]✅ Initialized at {db_path}[/green]")
    console.print(
        f"   Memories: {stats['total_memories']} | Sessions: {stats['total_sessions']}"
    )


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.pass_context
def index(ctx, path):
    """Index AI agent sessions from a directory."""
    store = get_store(ctx)
    base = Path(path)
    files = []
    for pattern in ["**/*.jsonl", "**/*.json", "**/*.log", "**/*.md"]:
        files.extend(base.glob(pattern))

    total_sessions = 0
    for fp in files:
        try:
            parser = auto_detect_parser(fp)
            for session in parser(fp):
                if not store.is_indexed(session.session_id):
                    store.add_session(session)
                    total_sessions += 1
        except (json.JSONDecodeError, ValueError, OSError, KeyError, TypeError):
            # Skip files that fail to parse (malformed JSON, missing fields, etc.)
            continue

    store.close()
    console.print(
        f"[green]✅ Indexed {total_sessions} sessions from {len(files)} files[/green]"
    )


@cli.command()
@click.argument("query_text")
@click.option("--agent", type=str, default=None, help="Filter by agent")
@click.option("--limit", type=int, default=10, help="Max results")
@click.pass_context
def recall(ctx, query_text, agent, limit):
    """Search memory for relevant context."""
    store = get_store(ctx)
    query = Query(text=query_text, agent=agent, limit=limit)
    results = store.search(query)

    if not results:
        console.print("[yellow]No memories found for this query.[/yellow]")
        return

    table = Table(title="Memory Results")
    table.add_column("Type", style="cyan")
    table.add_column("Agent", style="green")
    table.add_column("Content", style="white")
    table.add_column("Score", style="yellow")

    for m in results:
        content_preview = m.content[:100] + "..." if len(m.content) > 100 else m.content
        table.add_row(
            m.memory_type.value, m.source_agent, content_preview, f"{m.importance:.2f}"
        )

    console.print(table)
    store.close()


@cli.command()
@click.argument("session_id")
@click.argument("content")
@click.option("--agent", type=str, default="manual")
@click.option(
    "--type",
    "mtype",
    type=click.Choice(["decision", "pattern", "lesson", "preference", "architecture"]),
    default="decision",
)
@click.pass_context
def remember(ctx, session_id, content, agent, mtype):
    """Manually store a memory."""
    store = get_store(ctx)
    memory = Memory(
        content=content,
        memory_type=MemoryType(mtype),
        source_agent=agent,
        session_id=session_id,
        project_path=str(Path.cwd()),
    )
    mid = store.add_memory(memory)
    store.close()
    console.print(f"[green]✅ Memory stored (id={mid})[/green]")


@cli.command()
@click.pass_context
def stats(ctx):
    """Show memory statistics."""
    store = get_store(ctx)
    s = store.get_stats()
    store.close()
    console.print("[bold]Context Bridge Stats[/bold]")
    console.print(f"  Total Memories: {s['total_memories']}")
    console.print(f"  Total Sessions: {s['total_sessions']}")
    console.print(f"  Agents: {', '.join(s['agents']) if s['agents'] else 'None'}")


@cli.command()
@click.option("--agent", type=str, default="claude")
@click.pass_context
def inject(ctx, agent):
    """Output context injection for a new session."""
    store = get_store(ctx)
    query = Query(text="project setup architecture preferences", agent=agent, limit=5)
    results = store.search(query)
    store.close()

    if not results:
        console.print("[yellow]No relevant context found. Start fresh![/yellow]")
        return

    output = "## Context Bridge — Injected Context\n\n"
    for m in results:
        output += f"- [{m.memory_type.value}] {m.content}\n"
    console.print(output)


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
