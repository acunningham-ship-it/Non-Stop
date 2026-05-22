"""Per-agent persistent memory — SQLite-backed key-value store per agent."""

from __future__ import annotations
import json
import sqlite3
import os
import time
from typing import Any

DB_PATH = os.path.expanduser("~/.nonstop_memory.db")


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_memory (
            agent_name TEXT NOT NULL,
            project    TEXT NOT NULL DEFAULT 'default',
            key        TEXT NOT NULL,
            value      TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (agent_name, project, key)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_profile (
            agent_name TEXT NOT NULL,
            project    TEXT NOT NULL DEFAULT 'default',
            trait      TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            updated_at REAL NOT NULL,
            PRIMARY KEY (agent_name, project, trait)
        )
    """)
    conn.commit()
    return conn


class AgentMemory:
    """Key-value memory for a specific agent within a project."""

    def __init__(self, agent_name: str, project: str = "default"):
        self.agent_name = agent_name
        self.project = project

    def remember(self, key: str, value: Any):
        """Store a fact. Serializes dicts/lists to JSON."""
        if not isinstance(value, str):
            value = json.dumps(value)
        conn = _get_db()
        conn.execute(
            "INSERT OR REPLACE INTO agent_memory (agent_name, project, key, value, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.agent_name, self.project, key, value, time.time()),
        )
        conn.commit()

    def recall(self, key: str) -> str | None:
        """Retrieve a stored fact."""
        conn = _get_db()
        row = conn.execute(
            "SELECT value FROM agent_memory WHERE agent_name=? AND project=? AND key=?",
            (self.agent_name, self.project, key),
        ).fetchone()
        return row[0] if row else None

    def recall_all(self) -> dict[str, str]:
        """Retrieve all stored facts for this agent in this project."""
        conn = _get_db()
        rows = conn.execute(
            "SELECT key, value FROM agent_memory WHERE agent_name=? AND project=?",
            (self.agent_name, self.project),
        ).fetchall()
        return {k: v for k, v in rows}

    def forget(self, key: str):
        conn = _get_db()
        conn.execute(
            "DELETE FROM agent_memory WHERE agent_name=? AND project=? AND key=?",
            (self.agent_name, self.project, key),
        )
        conn.commit()

    def learn_trait(self, trait: str, confidence: float = 1.0):
        """Record a personality trait the agent has developed."""
        conn = _get_db()
        conn.execute(
            "INSERT OR REPLACE INTO agent_profile (agent_name, project, trait, confidence, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.agent_name, self.project, trait, confidence, time.time()),
        )
        conn.commit()

    def get_profile(self) -> list[dict]:
        """Get all learned traits, sorted by recency."""
        conn = _get_db()
        rows = conn.execute(
            "SELECT trait, confidence, updated_at FROM agent_profile "
            "WHERE agent_name=? AND project=? ORDER BY updated_at DESC",
            (self.agent_name, self.project),
        ).fetchall()
        return [
            {"trait": r[0], "confidence": r[1], "updated_at": r[2]} for r in rows
        ]

    def memory_summary(self) -> str:
        """Return a compact memory summary for injecting into system prompt."""
        facts = self.recall_all()
        traits = self.get_profile()
        parts = []
        if facts:
            parts.append("What I know:")
            for k, v in facts.items():
                parts.append(f"  {k}: {v[:100]}")
        if traits:
            parts.append("\nMy learned traits:")
            for t in traits[:5]:
                parts.append(f"  {t['trait']} (confidence: {t['confidence']:.1f})")
        return "\n".join(parts) if parts else ""


def global_memory(query: str, value: str | None = None) -> list[dict] | None:
    """Query or set global (cross-agent) memory.
    If value is None, searches for matching keys across all agents.
    If value is set, stores a global fact under agent '__global__'.
    """
    gmem = AgentMemory("__global__", "global")
    if value is not None:
        gmem.remember(query, value)
        return None
    # Search
    conn = _get_db()
    rows = conn.execute(
        "SELECT agent_name, project, key, value FROM agent_memory WHERE key LIKE ?",
        (f"%{query}%",),
    ).fetchall()
    return [
        {"agent": r[0], "project": r[1], "key": r[2], "value": r[3]} for r in rows
    ]