# Non-Stop

Multi-agent terminal. AI agents work together toward shared goals. Built for the terminal, runs on your machine.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/acunningham-ship-it/Non-Stop/main/install.sh | bash

export OPENROUTER_API_KEY="sk-..."

nonstop
```

Or install from source:

```bash
git clone https://github.com/armanicunningham/Non-Stop.git
cd Non-Stop
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
nonstop
```

## What it is

Non-Stop is a terminal-native operating system for AI agents. Unlike single-agent tools (Hermes, Claude Code), Non-Stop is multi-agent from the ground up:

- **Multiple agents** work in parallel toward shared goals
- **Streaming responses** — watch agents think in real-time
- **Agent memory** — per-agent SQLite persistence
- **Kanban board** — agents reference and move tickets
- **Teams** — spawn coordinated agent teams that pass work
- **Orchestration** — rules like "when architect finishes, send to skeptic"
- **Projects** — switch context, background agents keep working
- **Blank slate agents** — define personalities through conversation

## Commands

| Command | Description |
|---------|-------------|
| `/summon <name> [as <desc>]` | Spawn an agent |
| `/team <build\|research\|debate\|review>` | Spawn a coordinated team |
| `/board` | Kanban board |
| `/rules` | Orchestration rules |
| `/model <name>` | Set default model |
| `/remember <name>` | Show agent memory |
| `/projects` | Manage projects |
| `/tell <name> <msg>` | Message an agent directly |
| `/kill <name>` | Dismiss an agent |
| `/status` | System status |
| `/help` | Full command list |

## Architecture

```
nonstop/              # Python package
├── main.py           # Entry point
├── bus/              # Pub/sub message bus
├── board/            # Kanban (SQLite)
├── cli/              # Terminal REPL
├── personalities/    # Agent personality system
├── projects/         # Project isolation
├── providers/        # OpenRouter client
└── runtime/          # Agent, memory, teams, orchestration
```

## License

MIT