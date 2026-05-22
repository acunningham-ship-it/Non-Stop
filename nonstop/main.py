#!/usr/bin/env python3
"""Non-Stop — Multi-agent terminal for OpenRouter agents.

A terminal-native operating system for AI agents. Multiple agents work in
parallel toward shared goals. Agents have distinct personalities, communicate
via a pub/sub message bus, and persist across project switches.

Usage:
    nonstop                     # Interactive mode
    pip install nonstop         # Install from source
"""

from __future__ import annotations
import asyncio
import sys

from nonstop.bus import get_bus
from nonstop.projects.manager import ProjectManager
from nonstop.runtime.supervisor import Supervisor
from nonstop.cli.repl import NonStopREPL


async def run_async():
    projects = ProjectManager()
    supervisor = Supervisor(projects)
    repl = NonStopREPL(supervisor, projects)

    try:
        await repl.run()
    except asyncio.CancelledError:
        pass
    finally:
        await supervisor.shutdown_all()


def run():
    """Entry point for the 'nonstop' CLI command."""
    try:
        asyncio.run(run_async())
    except KeyboardInterrupt:
        print("\nGoodbye.")


if __name__ == "__main__":
    run()