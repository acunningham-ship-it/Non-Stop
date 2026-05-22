"""Kanban board — agents assign, move, and complete tickets autonomously."""

from __future__ import annotations
import json
import sqlite3
import os
import time
from dataclasses import dataclass, field
from typing import Any

DB_PATH = os.path.expanduser("~/.nonstop_board.db")

COLUMNS = ["backlog", "in_progress", "review", "done"]


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project     TEXT NOT NULL DEFAULT 'default',
            title       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            column      TEXT NOT NULL DEFAULT 'backlog',
            assigned_to TEXT,
            created_by  TEXT NOT NULL DEFAULT 'user',
            priority    INTEGER NOT NULL DEFAULT 0,
            depends_on  TEXT DEFAULT '',
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ticket_comments (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id  INTEGER NOT NULL REFERENCES tickets(id),
            author     TEXT NOT NULL,
            body       TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    conn.commit()
    return conn


@dataclass
class Ticket:
    id: int
    project: str
    title: str
    description: str
    column: str
    assigned_to: str | None
    created_by: str
    priority: int
    depends_on: list[str]
    created_at: float
    updated_at: float
    comments: list[dict] = field(default_factory=list)


def create_ticket(
    title: str,
    project: str = "default",
    description: str = "",
    assigned_to: str | None = None,
    created_by: str = "user",
    priority: int = 0,
    depends_on: str = "",
) -> int:
    conn = _get_db()
    now = time.time()
    cur = conn.execute(
        "INSERT INTO tickets (project, title, description, column, assigned_to, created_by, priority, depends_on, created_at, updated_at) "
        "VALUES (?, ?, ?, 'backlog', ?, ?, ?, ?, ?, ?)",
        (project, title, description, assigned_to, created_by, priority, depends_on, now, now),
    )
    conn.commit()
    return cur.lastrowid


def move_ticket(ticket_id: int, new_column: str) -> str | None:
    if new_column not in COLUMNS:
        return f"Invalid column: {new_column}. Use: {', '.join(COLUMNS)}"
    conn = _get_db()
    conn.execute(
        "UPDATE tickets SET column=?, updated_at=? WHERE id=?",
        (new_column, time.time(), ticket_id),
    )
    conn.commit()
    return None


def assign_ticket(ticket_id: int, agent_name: str):
    conn = _get_db()
    conn.execute(
        "UPDATE tickets SET assigned_to=?, column='in_progress', updated_at=? WHERE id=?",
        (agent_name, time.time(), ticket_id),
    )
    conn.commit()


def add_comment(ticket_id: int, author: str, body: str):
    conn = _get_db()
    conn.execute(
        "INSERT INTO ticket_comments (ticket_id, author, body, created_at) VALUES (?, ?, ?, ?)",
        (ticket_id, author, body, time.time()),
    )
    conn.commit()


def list_tickets(project: str = "default", column: str | None = None) -> list[Ticket]:
    conn = _get_db()
    query = "SELECT * FROM tickets WHERE project=?"
    params = [project]
    if column:
        query += " AND column=?"
        params.append(column)
    query += " ORDER BY priority DESC, created_at ASC"
    rows = conn.execute(query, params).fetchall()
    tickets = []
    for r in rows:
        comments = conn.execute(
            "SELECT author, body, created_at FROM ticket_comments WHERE ticket_id=? ORDER BY created_at",
            (r[0],),
        ).fetchall()
        tickets.append(Ticket(
            id=r[0], project=r[1], title=r[2], description=r[3],
            column=r[4], assigned_to=r[5], created_by=r[6],
            priority=r[7], depends_on=(r[8].split(",") if r[8] else []),
            created_at=r[9], updated_at=r[10],
            comments=[{"author": c[0], "body": c[1]} for c in comments],
        ))
    return tickets


def find_ticket(ticket_id: int) -> Ticket | None:
    tickets = list_tickets()
    for t in tickets:
        if t.id == ticket_id:
            return t
    return None


def board_summary(project: str = "default") -> str:
    """Human-readable board for display."""
    lines = [f"[bold]Board — {project}[/]\n"]
    for col in COLUMNS:
        tickets = list_tickets(project, col)
        if not tickets:
            continue
        lines.append(f"  [bold]{col}[/] ({len(tickets)}):")
        for t in tickets:
            assign = f" → {t.assigned_to}" if t.assigned_to else ""
            lines.append(f"    #{t.id} {t.title}{assign}")
    return "\n".join(lines) if len(lines) > 1 else "Board is empty."


def agent_pending_tasks(agent_name: str, project: str = "default") -> list[Ticket]:
    """Get tickets assigned to a specific agent."""
    return [t for t in list_tickets(project) if t.assigned_to == agent_name]