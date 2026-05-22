"""Self-updater for Non-Stop.

Two install modes are supported:

1. Editable git install (the install.sh path): the package lives inside a
   git checkout. Update = `git pull --ff-only` + `pip install -e .` into
   the same venv.

2. Pip-from-git install: no .git/ next to the package. Update =
   `pip install --upgrade git+https://github.com/acunningham-ship-it/Non-Stop`.

A background check runs at most once per UPDATE_CHECK_INTERVAL and caches
the result at ~/.nonstop/update_check.json. Set NONSTOP_AUTO_UPDATE=0 to
disable the background check; /update still works on demand.
"""

from __future__ import annotations
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO = "acunningham-ship-it/Non-Stop"
BRANCH = "main"
GITHUB_COMMITS_URL = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
PIP_TARGET = f"git+https://github.com/{REPO}@{BRANCH}"

UPDATE_CHECK_INTERVAL = 24 * 60 * 60  # 24h
CACHE_PATH = Path.home() / ".nonstop" / "update_check.json"


@dataclass
class InstallInfo:
    mode: str           # "editable" or "pip"
    repo_root: Path | None
    venv_pip: Path | None  # only set for editable mode


def detect_install() -> InstallInfo:
    """Walk up from this file to find a git checkout. If found, editable mode."""
    here = Path(__file__).resolve()
    # nonstop/updater.py -> nonstop/ -> repo root
    candidate = here.parents[1]
    if (candidate / ".git").is_dir() and (candidate / "install.sh").exists():
        venv_pip = candidate / ".venv" / "bin" / "pip"
        return InstallInfo(
            mode="editable",
            repo_root=candidate,
            venv_pip=venv_pip if venv_pip.exists() else None,
        )
    return InstallInfo(mode="pip", repo_root=None, venv_pip=None)


def _read_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_cache(data: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data))


def _local_sha(info: InstallInfo) -> str | None:
    if info.mode != "editable" or info.repo_root is None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(info.repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=3, check=True,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def _fetch_remote_head() -> tuple[str, str] | None:
    """Return (sha, commit_subject) for the remote HEAD, or None on failure."""
    try:
        req = urllib.request.Request(
            GITHUB_COMMITS_URL,
            headers={"Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.load(resp)
        sha = data.get("sha", "")
        subject = data.get("commit", {}).get("message", "").splitlines()[0]
        if sha:
            return sha, subject
    except Exception:
        return None
    return None


async def check_for_update() -> dict | None:
    """Background-safe check. Returns dict with update info if available, else None.

    Result shape: {"sha": str, "subject": str, "short": str}
    """
    if os.environ.get("NONSTOP_AUTO_UPDATE") == "0":
        return None

    cache = _read_cache()
    now = time.time()
    if now - cache.get("last_check_ts", 0) < UPDATE_CHECK_INTERVAL:
        # Use cached result without hitting the network.
        return cache.get("pending_update")

    info = detect_install()
    local = _local_sha(info) or cache.get("installed_sha", "")

    remote = await asyncio.to_thread(_fetch_remote_head)
    if remote is None:
        # Network failed — don't update the cache timestamp, try again later.
        return cache.get("pending_update")

    remote_sha, subject = remote
    pending = None
    if remote_sha and remote_sha != local:
        pending = {"sha": remote_sha, "subject": subject, "short": remote_sha[:7]}

    _write_cache({
        "last_check_ts": now,
        "installed_sha": local,
        "pending_update": pending,
    })
    return pending


def apply_update() -> tuple[bool, str]:
    """Run the actual upgrade. Returns (success, message)."""
    info = detect_install()
    try:
        if info.mode == "editable":
            assert info.repo_root is not None
            subprocess.run(
                ["git", "-C", str(info.repo_root), "pull", "--ff-only"],
                check=True, capture_output=True, text=True,
            )
            pip = str(info.venv_pip) if info.venv_pip else sys.executable
            cmd = (
                [pip, "install", "-e", str(info.repo_root)]
                if info.venv_pip
                else [sys.executable, "-m", "pip", "install", "-e", str(info.repo_root)]
            )
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        else:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", PIP_TARGET],
                check=True, capture_output=True, text=True,
            )
    except subprocess.CalledProcessError as e:
        return False, (e.stderr or e.stdout or str(e)).strip()
    except Exception as e:
        return False, str(e)

    # Refresh cache so banner stops nagging.
    cache = _read_cache()
    cache["pending_update"] = None
    cache["last_check_ts"] = time.time()
    sha = _local_sha(detect_install())
    if sha:
        cache["installed_sha"] = sha
    _write_cache(cache)

    return True, "updated — restart nonstop to load the new version"
