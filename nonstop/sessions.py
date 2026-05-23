"""Conversation persistence — one JSONL per project at ~/.nonstop/sessions/."""

from __future__ import annotations
import json
import time
from pathlib import Path

SESSIONS_DIR = Path.home() / ".nonstop" / "sessions"


def _path_for(project: str) -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in project)
    return SESSIONS_DIR / f"{safe or 'default'}.jsonl"


def save_turn(project: str, role: str, agent: str, content: str) -> None:
    """Append a single turn to the project's session log."""
    rec = {
        "ts": time.time(),
        "role": role,           # "user" | "assistant" | "system"
        "agent": agent,         # agent name for assistant rows; "" for user
        "content": content,
    }
    with _path_for(project).open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_recent(project: str, limit: int = 20) -> list[dict]:
    """Return the most-recent `limit` turns (oldest first)."""
    path = _path_for(project)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def clear(project: str) -> None:
    path = _path_for(project)
    if path.exists():
        path.unlink()


def stats(project: str) -> dict:
    """Quick counts for /sessions."""
    path = _path_for(project)
    if not path.exists():
        return {"turns": 0, "size": 0, "exists": False}
    turns = sum(1 for _ in path.open(encoding="utf-8"))
    return {"turns": turns, "size": path.stat().st_size, "exists": True}
