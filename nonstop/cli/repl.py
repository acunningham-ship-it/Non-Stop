"""Non-Stop REPL — clean, usable multi-agent terminal."""

from __future__ import annotations
import asyncio
import os
import sys
from datetime import datetime

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.completion import Completer, Completion, WordCompleter
from rich.console import Console
from rich.panel import Panel
from rich.markup import escape
from rich.text import Text
from rich.table import Table
from rich.align import Align
from rich import box

from nonstop.cli.commands import CommandRegistry, Command
from nonstop.runtime.supervisor import Supervisor
from nonstop.projects.manager import ProjectManager
from nonstop.personalities import list_presets
from nonstop.board import create_ticket, move_ticket, list_tickets, board_summary, add_comment
from nonstop.runtime.teams import list_teams, TEAM_TEMPLATES
from nonstop.runtime.orchestrator import Orchestrator


# ── Colors ──────────────────────────────────────────────────────────

STYLE = Style.from_dict({
    "prompt": "bold cyan",
})

AGENT_COLORS = [
    "#7C9AE6", "#E67C7C", "#7CE68C", "#E6C87C",
    "#C87CE6", "#7CE6E6", "#E67CAE", "#7CE6AE",
]

VERSION = "0.2.0"

# ── Command autocomplete ───────────────────────────────────────────

class CommandCompleter(Completer):
    """Tab-completes slash commands."""

    def __init__(self, commands: CommandRegistry):
        self.commands = commands

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        partial = text[1:].lower()
        for cmd in self.commands._commands.values():
            names = [cmd.name] + cmd.aliases
            for n in names:
                if n.startswith(partial):
                    yield Completion(f"/{n}", start_position=-len(text))


# ── REPL ────────────────────────────────────────────────────────────

