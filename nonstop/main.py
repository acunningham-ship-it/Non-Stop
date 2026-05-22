#!/usr/bin/env python3
"""Non-Stop — multi-agent terminal."""

from __future__ import annotations
import argparse
import asyncio
import getpass
import os
import sys
from importlib.metadata import version as _pkg_version, PackageNotFoundError
from pathlib import Path

from nonstop.projects.manager import ProjectManager
from nonstop.runtime.supervisor import Supervisor
from nonstop.cli.repl import NonStopREPL


CONFIG_PATH = Path.home() / ".nonstop" / "config"


def _version() -> str:
    try:
        return _pkg_version("nonstop")
    except PackageNotFoundError:
        return "0.0.0+dev"


def _load_config_env() -> None:
    """Load KEY=VALUE pairs from ~/.nonstop/config into os.environ."""
    if not CONFIG_PATH.exists():
        return
    for line in CONFIG_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _save_config_env(key: str, value: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if CONFIG_PATH.exists():
        for line in CONFIG_PATH.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    existing[key] = value
    CONFIG_PATH.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n")
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass


def _ensure_api_key() -> bool:
    """Make sure OPENROUTER_API_KEY is set. Returns False if user bails."""
    if os.environ.get("OPENROUTER_API_KEY"):
        return True

    print()
    print("  Non-Stop needs an OpenRouter API key to talk to models.")
    print("  Get one at: https://openrouter.ai/keys")
    print()
    try:
        key = getpass.getpass("  OPENROUTER_API_KEY (input hidden, blank to cancel): ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return False
    if not key:
        print("  no key entered — exiting.")
        return False

    os.environ["OPENROUTER_API_KEY"] = key
    _save_config_env("OPENROUTER_API_KEY", key)
    print(f"  saved to {CONFIG_PATH} (chmod 600). You won't be asked again.")
    print()
    return True


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

    _load_config_env()
    if not _ensure_api_key():
        sys.exit(1)

    try:
        asyncio.run(run_async())
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    run()
