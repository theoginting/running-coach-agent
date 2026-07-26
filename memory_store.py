"""Lightweight single-user memory store backed by a JSON file.

Replaces the old PostgreSQL-backed, per-chat memory: with the Claude app as the
only interface there is exactly one athlete, so memory is a flat list of facts
persisted to disk.

On Railway the container filesystem is ephemeral, so set MEMORY_FILE to a path
on a mounted volume if you want facts to survive redeploys.
"""
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
MEMORY_FILE = Path(os.environ.get("MEMORY_FILE", PROJECT_ROOT / ".memory.json"))


def list_facts() -> list[str]:
    if not MEMORY_FILE.exists():
        return []
    try:
        return json.loads(MEMORY_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _write(facts: list[str]) -> None:
    MEMORY_FILE.write_text(json.dumps(facts, indent=2))


def save_fact(fact: str) -> list[str]:
    """Append a fact (deduplicated) and return the full list."""
    fact = fact.strip()
    facts = list_facts()
    if fact and fact not in facts:
        facts.append(fact)
        _write(facts)
    return facts


def delete_fact(fact: str) -> list[str]:
    """Remove a fact by exact match and return the remaining list."""
    facts = [f for f in list_facts() if f != fact]
    _write(facts)
    return facts


def clear() -> None:
    _write([])
