"""Orchestration rules engine — when X happens, do Y.

Rules are trigger-action pairs evaluated against bus messages.
Agents can create rules dynamically: "when architect finishes, send to skeptic"
"""

from __future__ import annotations
import json
import sqlite3
import os
import re
import time
from typing import Any

DB_PATH = os.path.expanduser("~/.nonstop_rules.db")


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rules (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            project   TEXT NOT NULL DEFAULT 'default',
            trigger   TEXT NOT NULL,
            action    TEXT NOT NULL,
            enabled   INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL DEFAULT 'system',
            created_at REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


class Orchestrator:
    """Evaluates trigger-action rules against bus messages."""

    def __init__(self, bus=None, supervisor=None):
        self.bus = bus
        self.supervisor = supervisor

    def add_rule(self, trigger: str, action: str, project: str = "default",
                 created_by: str = "system"):
        """Add a rule.
        
        trigger: pattern like "agent.{name}.result" or wildcard "agent.*.result"
        action: instruction like "tell skeptic to review" or "move ticket #1 to review"
        """
        conn = _get_db()
        conn.execute(
            "INSERT INTO rules (project, trigger, action, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (project, trigger, action, created_by, time.time()),
        )
        conn.commit()

    def remove_rule(self, rule_id: int):
        conn = _get_db()
        conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        conn.commit()

    def list_rules(self, project: str = "default") -> list[dict]:
        conn = _get_db()
        rows = conn.execute(
            "SELECT id, trigger, action, enabled, created_by FROM rules WHERE project=? ORDER BY id",
            (project,),
        ).fetchall()
        return [
            {"id": r[0], "trigger": r[1], "action": r[2], "enabled": bool(r[3]),
             "created_by": r[4]}
            for r in rows
        ]

    async def evaluate(self, topic: str, sender: str, content: str, project: str):
        """Check all rules against a bus message. Fire matching ones."""
        if not self.supervisor:
            return
        rules = self.list_rules(project)
        for rule in rules:
            if not rule["enabled"]:
                continue
            if self._matches(rule["trigger"], topic):
                await self._fire(rule, sender, content, project)

    def _matches(self, pattern: str, topic: str) -> bool:
        if pattern.endswith(".*"):
            return topic.startswith(pattern[:-1])
        return pattern == topic

    async def _fire(self, rule: dict, sender: str, content: str, project: str):
        """Execute a rule's action."""
        action = rule["action"]

        # Parse action patterns
        tell_match = re.match(r"tell (\S+) to (.+)", action)
        if tell_match:
            target = tell_match.group(1)
            instruction = tell_match.group(2)
            agent = self.supervisor.projects.get_agent(target)
            if agent:
                # Include context from the triggering message
                full_instruction = (
                    f"[orchestration] {instruction}\n\n"
                    f"Context from {sender}: {content[:500]}"
                )
                await agent.direct_message(full_instruction)
            return

        move_match = re.match(r"move ticket #(\d+) to (\S+)", action)
        if move_match:
            from board import move_ticket
            ticket_id = int(move_match.group(1))
            new_col = move_match.group(2)
            move_ticket(ticket_id, new_col)
            return

        # Default: treat action as a message to send
        if self.bus:
            from bus import Message
            await self.bus.publish(Message(
                topic="orchestration.action",
                sender="orchestrator",
                content=action,
                metadata={"rule_id": rule["id"], "triggered_by": sender},
            ))


def parse_natural_rule(text: str) -> tuple[str, str] | None:
    """Parse a natural language rule like 'when architect finishes, send to skeptic'.
    Returns (trigger, action) or None.
    """
    patterns = [
        (r"when\s+(\S+)\s+finishes?\w*\s*,?\s*(?:send|tell|give)\s+(?:it|results?|to)\s+(\S+)",
         lambda m: (f"agent.{m.group(1)}.result", f"tell {m.group(2)} to review the result")),
        (r"when\s+(\S+)\s+finishes?\w*\s*,?\s+move\s+(?:it|the\s+ticket)\s+to\s+(\S+)",
         lambda m: (f"agent.{m.group(1)}.result", f"move the ticket to {m.group(2)}")),
        (r"when\s+(\S+)\s+(?:says|responds)\s*,?\s+(?:tell|notify)\s+(\S+)",
         lambda m: (f"agent.{m.group(1)}.result", f"tell {m.group(2)} to review")),
    ]
    for pattern, factory in patterns:
        m = re.search(pattern, text.lower())
        if m:
            return factory(m)
    return None