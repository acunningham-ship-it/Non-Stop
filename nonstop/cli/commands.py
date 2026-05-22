"""Slash command handler — parses and routes /commands"""

from __future__ import annotations
from typing import Callable, Awaitable


class Command:
    def __init__(
        self,
        name: str,
        handler: Callable[..., Awaitable[str]],
        help_text: str = "",
        aliases: list[str] | None = None,
    ):
        self.name = name
        self.handler = handler
        self.help_text = help_text
        self.aliases = aliases or []

    def matches(self, input_name: str) -> bool:
        return input_name == self.name or input_name in self.aliases


class CommandRegistry:
    """Registry of slash commands with routing."""

    def __init__(self):
        self._commands: dict[str, Command] = {}

    def register(self, cmd: Command):
        self._commands[cmd.name] = cmd

    async def route(self, input_line: str) -> str:
        """Parse and execute a slash command. Returns response text."""
        if not input_line.startswith("/"):
            return ""

        parts = input_line[1:].strip().split(maxsplit=1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        for cmd in self._commands.values():
            if cmd.matches(cmd_name):
                try:
                    result = await cmd.handler(args)
                    return result or f"Command /{cmd_name} executed."
                except Exception as e:
                    return f"Error in /{cmd_name}: {e}"

        return f"Unknown command: /{cmd_name}. Try /help"

    def help_text(self) -> str:
        lines = ["Available commands:"]
        for cmd in self._commands.values():
            aliases = f" (aliases: {', '.join(cmd.aliases)})" if cmd.aliases else ""
            lines.append(f"  /{cmd.name}{aliases} — {cmd.help_text}")
        return "\n".join(lines)