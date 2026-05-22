"""Non-Stop REPL — streaming multi-agent terminal with clean formatting."""

from __future__ import annotations
import asyncio
import os
import sys
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.panel import Panel
from rich.markup import escape
from rich.text import Text
from rich.align import Align
from rich.live import Live

from nonstop.cli.commands import CommandRegistry, Command
from nonstop.runtime.supervisor import Supervisor
from nonstop.projects.manager import ProjectManager
from nonstop.personalities import list_presets
from nonstop.board import create_ticket, move_ticket, list_tickets, board_summary, add_comment
from nonstop.runtime.teams import list_teams, TEAM_TEMPLATES
from nonstop.runtime.orchestrator import Orchestrator


# ── Styling ─────────────────────────────────────────────────────────

STYLE = Style.from_dict({
    "prompt": "bold cyan",
    "agent": "bold #7C9AE6",
    "dim": "dim #555555",
})

VERSION = "0.1.0"

# Pick a color for each agent name (cycling palette)
AGENT_COLORS = [
    "#7C9AE6", "#E67C7C", "#7CE68C", "#E6C87C",
    "#C87CE6", "#7CE6E6", "#E67CAE", "#7CE6AE",
]


class NonStopREPL:
    """Professional multi-agent terminal with streaming responses."""

    def __init__(self, supervisor: Supervisor, projects: ProjectManager):
        self.supervisor = supervisor
        self.projects = projects
        self.console = Console(highlight=False)
        self.running = True
        self.orchestrator = Orchestrator(
            bus=supervisor.bus,
            supervisor=supervisor,
        )
        # Wire orchestration into supervisor
        supervisor.orchestrator = self.orchestrator

        # Track agent colors
        self._agent_colors: dict[str, str] = {}
        self._color_idx = 0

        # Active stream state
        self._streaming_agent: str | None = None

        self.session = PromptSession(
            history=FileHistory(os.path.expanduser("~/.nonstop_history")),
            style=STYLE,
        )

        self.commands = CommandRegistry()
        self._register_commands()

    def _agent_color(self, name: str) -> str:
        if name not in self._agent_colors:
            self._agent_colors[name] = AGENT_COLORS[
                self._color_idx % len(AGENT_COLORS)
            ]
            self._color_idx += 1
        return self._agent_colors[name]

    def _register_commands(self):
        cmds = [
            Command("help", self._cmd_help, "Show this help", ["h"]),
            Command("projects", self._cmd_projects,
                    "Manage projects: /projects, /projects new <name>, /projects <name>", ["p"]),
            Command("summon", self._cmd_summon,
                    "Summon an agent: /summon <name> [as|preset] [description]", ["s", "spawn"]),
            Command("team", self._cmd_team,
                    "Spawn a coordinated team: /team <build|research|debate|review>", ["t"]),
            Command("agents", self._cmd_agents, "List active agents", ["a", "ls"]),
            Command("tell", self._cmd_tell, "Send message to an agent: /tell <name> <message>", ["t"]),
            Command("kill", self._cmd_kill, "Remove an agent: /kill <name>", ["k", "remove"]),
            Command("presets", self._cmd_presets, "Show available personality presets"),
            Command("board", self._cmd_board,
                    "Kanban board: /board, /board add <title>, /board move <#id> <column>, /board comment <#id> <text>", ["b"]),
            Command("rules", self._cmd_rules,
                    "Orchestration rules: /rules, /rules add <trigger> <action>, /rules remove <id>", ["r"]),
            Command("remember", self._cmd_remember,
                    "Check what an agent remembers: /remember <agent_name>", ["mem"]),
            Command("model", self._cmd_model,
                    "Set default model: /model <name>  e.g. /model openrouter/anthropic/claude-sonnet-4", ["m"]),
            Command("models", self._cmd_models,
                    "List available models and current default"),
            Command("status", self._cmd_status, "Show system status", ["st"]),
            Command("clear", self._cmd_clear, "Clear the display", ["c"]),
            Command("quit", self._cmd_quit, "Exit Non-Stop", ["q", "exit"]),
        ]
        for cmd in cmds:
            self.commands.register(cmd)

    # ── Streaming Callbacks ──────────────────────────────────────────

    def _on_stream_token(self, name: str, token: str, accumulated: str):
        """Called for each token in a streaming response."""
        color = self._agent_color(name)
        preview_len = min(len(accumulated), self.console.width - 12)

        # Show just the last line-worth of content streaming
        display = accumulated[-preview_len:] if len(accumulated) > preview_len else accumulated
        display = display.replace("\n", "↵ ")

        sys.stdout.write(
            f"\r  [{color}]⏵[/] {display:<{self.console.width - 8}}"
        )
        sys.stdout.flush()

    def _on_stream_end(self, name: str, full_response: str):
        """Called when streaming completes. Render the final panel."""
        color = self._agent_color(name)

        # Clear the streaming line
        sys.stdout.write("\r" + " " * self.console.width + "\r")
        sys.stdout.flush()

        short_label = full_response[:60].replace("\n", " ")

        # Render in a clean panel
        display = full_response[:1200]
        if len(full_response) > 1200:
            display += "\n\n[...]"

        panel = Panel(
            escape(display),
            title=f"[{color}]{name}[/]",
            title_align="left",
            border_style=color,
            padding=(1, 2),
            width=self.console.width - 4,
        )
        self.console.print(panel)
        self.console.print()

    # ── Rendering ────────────────────────────────────────────────────

    def _render_header(self):
        """Print the session header with branding."""
        self.console.print()
        self.console.print(Panel(
            Align.center(
                Text("Non-Stop", style="bold cyan") + Text(f"  v{VERSION}", style="dim")
            ),
            style="bold",
            border_style="cyan",
            padding=(0, 2),
        ))
        self.console.print()
        self._render_status_bar()

    def _render_status_bar(self):
        """Render the current status."""
        proj = self.projects.active_name
        agent_count = len(self.projects.active.agents)
        busy_count = sum(1 for a in self.supervisor.list_agents(
            project_name=self.projects.active_name
        ) if a["busy"])
        bg_count = len(self.supervisor.list_agents()) - agent_count

        parts = [f"  Project: [bold cyan]{proj}[/]"]
        if agent_count > 0:
            parts.append(f"Agents: {agent_count} ({busy_count} busy)")
        if bg_count > 0:
            parts.append(f"[dim]Background: {bg_count}[/]")
        self.console.print("  │  ".join(parts))
        self.console.print()

    def _render_status(self, message: str):
        sys.stdout.write(f"\r  ⏵ {message:<{self.console.width - 8}}\n")
        sys.stdout.flush()

    # ── Slash Commands ───────────────────────────────────────────────

    async def _cmd_help(self, args: str) -> str:
        lines = [
            f"[bold]Non-Stop v{VERSION}[/] — Multi-agent terminal\n",
            "Commands:",
        ]
        for cmd in self.commands._commands.values():
            aliases = f" [dim]({', '.join(cmd.aliases)})[/]" if cmd.aliases else ""
            lines.append(f"  [bold]/{cmd.name}[/]{aliases}")
            lines.append(f"    {cmd.help_text}")
        lines.extend([
            "",
            "Agents are blank slates — define them through conversation.",
            "  e.g. \"You are a ruthless skeptic. Tear apart everything I say.\"",
            "",
            "Agents can delegate to each other with @name: instructions.",
            "  e.g. \"@archie: design the API for me\"",
        ])
        return "\n".join(lines)

    async def _cmd_summon(self, args: str) -> str:
        """Summon an agent. Flexible syntax:
           /summon <name>
           /summon <name> as <description>
           /summon <name> <preset>
        """
        if not args.strip():
            return "Usage: /summon <name> [as <description>] or /summon <name> <preset>\n" \
                   "Presets: " + ", ".join(p["name"] for p in list_presets())

        parts = args.strip().split(maxsplit=2)
        name = parts[0]

        # Determine persona reference
        persona_ref = ""
        if len(parts) > 1:
            if parts[1] == "as" and len(parts) > 2:
                persona_ref = parts[2]
            else:
                persona_ref = parts[1]

        default_model = getattr(self, '_default_model', '')
        result = await self.supervisor.spawn_agent(name, persona_ref, model=default_model)

        if isinstance(result, str):
            return f"[red]✗[/] {result}"

        # Wire streaming callbacks
        result.set_stream_callbacks(
            on_token=self._on_stream_token,
            on_end=self._on_stream_end,
        )

        self._render_status(f"Summoned [bold]{name}[/]")
        self._render_status_bar()
        return ""

    async def _cmd_agents(self, args: str) -> str:
        agents = self.supervisor.list_agents()
        if not agents:
            return "[yellow]No agents yet. Use /summon to create one.[/]"

        lines = ["[bold]Agents:[/]"]
        for a in agents:
            state = "[bold]●[/] busy" if a["busy"] else "[dim]●[/] idle"
            marker = "[cyan]»[/]" if a["active"] else " "
            color = self._agent_color(a["name"])
            lines.append(
                f"  {marker} [{color}]{a['name']}[/]  {state}  "
                f"[dim](project: {a['project']})[/]"
            )
        return "\n".join(lines)

    async def _cmd_projects(self, args: str) -> str:
        parts = args.split(maxsplit=1)
        if not args:
            lines = ["[bold]Projects:[/]"]
            for p in self.projects.list():
                marker = "[bold cyan]»[/]" if p["active"] else " "
                agents = ", ".join(p["agents"]) if p["agents"] else "[dim](empty)[/]"
                lines.append(f"  {marker} [cyan]{p['name']}[/] — {agents}")
            return "\n".join(lines)
        elif parts[0] == "new" and len(parts) > 1:
            err = await self.projects.create(parts[1])
            if err:
                return f"[red]✗[/] {err}"
            self._render_status(f"Created project '{parts[1]}'")
            return f"[green]✓[/] Created '[cyan]{parts[1]}[/]'"
        else:
            target = parts[0]
            err = await self.projects.switch(target)
            if err:
                return f"[red]✗[/] {err}"
            self._render_status(f"Switched to project '{target}'")
            self._render_status_bar()
            return ""

    async def _cmd_tell(self, args: str) -> str:
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            return "Usage: /tell <agent_name> <message>"
        agent_name, message = parts[0], parts[1]
        err = await self.supervisor.send_to_agent(agent_name, message)
        if err:
            return f"[red]✗[/] {err}"
        self._render_status(f"Sent to {agent_name}")
        return ""

    async def _cmd_kill(self, args: str) -> str:
        name = args.strip()
        if not name:
            return "Usage: /kill <agent_name>"
        err = await self.supervisor.kill_agent(name)
        if err:
            return f"[red]✗[/] {err}"
        self._render_status(f"Dismissed [bold]{name}[/]")
        self._render_status_bar()
        return ""

    async def _cmd_presets(self, args: str) -> str:
        presets = list_presets()
        lines = ["[bold]Presets:[/]"]
        for p in presets:
            lines.append(f"  [bold]{p['name']}[/] — {p['description']}")
        lines.append("")
        lines.append("[dim]Or use free-form: /summon <name> as <description>[/]")
        return "\n".join(lines)

    async def _cmd_team(self, args: str) -> str:
        """Spawn a coordinated team."""
        template_name = args.strip().lower()
        if not template_name:
            teams = list_teams()
            lines = ["[bold]Team templates:[/]"]
            for t in teams:
                agents = ", ".join(t["agents"])
                lines.append(f"  [bold]{t['name']}[/] — {t['description']}")
                lines.append(f"    Agents: {agents}")
            return "\n".join(lines)

        results = await self.supervisor.spawn_team(template_name)
        errors = [r for r in results if isinstance(r, str)]
        agents = [r for r in results if not isinstance(r, str)]

        lines = []
        if agents:
            names = ", ".join(a.name for a in agents)
            lines.append(f"[green]✓[/] Team '{template_name}' spawned: {names}")
        if errors:
            for e in errors:
                lines.append(f"[red]✗[/] {e}")
        self._render_status_bar()
        return "\n".join(lines) if lines else f"No team '{template_name}'"

    async def _cmd_board(self, args: str) -> str:
        """Kanban board management."""
        parts = args.split(maxsplit=2)
        if not args:
            return board_summary(self.projects.active_name)

        if parts[0] == "add" and len(parts) >= 2:
            title = parts[1]
            ticket_id = create_ticket(title, project=self.projects.active_name)
            return f"[green]✓[/] Ticket #[bold]{ticket_id}[/] created: {title}"

        elif parts[0] == "move" and len(parts) >= 2:
            # /board move <#id or id> <column>
            sub = parts[1].lstrip("#")
            if len(parts) < 3:
                return "Usage: /board move <#id> <column>"
            try:
                ticket_id = int(sub)
            except ValueError:
                return "Usage: /board move <#id> <column>"
            err = move_ticket(ticket_id, parts[2])
            if err:
                return f"[red]✗[/] {err}"
            return f"[green]✓[/] Ticket #{ticket_id} moved to '{parts[2]}'"

        elif parts[0] == "comment" and len(parts) >= 2:
            sub = parts[1].lstrip("#")
            if len(parts) < 3:
                return "Usage: /board comment <#id> <text>"
            try:
                ticket_id = int(sub)
            except ValueError:
                return "Usage: /board comment <#id> <text>"
            add_comment(ticket_id, "user", parts[2])
            return f"[green]✓[/] Comment added to ticket #{ticket_id}"

        else:
            return "Usage: /board, /board add <title>, /board move <#id> <col>, /board comment <#id> <text>"

    async def _cmd_rules(self, args: str) -> str:
        """Orchestration rules management."""
        parts = args.split(maxsplit=2)
        if not args:
            rules = self.orchestrator.list_rules(self.projects.active_name)
            if not rules:
                return "[dim]No orchestration rules defined.[/]"
            lines = ["[bold]Orchestration rules:[/]"]
            for r in rules:
                status = "[green]●[/]" if r["enabled"] else "[dim]○[/]"
                lines.append(f"  {status} #{r['id']} when [bold]{r['trigger']}[/] → {r['action']} [dim](by {r['created_by']})[/]")
            return "\n".join(lines)

        if parts[0] == "add" and len(parts) >= 3:
            trigger = parts[1]
            action = parts[2]
            self.orchestrator.add_rule(trigger, action, project=self.projects.active_name)
            return f"[green]✓[/] Rule added: when '{trigger}' → {action}"

        if parts[0] == "remove" and len(parts) >= 2:
            try:
                rule_id = int(parts[1])
            except ValueError:
                return "Usage: /rules remove <id>"
            self.orchestrator.remove_rule(rule_id)
            return f"[green]✓[/] Rule #{rule_id} removed"

        if parts[0] == "enable" and len(parts) >= 2:
            return "Use /rules then manually toggle (not implemented yet)"

        return "Usage: /rules, /rules add <trigger> <action>, /rules remove <id>"

    async def _cmd_remember(self, args: str) -> str:
        """Show what an agent remembers."""
        name = args.strip()
        if not name:
            return "Usage: /remember <agent_name>"
        agent = self.supervisor.get_agent(name)
        if not agent:
            return f"No agent '{name}' found"
        mem = agent.memory.recall_all()
        traits = agent.memory.get_profile()
        lines = [f"[bold]Memory for {name}:[/]"]
        if mem:
            for k, v in mem.items():
                lines.append(f"  {k}: {v[:100]}")
        else:
            lines.append("  [dim]No stored facts.[/]")
        if traits:
            lines.append(f"\n[bold]Learned traits:[/]")
            for t in traits:
                lines.append(f"  {t['trait']} (confidence: {t['confidence']:.1f})")
        return "\n".join(lines)

    # ── Model commands ───────────────────────────────────────────

    async def _cmd_model(self, args: str) -> str:
        """Set the default model for new agents."""
        model = args.strip()
        if not model:
            current = getattr(self, '_default_model', 'openrouter/openai/gpt-4o-mini')
            return f"Current default model: [bold]{current}[/]\nUsage: /model <full_model_name>\n  e.g. /model openrouter/anthropic/claude-sonnet-4"
        self._default_model = model
        from nonstop.personalities import BUILTIN_PERSONALITIES, blank_slate
        # Update personality model defaults
        for name in BUILTIN_PERSONALITIES:
            BUILTIN_PERSONALITIES[name] = BUILTIN_PERSONALITIES[name]  # keep presets as-is
        return f"[green]✓[/] Default model set to: [bold]{model}[/]\n[dim]New agents will use this model.[/]"

    async def _cmd_models(self, args: str) -> str:
        """List models and the current default."""
        current = getattr(self, '_default_model', 'openrouter/openai/gpt-4o-mini')

        models = [
            ("openrouter/openai/gpt-4o", "OpenAI GPT-4o (fast, general)"),
            ("openrouter/openai/gpt-4o-mini", "OpenAI GPT-4o Mini (cheap, fast)"),
            ("openrouter/anthropic/claude-sonnet-4", "Anthropic Claude Sonnet 4 (reasoning)"),
            ("openrouter/anthropic/claude-opus-4", "Anthropic Claude Opus 4 (best)"),
            ("openrouter/google/gemini-2.0-flash-001", "Google Gemini 2.0 Flash"),
            ("openrouter/deepseek/deepseek-v4", "DeepSeek V4"),
            ("openrouter/meta-llama/llama-4", "Meta Llama 4"),
            ("openrouter/qwen/qwen-3", "Qwen 3"),
            ("openrouter/mistral/mistral-large", "Mistral Large"),
        ]
        lines = [
            f"[bold]Current default:[/] {current}\n",
            "[bold]Common models:[/]",
        ]
        for model_name, desc in models:
            marker = "[green]►[/]" if model_name == current else " "
            lines.append(f"  {marker} {desc}")
            lines.append(f"     [dim]{model_name}[/]")
        lines.append("")
        lines.append("[dim]Set with: /model <full_name>[/]")
        return "\n".join(lines)

    async def _cmd_status(self, args: str) -> str:
        lines = [f"[bold]Non-Stop v{VERSION}[/]\n"]
        lines.append(f"[bold]Current Project:[/] [cyan]{self.projects.active_name}[/]")
        lines.append(f"  Total projects: {len(self.projects.projects)}")

        # Board stats
        tickets = list_tickets(self.projects.active_name)
        if tickets:
            cols = {}
            for t in tickets:
                cols[t.column] = cols.get(t.column, 0) + 1
            board_line = ", ".join(f"{k}: {v}" for k, v in cols.items())
            lines.append(f"  Board: {len(tickets)} tickets ({board_line})")

        # Rules count
        rules = self.orchestrator.list_rules(self.projects.active_name) if self.orchestrator else []
        if rules:
            lines.append(f"  Rules: {len(rules)} active")

        all_a = self.supervisor.list_agents()
        active = [a for a in all_a if a["active"]]
        bg = [a for a in all_a if not a["active"]]

        lines.append(f"\n[bold]Active agents:[/] {len(active)}")
        for a in active:
            state = "[bold]busy[/]" if a["busy"] else "[dim]idle[/]"
            trait_str = f" [{', '.join(a['traits'])}]" if a.get("traits") else ""
            lines.append(f"  {a['name']} — {state}{trait_str}")

        if bg:
            lines.append(f"\n[bold]Background agents:[/] {len(bg)}")
            for a in bg:
                lines.append(f"  {a['name']} [dim](project: {a['project']})[/]")
        return "\n".join(lines)

    async def _cmd_clear(self, args: str) -> str:
        return f"[green]✓[/] Cleared"

    async def _cmd_quit(self, args: str) -> str:
        self.running = False
        return ""

    # ── Main Loop ────────────────────────────────────────────────────

    async def run(self):
        self._render_header()

        with patch_stdout():
            while self.running:
                try:
                    text = await self.session.prompt_async(
                        f"[{self.projects.active_name}]> ",
                        style=STYLE,
                    )

                    if not text.strip():
                        continue

                    if text.startswith("/"):
                        response = await self.commands.route(text)
                        if response:
                            self.console.print(response)
                            self.console.print()
                        continue

                    await self._handle_user_input(text)

                except KeyboardInterrupt:
                    continue
                except EOFError:
                    break
                except Exception as e:
                    self._render_status(f"[red]Error:[/] {e}")

        self.console.print()
        self.console.print(Panel(
            Align.center(Text("Non-Stop shutting down...", style="dim")),
            border_style="dim",
        ))
        await self.supervisor.shutdown_all()
        self.console.print("[green]✓ Stopped[/]")

    async def _handle_user_input(self, text: str):
        proj = self.projects.active

        if not proj.agents:
            self.console.print(
                "  [yellow]No agents in this project.[/] [dim]Use /summon to add one.[/]\n"
            )
            return

        # Find an idle agent
        for name, agent in proj.agents.items():
            if not agent.is_busy:
                self._render_status(f"→ {name}")
                await agent.direct_message(text)
                return

        # All busy
        self._render_status("[yellow]All agents busy. Queuing to first agent...[/]")
        first_agent = list(proj.agents.values())[0]
        await first_agent.direct_message(text)