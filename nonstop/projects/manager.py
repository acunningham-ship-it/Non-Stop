from __future__ import annotations
import asyncio
from dataclasses import dataclass, field

from nonstop.bus import Message, get_bus
from nonstop.runtime.agent import Agent


@dataclass
class Project:
    name: str
    description: str = ""
    agents: dict[str, Agent] = field(default_factory=dict)
    memory: list[dict] = field(default_factory=list)
    created_at: str = ""


class ProjectManager:
    """Manages projects — each project is an isolated context with its own agents."""

    def __init__(self):
        self.projects: dict[str, Project] = {}
        self._active: str = "default"

        # Create default project
        self.projects["default"] = Project(name="default", description="Default project")

    @property
    def active(self) -> Project:
        return self.projects[self._active]

    @property
    def active_name(self) -> str:
        return self._active

    async def switch(self, name: str) -> str | None:
        """Switch to a project. Returns error message or None."""
        if name not in self.projects:
            return f"Project '{name}' not found. Use /projects list or /projects new <name>"
        old = self._active
        self._active = name
        await get_bus().publish(Message(
            topic="system.project.switch",
            sender="system",
            content=f"Switched from {old} to {name}",
            metadata={"from": old, "to": name},
        ))
        return None

    async def create(self, name: str, description: str = "") -> str | None:
        if name in self.projects:
            return f"Project '{name}' already exists"
        self.projects[name] = Project(name=name, description=description)
        return None

    def list(self) -> list[dict]:
        return [
            {
                "name": p.name,
                "description": p.description,
                "agents": list(p.agents.keys()),
                "active": p.name == self._active,
            }
            for p in self.projects.values()
        ]

    def get_agent(self, name: str) -> Agent | None:
        """Find an agent by name across all projects."""
        for p in self.projects.values():
            if name in p.agents:
                return p.agents[name]
        return None