class NonStopREPL:
    """Clean multi-agent terminal."""

    def __init__(self, supervisor: Supervisor, projects: ProjectManager):
        self.supervisor = supervisor
        self.projects = projects
        self.console = Console(highlight=False)
        self.running = True
        self._default_model = "openrouter/openai/gpt-4o-mini"

        self.orchestrator = Orchestrator(
            bus=supervisor.bus,
            supervisor=supervisor,
        )
        supervisor.orchestrator = self.orchestrator

        self._agent_colors: dict[str, str] = {}
        self._color_idx = 0

        self.commands = CommandRegistry()
        self._register_commands()

        self.session = PromptSession(
            history=FileHistory(os.path.expanduser("~/.nonstop_history")),
            style=STYLE,
            completer=CommandCompleter(self.commands),
            complete_while_typing=True,
        )

    def _agent_color(self, name: str) -> str:
        if name not in self._agent_colors:
            self._agent_colors[name] = AGENT_COLORS[self._color_idx % len(AGENT_COLORS)]
            self._color_idx += 1
        return self._agent_colors[name]

    def _register_commands(self):
        cmds = [
            Command("help", self._cmd_help, "Show this help", ["?"]),
            Command("summon", self._cmd_summon, "Spawn an agent — /summon <name> [as <desc>|<preset>]", ["s"]),
            Command("tell", self._cmd_tell, "Message an agent — /tell <name> <message>", ["t"]),
            Command("team", self._cmd_team, "Spawn a team — /team [build|research|debate|review]", []),
            Command("board", self._cmd_board, "Kanban board — /board [add|move|comment]", ["b"]),
            Command("projects", self._cmd_projects, "Manage projects — /projects [new|switch]", ["p"]),
            Command("model", self._cmd_model, "Set default model — /model <name>", ["m"]),
            Command("models", self._cmd_models, "List available models", []),
            Command("agents", self._cmd_agents, "List active agents", ["a"]),
            Command("kill", self._cmd_kill, "Remove an agent — /kill <name>", ["k"]),
            Command("rules", self._cmd_rules, "Orchestration rules — /rules [add|remove]", ["r"]),
            Command("remember", self._cmd_remember, "Show agent memory — /remember <name>", []),
            Command("presets", self._cmd_presets, "List personality presets", []),
            Command("status", self._cmd_status, "System status", ["st"]),
            Command("clear", self._cmd_clear, "Clear screen", ["c"]),
            Command("quit", self._cmd_quit, "Exit Non-Stop", ["q", "exit"]),
        ]
        for cmd in cmds:
            self.commands.register(cmd)

    # ── Streaming ────────────────────────────────────────────────────

    def _on_stream_token(self, name: str, token: str, accumulated: str):
        """Called for each token. Shows a live-updating line."""
        color = self._agent_color(name)
        last_line = accumulated.replace("\n", " ↵ ")[-100:]
        sys.stdout.write(
            f"\r  [{color}]{name}[/] {last_line}{' ' * max(0, 20 - len(last_line))}"
        )
        sys.stdout.flush()

    def _on_stream_end(self, name: str, full_response: str):
        """Streaming done — show the clean panel."""
        color = self._agent_color(name)
        # Clear streaming line
        sys.stdout.write("\r" + " " * (self.console.width or 80) + "\r")
        sys.stdout.flush()

        content = full_response[:1500]
        if len(full_response) > 1500:
            content += "\n… (truncated)"

        panel = Panel(
            escape(content),
            title=f"[{color}]{name}[/]",
            title_align="left",
            border_style=color,
            padding=(0, 1),
            width=None,
            box=box.ROUNDED,
        )
        self.console.print(panel)
        self.console.print()

    # ── Help / Command Menu ─────────────────────────────────────────

    def _show_command_menu(self):
        """Show a compact command menu."""
        table = Table(
            box=box.SIMPLE,
            show_header=False,
            padding=(0, 2),
            collapse=True,
        )
        table.add_column("cmd", style="bold cyan", no_wrap=True)
        table.add_column("desc", style="")

        for cmd in self.commands._commands.values():
            aliases = f" [dim]({', '.join(cmd.aliases)})[/]" if cmd.aliases else ""
            table.add_row(f"/{cmd.name}{aliases}", cmd.help_text)

        self.console.print(table)

    def _show_banner(self):
        """Show a minimal startup banner."""
        self.console.print()
        self.console.print(
            Text("  Non-Stop  ", style="bold cyan") +
            Text(f"v{VERSION}", style="dim") +
            Text("  —  ", style="dim") +
            Text("multi-agent terminal", style="")
        )
        self.console.print(
            Text("  Type / to see commands  |  ", style="dim") +
            Text("export OPENROUTER_API_KEY=...", style="dim")
        )
        self.console.print()

    def _prompt_text(self) -> str:
        """Build a clean prompt showing project context."""
        proj = self.projects.active_name
        agents = self.supervisor.list_agents(project_name=proj)
        busy = sum(1 for a in agents if a["busy"])
        suffix = ""
        if busy:
            suffix = f" ({busy} busy)"
        elif agents:
            suffix = f" ({len(agents)} agents)"
        return f"[{proj}{suffix}]> "

    # ── Slash Commands ───────────────────────────────────────────────

    async def _cmd_help(self, args: str) -> str:
        self._show_command_menu()
        return ""

    async def _cmd_summon(self, args: str) -> str:
        if not args.strip():
            presets = ", ".join(p["name"] for p in list_presets())
            return f"Usage: /summon <name> [as <desc>|<preset>]\nPresets: {presets}"

        parts = args.strip().split(maxsplit=2)
        name = parts[0]
        persona_ref = parts[1] if len(parts) > 1 else ""
        if len(parts) > 2 and parts[1] == "as":
            persona_ref = parts[2]

        result = await self.supervisor.spawn_agent(name, persona_ref, model=self._default_model)
        if isinstance(result, str):
            return f"[red]✗[/] {result}"

        result.set_stream_callbacks(
            on_token=self._on_stream_token,
            on_end=self._on_stream_end,
        )
        return f"[green]✓[/] {name} is ready"

    async def _cmd_tell(self, args: str) -> str:
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            return "Usage: /tell <name> <message>"
        err = await self.supervisor.send_to_agent(parts[0], parts[1])
        if err:
            return f"[red]✗[/] {err}"
        return f"→ {parts[0]}"

    async def _cmd_team(self, args: str) -> str:
        name = args.strip().lower()
        if not name:
            teams = list_teams()
            lines = ["Teams:"]
            for t in teams:
                lines.append(f"  [bold]{t['name']}[/] — {t['description']}")
            return "\n".join(lines)

        results = await self.supervisor.spawn_team(name)
        agents = [r for r in results if not isinstance(r, str)]
        errors = [r for r in results if isinstance(r, str)]

        for a in agents:
            a.set_stream_callbacks(
                on_token=self._on_stream_token,
                on_end=self._on_stream_end,
            )

        lines = []
        if agents:
            lines.append(f"[green]✓[/] Team '{name}': {', '.join(a.name for a in agents)}")
        if errors:
            for e in errors:
                lines.append(f"[red]✗[/] {e}")
        return "\n".join(lines) if lines else f"Unknown team '{name}'"

    async def _cmd_board(self, args: str) -> str:
        parts = args.split(maxsplit=2)
        if not args:
            return board_summary(self.projects.active_name)

        if parts[0] == "add" and len(parts) >= 2:
            tid = create_ticket(parts[1], project=self.projects.active_name)
            return f"[green]✓[/] Ticket #{tid}: {parts[1]}"

        if parts[0] == "move" and len(parts) >= 3:
            try:
                tid = int(parts[1].lstrip("#"))
            except ValueError:
                return "Usage: /board move <#id> <column>"
            err = move_ticket(tid, parts[2])
            return f"[green]✓[/] Ticket #{tid} → {parts[2]}" if not err else f"[red]✗[/] {err}"

        if parts[0] == "comment" and len(parts) >= 3:
            try:
                tid = int(parts[1].lstrip("#"))
            except ValueError:
                return "Usage: /board comment <#id> <text>"
            add_comment(tid, "user", parts[2])
            return f"[green]✓[/] Comment on #{tid}"

        return "Usage: /board add <title> | /board move <#id> <col> | /board comment <#id> <text>"

    async def _cmd_projects(self, args: str) -> str:
        parts = args.split(maxsplit=1)
        if not args:
            lines = ["Projects:"]
            for p in self.projects.list():
                m = "[cyan]»[/]" if p["active"] else " "
                agents = ", ".join(p["agents"]) if p["agents"] else "[dim]empty[/]"
                lines.append(f"  {m} {p['name']}  {agents}")
            return "\n".join(lines)

        if parts[0] == "new" and len(parts) > 1:
            err = await self.projects.create(parts[1])
            return f"[green]✓[/] Created '{parts[1]}'" if not err else f"[red]✗[/] {err}"

        err = await self.projects.switch(parts[0])
        return f"[green]✓[/] Switched to '{parts[0]}'" if not err else f"[red]✗[/] {err}"

    async def _cmd_model(self, args: str) -> str:
        model = args.strip()
        if not model:
            return f"Default model: [bold]{self._default_model}[/]\nUsage: /model <name>"
        self._default_model = model
        return f"[green]✓[/] Model: [bold]{model}[/]"

    async def _cmd_models(self, args: str) -> str:
        models = [
            ("openrouter/openai/gpt-4o", "OpenAI GPT-4o"),
            ("openrouter/openai/gpt-4o-mini", "OpenAI GPT-4o Mini"),
            ("openrouter/anthropic/claude-sonnet-4", "Claude Sonnet 4"),
            ("openrouter/anthropic/claude-opus-4", "Claude Opus 4"),
            ("openrouter/google/gemini-2.0-flash-001", "Gemini 2.0 Flash"),
            ("openrouter/deepseek/deepseek-v4", "DeepSeek V4"),
        ]
        lines = [f"Current: [bold]{self._default_model}[/]\n"]
        for m, d in models:
            marker = " [green]►[/]" if m == self._default_model else "  "
            lines.append(f"{marker} {d}")
            lines.append(f"   [dim]{m}[/]")
        return "\n".join(lines)

    async def _cmd_agents(self, args: str) -> str:
        agents = self.supervisor.list_agents()
        if not agents:
            return "[dim]No agents. Use /summon[/]"
        lines = ["Agents:"]
        for a in agents:
            state = "[bold]●[/] busy" if a["busy"] else "[dim]●[/] idle"
            m = "[cyan]»[/]" if a["active"] else " "
            c = self._agent_color(a["name"])
            lines.append(f"  {m} [{c}]{a['name']}[/]  {state}")
            if not a["active"]:
                lines[-1] += f" [dim](project: {a['project']})[/]"
        return "\n".join(lines)

    async def _cmd_kill(self, args: str) -> str:
        name = args.strip()
        if not name:
            return "Usage: /kill <name>"
        err = await self.supervisor.kill_agent(name)
        return f"[green]✓[/] {name} dismissed" if not err else f"[red]✗[/] {err}"

    async def _cmd_rules(self, args: str) -> str:
        parts = args.split(maxsplit=2)
        if not args:
            rules = self.orchestrator.list_rules(self.projects.active_name)
            if not rules:
                return "[dim]No rules.[/]"
            lines = ["Rules:"]
            for r in rules:
                lines.append(f"  #{r['id']} when [bold]{r['trigger']}[/] → {r['action']}")
            return "\n".join(lines)

        if parts[0] == "add" and len(parts) >= 3:
            self.orchestrator.add_rule(parts[1], parts[2], project=self.projects.active_name)
            return f"[green]✓[/] Rule: when '{parts[1]}' → {parts[2]}"

        if parts[0] == "remove" and len(parts) >= 2:
            try:
                self.orchestrator.remove_rule(int(parts[1]))
                return f"[green]✓[/] Rule #{parts[1]} removed"
            except ValueError:
                return "Usage: /rules remove <id>"

        return "Usage: /rules [add <trigger> <action> | remove <id>]"

    async def _cmd_remember(self, args: str) -> str:
        name = args.strip()
        if not name:
            return "Usage: /remember <name>"
        agent = self.supervisor.get_agent(name)
        if not agent:
            return f"No agent '{name}'"

        facts = agent.memory.recall_all()
        traits = agent.memory.get_profile()
        lines = [f"[bold]{name}[/] memory:"]
        if facts:
            for k, v in facts.items():
                lines.append(f"  {k}: {v[:100]}")
        else:
            lines.append("  [dim]no facts[/]")
        if traits:
            lines.append("")
            for t in traits:
                lines.append(f"  trait: {t['trait']}")
        return "\n".join(lines)

    async def _cmd_presets(self, args: str) -> str:
        presets = list_presets()
        lines = ["Presets — /summon <name> <preset>:"]
        for p in presets:
            lines.append(f"  [bold]{p['name']}[/] — {p['description']}")
        return "\n".join(lines)

    async def _cmd_status(self, args: str) -> str:
        proj = self.projects.active_name
        all_a = self.supervisor.list_agents()
        active = [a for a in all_a if a["active"]]
        bg = [a for a in all_a if not a["active"]]
        tickets = list_tickets(proj)
        rules = self.orchestrator.list_rules(proj)

        lines = [
            f"[bold]Non-Stop v{VERSION}[/]",
            f"Project: [cyan]{proj}[/]  |  Agents: {len(active)} active",
        ]
        if bg:
            lines.append(f"Background: {len(bg)} agents across other projects")
        if tickets:
            cols = {}
            for t in tickets:
                cols[t.column] = cols.get(t.column, 0) + 1
            board_line = ", ".join(f"{k}: {v}" for k, v in cols.items())
            lines.append(f"Board: {len(tickets)} tickets ({board_line})")
        if rules:
            lines.append(f"Rules: {len(rules)} active")
        lines.append(f"Model: {self._default_model}")

        if active:
            lines.append("")
            for a in active:
                state = "busy" if a["busy"] else "idle"
                c = self._agent_color(a["name"])
                lines.append(f"  [{c}]{a['name']}[/] — {state}")
        return "\n".join(lines)

    async def _cmd_clear(self, args: str) -> str:
        self.console.clear()
        return ""

    async def _cmd_quit(self, args: str) -> str:
        self.running = False
        return ""

    # ── Main Loop ────────────────────────────────────────────────────

    async def run(self):
        self._show_banner()

        with patch_stdout():
            while self.running:
                try:
                    text = await self.session.prompt_async(
                        self._prompt_text(),
                        style=STYLE,
                    )

                    if not text.strip():
                        continue

                    # / alone shows command menu
                    if text.strip() == "/":
                        self._show_command_menu()
                        continue

                    if text.startswith("/"):
                        response = await self.commands.route(text)
                        if response:
                            self.console.print(response)
                            self.console.print()
                        continue

                    await self._handle_input(text)

                except KeyboardInterrupt:
                    continue
                except EOFError:
                    break
                except Exception as e:
                    self.console.print(f"  [red]✗ {e}[/]")

        self.console.print()
        self.console.print("[dim]Non-Stop stopped[/]")
        await self.supervisor.shutdown_all()

    async def _handle_input(self, text: str):
        """Route user input to agents."""
        proj = self.projects.active
        if not proj.agents:
            self.console.print("  [dim]No agents. Use /summon or /team[/]\n")
            return

        for name, agent in proj.agents.items():
            if not agent.is_busy:
                await agent.direct_message(text)
                return

        # All busy
        first = list(proj.agents.values())[0]
        self.console.print("  [dim]All agents busy — queued[/]")
        await first.direct_message(text)