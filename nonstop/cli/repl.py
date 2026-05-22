"""Non-Stop REPL — Gorgeous, modern terminal UI with a professional developer dashboard."""

from __future__ import annotations
import asyncio
import os
import sys
import time
from datetime import datetime

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.completion import Completer, Completion
from rich.console import Console
from rich.panel import Panel
from rich.markup import escape
from rich.text import Text
from rich.align import Align
from rich.table import Table
from rich.columns import Columns
from rich import box

from nonstop.cli.commands import CommandRegistry, Command
from nonstop.runtime.supervisor import Supervisor
from nonstop.projects.manager import ProjectManager
from nonstop.personalities import list_presets
from nonstop.board import create_ticket, move_ticket, list_tickets, board_summary, add_comment
from nonstop.runtime.teams import list_teams, TEAM_TEMPLATES
from nonstop.runtime.orchestrator import Orchestrator


# ── Vercel/Linear-inspired Terminal Palette ─────────────────────────

STYLE = Style.from_dict({
    "prompt": "bold #4AF626", # Retro hacker green prompt marker
    "pygments.completion": "bg:#1e1e1e #ffffff",
    "pygments.completion.current": "bg:#3c3c3c #ffffff bold",
})

AGENT_COLORS = [
    "cyan", "bright_magenta", "bright_green", "yellow",
    "magenta", "bright_cyan", "bright_yellow", "bright_blue"
]

VERSION = "0.2.0"

# ── Clean Command Autocomplete ─────────────────────────────────────

class CommandCompleter(Completer):
    """Tab-completes slash commands with dynamic context."""

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
                    yield Completion(
                        f"/{n}", 
                        start_position=-len(text),
                        display=f"/{n} — {cmd.help_text[:40]}"
                    )


# ── Gorgeous Interactive REPL ───────────────────────────────────────

