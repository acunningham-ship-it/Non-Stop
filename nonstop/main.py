#!/usr/bin/env python3
"""Non-Stop — multi-agent terminal."""

from __future__ import annotations
import argparse
import asyncio
import sys
from importlib.metadata import version as _pkg_version, PackageNotFoundError

from nonstop.projects.manager import ProjectManager
from nonstop.runtime.supervisor import Supervisor
from nonstop.cli.repl import NonStopREPL


def _version() -> str:
    try:
        return _pkg_version("nonstop")
    except PackageNotFoundError:
        return "0.0.0+dev"


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
    parser = argparse.ArgumentParser(prog="nonstop", description="Multi-agent terminal.")
    parser.add_argument("--version", action="version", version=f"nonstop {_version()}")
    parser.add_argument("--update", action="store_true", help="Update and exit.")
    args = parser.parse_args()

    if args.update:
        from nonstop.updater import apply_update
        ok, msg = apply_update()
        print(msg)
        sys.exit(0 if ok else 1)

    try:
        asyncio.run(run_async())
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    run()