class NonStopREPL:
    """Beautiful developer-focused multi-agent terminal."""

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
            Command("help", self._cmd_help, "Show design menu and guide", ["?"]),
            Command("summon", self._cmd_summon, "Summon agent — /summon <name> [as <desc>|<preset>]", ["s"]),
            Command("tell", self._cmd_tell, "Direct message — /tell <name> <message>", ["t"]),
            Command("team", self._cmd_team, "Spawn specialized team — /team [build|research|debate|review]", []),
            Command("board", self._cmd_board, "Show interactive board — /board [add|move|comment]", ["b"]),
            Command("projects", self._cmd_projects, "Switch workspaces — /projects [new|switch]", ["p"]),
            Command("model", self._cmd_model, "Change running LLM — /model <name>", ["m"]),
            Command("models", self._cmd_models, "Show premium model selection", []),
            Command("agents", self._cmd_agents, "Display running agents", ["a"]),
            Command("kill", self._cmd_kill, "Decommission agent — /kill <name>", ["k"]),
            Command("rules", self._cmd_rules, "Display rule chains — /rules [add|remove]", ["r"]),
            Command("remember", self._cmd_remember, "Inspect cognitive state — /remember <name>", []),
            Command("presets", self._cmd_presets, "Enumerate behavior presets", []),
            Command("status", self._cmd_status, "Deep telemetry inspection", ["st"]),
            Command("clear", self._cmd_clear, "Purge display log", ["c"]),
            Command("quit", self._cmd_quit, "Graceful absolute exit", ["q", "exit"]),
        ]
        for cmd in cmds:
            self.commands.register(cmd)

    # ── High-Fidelity Streaming ──────────────────────────────────────

    def _on_stream_token(self, name: str, token: str, accumulated: str):
        """Elegant console status animation for active token generation."""
        color = self._agent_color(name)
        cleaned_tok = accumulated.replace("\n", " ↵ ")[-60:]
        # Render a gorgeous minimalist spinner bar
        sys.stdout.write(
            f"\r  [dim]⚡[/] [[{color}]{name}[/]] [italic white]{cleaned_tok}[/]{' ' * max(0, 15 - len(cleaned_tok))}"
        )
        sys.stdout.flush()

    def _on_stream_end(self, name: str, full_response: str):
        """Render a sophisticated custom card block with rounded corners."""
        color = self._agent_color(name)
        # Clean inline lines completely
        sys.stdout.write("\r" + " " * (self.console.width or 80) + "\r")
        sys.stdout.flush()

        # Render with Markdown-like professional title styling
        panel = Panel(
            Text.from_markup(escape(full_response)),
            title=f" ◈  [{color} bold]{name}[/] [dim]({self._default_model.split('/')[-1]})[/] ",
            title_align="left",
            border_style=f"bold {color}",
            padding=(1, 2),
            box=box.ROUNDED,
        )
        self.console.print()
        self.console.print(panel)
        self.console.print()

    # ── Custom Rich UI Layout Panels ─────────────────────────────────

    def _show_command_menu(self):
        """Show gorgeous grid of options designed for terminal workspaces."""
        table = Table(
            box=box.MINIMAL,
            show_header=True,
            header_style="bold cyan",
            padding=(0, 2),
        )
        table.add_column("Command", style="bold green")
        table.add_column("Aliases", style="dim")
        table.add_column("Operational Description", style="italic")

        for cmd in self.commands._commands.values():
            aliases = ", ".join(cmd.aliases) if cmd.aliases else "—"
            table.add_row(f"/{cmd.name}", aliases, cmd.help_text)

        self.console.print(Panel(
            table,
            title=" SYSTEM OPERATIONAL COMMANDS ",
            title_align="center",
            border_style="cyan",
            padding=(1, 1)
        ))

    def _show_banner(self):
        """Show a premium design-focused splash screen."""
        self.console.print()
        banner_content = (
            "      _  __               ____  _                \n"
            "     / |/ /___  ___  ____/_  _/( )___  ___  ___  \n"
            "    /    // _ \\/ _ \\/___/ / /  |// _ \\/ _ \\/ _ \\ \n"
            "   /_/|_/ \\___/_//_/     /_/     \\___/ .__/ .__/ \n"
            "                                    /_/  /_/     "
        )
        self.console.print(Align.center(Text(banner_content, style="bold cyan")))
        self.console.print()
        self.console.print(Align.center(
            Text("ENGINE CONFIGU ATION READY", style="dim") +
            Text("  |  ", style="bright_magenta") +
            Text(f"STATION VERSION v{VERSION}", style="bold #4AF626") +
            Text("  |  ", style="bright_magenta") +
            Text("DURABLE CONTEXT ACTIVE", style="dim")
        ))
        self.console.print()
        self._render_status_bar()

    def _render_status_bar(self):
        """Minimalist high-tech status line."""
        proj = self.projects.active_name
        agents = self.supervisor.list_agents(project_name=proj)
        busy = sum(1 for a in agents if a["busy"])
        
        status_line = (
            f" [bold black bg:cyan] WORKSPACE: {proj.upper()} [/]"
            f"  [bold]●[/] {len(agents)} Active Agents"
            f"  [bold]●[/] {busy} Engaged"
            f"  [bold]●[/] Model: [{STYLE['prompt']}]{self._default_model.split('/')[-1]}[/]"
        )
        self.console.print(status_line)
        self.console.print()

    def _prompt_text(self) -> str:
        """Create sleek command line."""
        proj = self.projects.active_name
        return f"[dim]nonstop[/][cyan]@{proj}[/]::▶ "

    # ── Enhanced Command Implementations ──────────────────────────────

    async def _cmd_help(self, args: str) -> str:
        self._show_command_menu()
        return ""

    async def _cmd_summon(self, args: str) -> str:
        if not args.strip():
            presets = ", ".join(p["name"] for p in list_presets())
            return f"[yellow]⚡[/] Usage: /summon <name> [as <desc>|<preset>]\nAvailable presets: {presets}"

        parts = args.strip().split(maxsplit=2)
        name = parts[0]
        persona_ref = parts[1] if len(parts) > 1 else ""
        if len(parts) > 2 and parts[1] == "as":
            persona_ref = parts[2]

        result = await self.supervisor.spawn_agent(name, persona_ref, model=self._default_model)
        if isinstance(result, str):
            return f"[red]✗[/] Spawn error: {result}"

        result.set_stream_callbacks(
            on_token=self._on_stream_token,
            on_end=self._on_stream_end,
        )
        return f"  [green]✔[/] Agent [bold cyan]{name}[/] initialized and standing by to execute."

    async def _cmd_tell(self, args: str) -> str:
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            return "[yellow]⚡[/] Usage: /tell <name> <message>"
        err = await self.supervisor.send_to_agent(parts[0], parts[1])
        if err:
            return f"[red]✗[/] Offline state: {err}"
        return f"  [dim]▶[/] Dispatching instructions to [{self._agent_color(parts[0])}]{parts[0]}[/]..."

    async def _cmd_team(self, args: str) -> str:
        name = args.strip().lower()
        if not name:
            teams = list_teams()
            lines = ["[bold info]Available Team Formations:[/]\n"]
            for t in teams:
                lines.append(f"  ◈  [bold cyan]{t['name'].upper()}[/] — {t['description']}")
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
            lines.append(f"  [green]✔[/] Formation [bold cyan]{name.upper()}[/] deployed successfully!")
            lines.append(f"     Sub-systems: " + ", ".join(f"[{self._agent_color(a.name)}]{a.name}[/]" for a in agents))
        if errors:
            for e in errors:
                lines.append(f"  [red]✗[/] {e}")
        return "\n".join(lines) if lines else f"Unknown team formation '{name}'"

    async def _cmd_board(self, args: str) -> str:
        parts = args.split(maxsplit=2)
        if not args:
            # Render a beautiful multi-column physical Kanban layout
            active_proj = self.projects.active_name
            cols = ["backlog", "in_progress", "review", "done"]
            panels = []
            
            for c in cols:
                tickets_in_col = list_tickets(active_proj, c)
                ticket_table = Table(show_header=False, box=box.SIMPLE_HEAD, collapse=True)
                ticket_table.add_column("Info")
                
                for t in tickets_in_col:
                    assigned = f" ([dim]@{t.assigned_to}[/])" if t.assigned_to else ""
                    ticket_table.add_row(f"[bold cyan]#{t.id}[/] {t.title}{assigned}")
                
                panels.append(Panel(
                    ticket_table,
                    title=f" {c.upper()} ({len(tickets_in_col)}) ",
                    border_style="cyan" if c == "in_progress" else "dim",
                    padding=(0, 1),
                    box=box.ROUNDED,
                ))
            
            self.console.print(Columns(panels, equal=True))
            return ""

        if parts[0] == "add" and len(parts) >= 2:
            tid = create_ticket(parts[1], project=self.projects.active_name)
            return f"  [green]✔[/] Logged task [bold cyan]#{tid}[/] in project backlog."

        if parts[0] == "move" and len(parts) >= 3:
            try:
                tid = int(parts[1].lstrip("#"))
            except ValueError:
                return "[yellow]⚡[/] Usage: /board move <#id> <column>"
            err = move_ticket(tid, parts[2])
            return f"  [green]✔[/] Ticket [bold cyan]#{tid}[/] migrated to state [bold magenta]{parts[2]}[/]." if not err else f"  [red]✗[/] {err}"

        if parts[0] == "comment" and len(parts) >= 3:
            try:
                tid = int(parts[1].lstrip("#"))
            except ValueError:
                return "[yellow]⚡[/] Usage: /board comment <#id> <text>"
            add_comment(tid, "user", parts[2])
            return f"  [green]✔[/] Comment appended to transaction [bold cyan]#{tid}[/]."

        return "[yellow]⚡[/] Usage: /board [add <title> | move <#id> <col> | comment <#id> <text>]"

    async def _cmd_projects(self, args: str) -> str:
        parts = args.split(maxsplit=1)
        if not args:
            table = Table(box=box.MINIMAL_DOUBLE, show_header=True)
            table.add_column("Workspace", style="bold cyan")
            table.add_column("Registered Agents", style="green")
            
            for p in self.projects.list():
                workspace_str = f"◈ {p['name'].upper()}"
                if p["active"]:
                    workspace_str = f"[bold green]▶ {p['name'].upper()} (Current)[/]"
                agents_str = ", ".join(p["agents"]) if p["agents"] else "[dim]None[/]"
                table.add_row(workspace_str, agents_str)
                
            self.console.print(Panel(table, border_style="cyan", title=" CORE WORKSPACE MATRIX "))
            return ""

        if parts[0] == "new" and len(parts) > 1:
            err = await self.projects.create(parts[1])
            return f"  [green]✔[/] Project environment [bold green]'{parts[1].upper()}'[/] allocated." if not err else f"  [red]✗[/] Allocation failed: {err}"

        err = await self.projects.switch(parts[0])
        return f"  [green]✔[/] Workspace context redirected to [bold green]'{parts[0].upper()}'[/]." if not err else f"  [red]✗[/] Workspace resolve error: {err}"

    async def _cmd_model(self, args: str) -> str:
        model = args.strip()
        if not model:
            return f"[yellow]⚡[/] Default running model: [bold]{self._default_model}[/]"
        self._default_model = model
        return f"  [green]✔[/] Master routing path linked to [bold magenta]{model}[/]."

    async def _cmd_models(self, args: str) -> str:
        models = [
            ("openrouter/google/gemini-2.5-flash", "Google Gemini 2.5 Flash"),
            ("openrouter/google/gemini-2.5-pro", "Google Gemini 2.5 Pro"),
            ("openrouter/openai/gpt-4o", "OpenAI GPT-4o"),
            ("openrouter/openai/gpt-4o-mini", "OpenAI GPT-4o Mini (Ultra-performance)"),
            ("openrouter/anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet"),
            ("openrouter/deepseek/deepseek-v3", "DeepSeek V3"),
        ]
        table = Table(box=box.SIMPLE, show_header=False)
        table.add_column("Active Indicator")
        table.add_column("ID")
        table.add_column("Specifications")
        
        for m, d in models:
            marker = "[bold cyan]►[/]" if m == self._default_model else " "
            table.add_row(marker, f"[bold]{d}[/]", f"[dim]{m}[/]")
            
        self.console.print(Panel(table, title=" AVAILABLE COGNITIVE ROUTERS ", border_style="cyan"))
        return ""

    async def _cmd_agents(self, args: str) -> str:
        agents = self.supervisor.list_agents()
        if not agents:
            return "  [dim]No system nodes initialized. Summon with /summon.[/]"
        
        table = Table(box=box.MINIMAL_HEAVY, show_header=True)
        table.add_column("Node ID", style="bold")
        table.add_column("Status", style="bold")
        table.add_column("Affiliation Workspace", style="dim")
        
        for a in agents:
            state = "[bold green]ONLINE (Idle)[/]"
            if a["busy"]:
                state = "[bold yellow]COMPUTING (Thinking)[/]"
            name_colored = f"[{self._agent_color(a['name'])}]{a['name']}[/]"
            
            table.add_row(name_colored, state, a["project"].upper())
            
        self.console.print(Panel(table, title=" COGNITIVE TELEMETRY STATUS "))
        return ""

    async def _cmd_kill(self, args: str) -> str:
        name = args.strip()
        if not name:
            return "[yellow]⚡[/] Usage: /kill <name>"
        err = await self.supervisor.kill_agent(name)
        return f"  [green]✔[/] Agent node [bold red]{name}[/] purged from memory loop." if not err else f"  [red]✗[/] Pure error: {err}"

    async def _cmd_rules(self, args: str) -> str:
        parts = args.split(maxsplit=2)
        if not args:
            rules = self.orchestrator.list_rules(self.projects.active_name)
            if not rules:
                return "  [dim]System chains are blank. Insert a link with /rules add.[/]"
            
            table = Table(box=box.SIMPLE, show_header=True)
            table.add_column("ID", style="bold")
            table.add_column("Trigger Stream", style="italic")
            table.add_column("Target Chain Pipeline", style="bold green")
            
            for r in rules:
                table.add_row(f"#{r['id']}", r['trigger'], r['action'])
            self.console.print(Panel(table, title=" CORE ROUTING CHAINS "))
            return ""

        if parts[0] == "add" and len(parts) >= 3:
            self.orchestrator.add_rule(parts[1], parts[2], project=self.projects.active_name)
            return f"  [green]✔[/] System chain instantiated: when [italic]{parts[1]}[/] ➔ [bold green]{parts[2]}[/]."

        if parts[0] == "remove" and len(parts) >= 2:
            try:
                self.orchestrator.remove_rule(int(parts[1]))
                return f"  [green]✔[/] Chain link #{parts[1]} decoupled."
            except ValueError:
                return "[yellow]⚡[/] Usage: /rules remove <id>"

        return "[yellow]⚡[/] Usage: /rules [add <trigger> <action> | remove <id>]"

    async def _cmd_remember(self, args: str) -> str:
        name = args.strip()
        if not name:
            return "[yellow]⚡[/] Usage: /remember <name>"
        agent = self.supervisor.get_agent(name)
        if not agent:
            return f"  [red]✗[/] Resolved target not found: '{name}'"

        facts = agent.memory.recall_all()
        traits = agent.memory.get_profile()
        
        table = Table(box=box.SIMPLE, show_header=False)
        table.add_column("Type", style="bold")
        table.add_column("Payload")
        
        for k, v in facts.items():
            table.add_row(k.upper().replace("_", " "), v)
        for t in traits:
            table.add_row("LEARNED TRAIT", f"[italic cyan]{t['trait']}[/]")
            
        self.console.print(Panel(table, title=f" {name.upper()}'S COGNITIVE BASE "))
        return ""

    async def _cmd_presets(self, args: str) -> str:
        presets = list_presets()
        table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold green")
        table.add_column("Preset Pattern")
        table.add_column("Internal System Prompt Matrix")
        for p in presets:
            table.add_row(p['name'], p['description'])
        self.console.print(Panel(table, title=" COGNITIVE BEHAVIOR PATTERNS "))
        return ""

    async def _cmd_status(self, args: str) -> str:
        proj = self.projects.active_name
        all_a = self.supervisor.list_agents()
        active = [a for a in all_a if a["active"]]
        bg = [a for a in all_a if not a["active"]]
        tickets = list_tickets(proj)
        rules = self.orchestrator.list_rules(proj)

        status_table = Table(box=box.MINIMAL, show_header=False)
        status_table.add_row("[bold cyan]Non-Stop Node Workspace[/]", f"[bold green]{proj.upper()}[/]")
        status_table.add_row("Primary Core Memory Stream", f"{len(all_a)} active sub-agents")
        status_table.add_row("Background Node Slices", f"{len(bg)} sleeping agents")
        status_table.add_row("Pending Board Tickets", f"{len(tickets)}")
        status_table.add_row("Orchestration Node Rules", f"{len(rules)}")
        status_table.add_row("Active Cognitive Model", f"[bold green]{self._default_model}[/]")
        
        self.console.print(Panel(status_table, title=" CORE SYSTEM INTEGRITY STATUS "))
        return ""

    async def _cmd_clear(self, args: str) -> str:
        self.console.clear()
        return ""

    async def _cmd_quit(self, args: str) -> str:
        self.running = False
        return ""

    # ── Master Loops ──────────────────────────────────────────────────

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

                    # Compact display trigger
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
                    self.console.print(f"  [red]✗ Runtime Error: {e}[/]")

        self.console.print()
        self.console.print("[dim]Non-Stop system loop decoupled. Program terminated.[/]")
        await self.supervisor.shutdown_all()

    async def _handle_input(self, text: str):
        """Route user inputs gracefully, prioritizing PM routing patterns."""
        proj = self.projects.active
        if not proj.agents:
            self.console.print("  [dim]No agents connected. Summon one with /summon.[/]\n")
            return

        for name, agent in proj.agents.items():
            if not agent.is_busy:
                await agent.direct_message(text)
                return

        # Busy state exception
        first = list(proj.agents.values())[0]
        self.console.print("  [dim]Active nodes busy. Appending input to default agent buffer...[/]")
        await first.direct_message(text)
