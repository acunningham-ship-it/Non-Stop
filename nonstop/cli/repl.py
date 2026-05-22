"""Non-Stop REPL — minimal, Claude Code style terminal UI."""

from __future__ import annotations
import asyncio
import hashlib
import os
import re
from collections import defaultdict, deque
from importlib.metadata import version as _pkg_version, PackageNotFoundError
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.table import Table

from nonstop.cli.commands import CommandRegistry, Command
from nonstop.runtime.supervisor import Supervisor
from nonstop.projects.manager import ProjectManager
from nonstop.personalities import list_presets
from nonstop.board import create_ticket, move_ticket, list_tickets, add_comment
from nonstop.runtime.teams import list_teams
from nonstop.runtime.orchestrator import Orchestrator
from nonstop import updater


try:
    VERSION = _pkg_version("nonstop")
except PackageNotFoundError:
    VERSION = "0.0.0+dev"


STYLE = Style.from_dict({
    "prompt": "#888888",
    "bottom-toolbar": "noreverse #666666",
    "completion-menu": "bg:#1a1a1a #cccccc",
    "completion-menu.completion": "bg:#1a1a1a #cccccc",
    "completion-menu.completion.current": "bg:#ff8800 #000000 bold",
    "completion-menu.meta.completion": "bg:#1a1a1a #888888",
    "completion-menu.meta.completion.current": "bg:#ff8800 #000000",
    "scrollbar.background": "bg:#1a1a1a",
    "scrollbar.button": "bg:#444444",
})

# 256-color palette: readable on dark + light terminals, no near-black/white.
COLOR_PALETTE = [39, 45, 51, 75, 81, 117, 123, 159, 165, 171, 177, 207, 213, 219, 220, 226]


def _color_for(name: str) -> str:
    h = int(hashlib.md5(name.encode()).hexdigest(), 16)
    return f"color({COLOR_PALETTE[h % len(COLOR_PALETTE)]})"


class CommandCompleter(Completer):
    def __init__(self, commands: CommandRegistry):
        self.commands = commands

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        partial = text[1:].lower()
        for cmd in self.commands._commands.values():
            # Show one row per command (primary name only). Match against
            # aliases so /q still completes, but display the canonical name.
            matches_any = any(
                n.startswith(partial) for n in [cmd.name] + cmd.aliases
            )
            if matches_any:
                yield Completion(
                    f"/{cmd.name}",
                    start_position=-len(text),
                    display=f"/{cmd.name}",
                    display_meta=cmd.help_text,
                )


class NonStopREPL:
    def __init__(self, supervisor: Supervisor, projects: ProjectManager):
        self.supervisor = supervisor
        self.projects = projects
        self.console = Console(highlight=False, soft_wrap=True)
        self.running = True
        self._default_model = "openrouter/openai/gpt-4o-mini"

        self.orchestrator = Orchestrator(bus=supervisor.bus, supervisor=supervisor)
        supervisor.orchestrator = self.orchestrator

        # Streaming serialization: one agent at a time owns the output line.
        # If another agent emits tokens while one is active, buffer them.
        self._stream_owner: str | None = None
        self._stream_buffers: dict[str, list[str]] = defaultdict(list)
        self._stream_order: deque[str] = deque()

        # Update state — populated by the background check.
        self._update_available: dict | None = None

        self.commands = CommandRegistry()
        self._register_commands()

        kb = KeyBindings()

        @kb.add("escape", "enter")
        def _(event):
            event.current_buffer.insert_text("\n")

        self.session = PromptSession(
            history=FileHistory(os.path.expanduser("~/.nonstop_history")),
            style=STYLE,
            completer=CommandCompleter(self.commands),
            complete_while_typing=True,
            key_bindings=kb,
            bottom_toolbar=self._toolbar,
            refresh_interval=0.5,
        )

    def _register_commands(self):
        cmds = [
            Command("help", self._cmd_help, "Show commands", ["?"]),
            Command("summon", self._cmd_summon, "Spawn an agent: /summon <name> [as <desc>|<preset>]", ["s"]),
            Command("tell", self._cmd_tell, "Message an agent directly: /tell <name> <msg>", ["t"]),
            Command("team", self._cmd_team, "Spawn a team: /team <build|research|debate|review>", []),
            Command("board", self._cmd_board, "Kanban board: /board [add|move|comment]", ["b"]),
            Command("projects", self._cmd_projects, "Workspaces: /projects [new|switch]", ["p"]),
            Command("model", self._cmd_model, "Set default model: /model <name>", ["m"]),
            Command("models", self._cmd_models, "List models", []),
            Command("agents", self._cmd_agents, "List running agents", ["a"]),
            Command("kill", self._cmd_kill, "Dismiss agent: /kill <name>", ["k"]),
            Command("rules", self._cmd_rules, "Orchestration rules: /rules [add|remove]", ["r"]),
            Command("remember", self._cmd_remember, "Show agent memory: /remember <name>", []),
            Command("presets", self._cmd_presets, "List personality presets", []),
            Command("status", self._cmd_status, "System status", ["st"]),
            Command("update", self._cmd_update, "Check for + apply updates", ["up"]),
            Command("clear", self._cmd_clear, "Clear screen", ["c"]),
            Command("quit", self._cmd_quit, "Exit", ["q", "exit"]),
        ]
        for cmd in cmds:
            self.commands.register(cmd)

    # ── Streaming ────────────────────────────────────────────────────

    def _print_agent_header(self, name: str):
        color = _color_for(name)
        self.console.print()
        self.console.print(f"[{color}]⏺[/] [bold {color}]{name}[/]")
        self.console.print("[dim]  │[/] ", end="")

    def _flush_buffer(self, name: str):
        buf = self._stream_buffers.pop(name, [])
        if not buf:
            return
        self._print_agent_header(name)
        # Indent continuation lines so they line up under the │.
        text = "".join(buf).replace("\n", "\n[dim]  │[/] ")
        self.console.print(text, end="", highlight=False)

    def _on_stream_token(self, name: str, token: str, accumulated: str):
        # If nobody owns the line, this agent takes it.
        if self._stream_owner is None:
            self._stream_owner = name
            self._print_agent_header(name)
            text = token.replace("\n", "\n[dim]  │[/] ")
            self.console.print(text, end="", highlight=False)
            return

        # Same agent continues writing.
        if self._stream_owner == name:
            text = token.replace("\n", "\n[dim]  │[/] ")
            self.console.print(text, end="", highlight=False)
            return

        # Another agent's tokens — buffer until current owner finishes.
        if name not in self._stream_buffers:
            self._stream_order.append(name)
        self._stream_buffers[name].append(token)

    def _on_stream_end(self, name: str, full_response: str):
        if self._stream_owner == name:
            self.console.print()  # newline closes the agent line
            self._stream_owner = None
            # Promote the next buffered agent (if any).
            while self._stream_order:
                nxt = self._stream_order.popleft()
                if nxt in self._stream_buffers and self._stream_buffers[nxt]:
                    self._stream_owner = nxt
                    self._flush_buffer(nxt)
                    # The promoted agent may still be producing; if its stream
                    # already ended while buffered, close the line.
                    agent = self.supervisor.get_agent(nxt)
                    if agent is None or not agent.is_busy:
                        self.console.print()
                        self._stream_owner = None
                        continue
                    break
        else:
            # Owner was someone else — just dump this agent's buffer cleanly.
            self._flush_buffer(name)
            if self._stream_owner is None or self._stream_owner == name:
                self.console.print()
                self._stream_owner = None

    # ── UI chrome ────────────────────────────────────────────────────

    def _show_banner(self):
        proj = self.projects.active_name
        cwd = os.getcwd().replace(str(Path.home()), "~")
        lines = [
            Text.from_markup("[bold #ff8800]✻[/] [bold]Welcome to Non-Stop[/]  [dim]v" + VERSION + "[/]"),
            Text(""),
            Text.from_markup("  [dim]Just type to talk[/] · [dim]/help[/] for commands · [dim]/team[/] for multi-agent · [dim]Esc+Enter[/] newline"),
            Text(""),
            Text.from_markup(f"  [dim]project:[/] {proj}    [dim]cwd:[/] {cwd}"),
        ]
        if self._update_available:
            short = self._update_available.get("short", "")
            lines.append(Text(""))
            lines.append(Text.from_markup(f"  [#ff8800]↑ update available[/] [dim]({short}) — run /update[/]"))

        self.console.print()
        self.console.print(Panel(
            Group(*lines),
            border_style="#ff8800",
            box=box.ROUNDED,
            padding=(0, 1),
            expand=False,
        ))
        self.console.print()

    def _show_commands(self):
        groups = [
            ("Agents", ["summon", "tell", "team", "kill", "agents", "remember", "presets"]),
            ("Workspace", ["board", "projects", "model", "models", "rules", "status"]),
            ("System", ["help", "update", "clear", "quit"]),
        ]
        by_name = {c.name: c for c in self.commands._commands.values()}

        table = Table.grid(padding=(0, 2), expand=False)
        table.add_column(style="bold")
        table.add_column(style="dim")

        for i, (label, names) in enumerate(groups):
            if i:
                table.add_row("", "")
            table.add_row(Text(label.upper(), style="bold #ff8800"), "")
            for n in names:
                cmd = by_name.get(n)
                if not cmd:
                    continue
                table.add_row(f"/{cmd.name}", cmd.help_text)

        self.console.print()
        self.console.print(Panel(
            table,
            title="[bold] commands [/]",
            title_align="left",
            border_style="dim",
            box=box.ROUNDED,
            padding=(1, 2),
            expand=False,
        ))
        self.console.print()

    def _toolbar(self):
        proj = self.projects.active_name
        agents = self.supervisor.list_agents(project_name=proj)
        busy = sum(1 for a in agents if a["busy"])
        model_short = self._default_model.split("/")[-1]

        left_parts = [
            f"\x1b[1m{proj}\x1b[0m",
            f"{len(agents)} agent{'s' if len(agents) != 1 else ''}"
            + (f" \x1b[38;5;208m({busy} ✻ thinking)\x1b[0m" if busy else ""),
            f"\x1b[2m{model_short}\x1b[0m",
        ]
        if self._update_available:
            left_parts.append("\x1b[38;5;208m↑ /update\x1b[0m")
        left = "  ·  ".join(left_parts)

        right = "\x1b[2m? for help · ↵ send · esc+↵ newline\x1b[0m"

        try:
            width = self.console.width
        except Exception:
            width = 80
        # Strip ANSI for width calc.
        plain_left = re.sub(r"\x1b\[[0-9;]*m", "", left)
        plain_right = re.sub(r"\x1b\[[0-9;]*m", "", right)
        gap = max(2, width - len(plain_left) - len(plain_right) - 2)
        return ANSI(" " + left + (" " * gap) + right + " ")

    def _prompt(self):
        return ANSI("\x1b[38;5;208m❯\x1b[0m ")

    # ── Commands ─────────────────────────────────────────────────────

    async def _cmd_help(self, args: str) -> str:
        self._show_commands()
        return ""

    async def _cmd_summon(self, args: str) -> str:
        if not args.strip():
            presets = ", ".join(p["name"] for p in list_presets())
            return f"[dim]Usage:[/] /summon <name> [as <desc>|<preset>]\n[dim]Presets:[/] {presets}"

        parts = args.strip().split(maxsplit=2)
        name = parts[0]
        persona_ref = parts[1] if len(parts) > 1 else ""
        if len(parts) > 2 and parts[1] == "as":
            persona_ref = parts[2]

        result = await self.supervisor.spawn_agent(name, persona_ref, model=self._default_model)
        if isinstance(result, str):
            return f"[red]error:[/] {result}"

        result.set_stream_callbacks(on_token=self._on_stream_token, on_end=self._on_stream_end)
        return f"[dim]spawned[/] [{_color_for(name)}]{name}[/]"

    async def _cmd_tell(self, args: str) -> str:
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            return "[dim]Usage:[/] /tell <name> <message>"
        err = await self.supervisor.send_to_agent(parts[0], parts[1])
        if err:
            return f"[red]error:[/] {err}"
        return ""

    async def _cmd_team(self, args: str) -> str:
        name = args.strip().lower()
        if not name:
            teams = list_teams()
            lines = []
            for t in teams:
                lines.append(f"  [bold]{t['name']}[/]  [dim]{t['description']}[/]")
            return "\n".join(lines)

        results = await self.supervisor.spawn_team(name)
        agents = [r for r in results if not isinstance(r, str)]
        errors = [r for r in results if isinstance(r, str)]

        for a in agents:
            a.set_stream_callbacks(on_token=self._on_stream_token, on_end=self._on_stream_end)

        lines = []
        if agents:
            names = ", ".join(f"[{_color_for(a.name)}]{a.name}[/]" for a in agents)
            lines.append(f"[dim]spawned team[/] [bold]{name}[/]: {names}")
        for e in errors:
            lines.append(f"[red]error:[/] {e}")
        return "\n".join(lines) if lines else f"unknown team '{name}'"

    async def _cmd_board(self, args: str) -> str:
        parts = args.split(maxsplit=2)
        if not args:
            proj = self.projects.active_name
            for c in ["backlog", "in_progress", "review", "done"]:
                tickets = list_tickets(proj, c)
                self.console.print(f"[bold]{c}[/] [dim]({len(tickets)})[/]")
                if not tickets:
                    self.console.print("  [dim]—[/]")
                for t in tickets:
                    assigned = f" [dim]@{t.assigned_to}[/]" if t.assigned_to else ""
                    self.console.print(f"  [cyan]#{t.id}[/] {escape(t.title)}{assigned}")
                self.console.print()
            return ""

        if parts[0] == "add" and len(parts) >= 2:
            tid = create_ticket(parts[1], project=self.projects.active_name)
            return f"[dim]added[/] [cyan]#{tid}[/]"

        if parts[0] == "move" and len(parts) >= 3:
            try:
                tid = int(parts[1].lstrip("#"))
            except ValueError:
                return "[dim]Usage:[/] /board move <#id> <column>"
            err = move_ticket(tid, parts[2])
            return f"[dim]moved[/] [cyan]#{tid}[/] → {parts[2]}" if not err else f"[red]error:[/] {err}"

        if parts[0] == "comment" and len(parts) >= 3:
            try:
                tid = int(parts[1].lstrip("#"))
            except ValueError:
                return "[dim]Usage:[/] /board comment <#id> <text>"
            add_comment(tid, "user", parts[2])
            return f"[dim]commented on[/] [cyan]#{tid}[/]"

        return "[dim]Usage:[/] /board [add <title> | move <#id> <col> | comment <#id> <text>]"

    async def _cmd_projects(self, args: str) -> str:
        parts = args.split(maxsplit=1)
        if not args:
            for p in self.projects.list():
                marker = "[green]●[/]" if p["active"] else "[dim]○[/]"
                agents = ", ".join(p["agents"]) if p["agents"] else "[dim]—[/]"
                self.console.print(f"  {marker} [bold]{p['name']}[/]  [dim]{agents}[/]")
            return ""

        if parts[0] == "new" and len(parts) > 1:
            err = await self.projects.create(parts[1])
            return f"[dim]created[/] [bold]{parts[1]}[/]" if not err else f"[red]error:[/] {err}"

        err = await self.projects.switch(parts[0])
        return f"[dim]switched to[/] [bold]{parts[0]}[/]" if not err else f"[red]error:[/] {err}"

    async def _cmd_model(self, args: str) -> str:
        model = args.strip()
        if not model:
            return f"[dim]model:[/] {self._default_model}"
        self._default_model = model
        return f"[dim]model →[/] {model}"

    async def _cmd_models(self, args: str) -> str:
        models = [
            ("openrouter/google/gemini-2.5-flash", "Gemini 2.5 Flash"),
            ("openrouter/google/gemini-2.5-pro", "Gemini 2.5 Pro"),
            ("openrouter/openai/gpt-4o", "GPT-4o"),
            ("openrouter/openai/gpt-4o-mini", "GPT-4o Mini"),
            ("openrouter/anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet"),
            ("openrouter/deepseek/deepseek-v3", "DeepSeek V3"),
        ]
        for m, d in models:
            marker = "[green]●[/]" if m == self._default_model else "[dim]○[/]"
            self.console.print(f"  {marker} [bold]{d}[/]  [dim]{m}[/]")
        return ""

    async def _cmd_agents(self, args: str) -> str:
        agents = self.supervisor.list_agents()
        if not agents:
            return "[dim]no agents — try /summon[/]"
        for a in agents:
            color = _color_for(a["name"])
            state = "[yellow]thinking[/]" if a["busy"] else "[dim]idle[/]"
            self.console.print(f"  [{color}]{a['name']}[/]  {state}  [dim]{a['project']}[/]")
        return ""

    async def _cmd_kill(self, args: str) -> str:
        name = args.strip()
        if not name:
            return "[dim]Usage:[/] /kill <name>"
        err = await self.supervisor.kill_agent(name)
        return f"[dim]killed[/] {name}" if not err else f"[red]error:[/] {err}"

    async def _cmd_rules(self, args: str) -> str:
        parts = args.split(maxsplit=2)
        if not args:
            rules = self.orchestrator.list_rules(self.projects.active_name)
            if not rules:
                return "[dim]no rules — add with /rules add <trigger> <action>[/]"
            for r in rules:
                self.console.print(f"  [cyan]#{r['id']}[/] [dim]when[/] {escape(r['trigger'])} [dim]→[/] {escape(r['action'])}")
            return ""

        if parts[0] == "add" and len(parts) >= 3:
            self.orchestrator.add_rule(parts[1], parts[2], project=self.projects.active_name)
            return f"[dim]rule added:[/] when {parts[1]} → {parts[2]}"

        if parts[0] == "remove" and len(parts) >= 2:
            try:
                self.orchestrator.remove_rule(int(parts[1]))
                return f"[dim]removed rule[/] #{parts[1]}"
            except ValueError:
                return "[dim]Usage:[/] /rules remove <id>"

        return "[dim]Usage:[/] /rules [add <trigger> <action> | remove <id>]"

    async def _cmd_remember(self, args: str) -> str:
        name = args.strip()
        if not name:
            return "[dim]Usage:[/] /remember <name>"
        agent = self.supervisor.get_agent(name)
        if not agent:
            return f"[red]error:[/] no agent '{name}'"

        facts = agent.memory.recall_all()
        traits = agent.memory.get_profile()

        if not facts and not traits:
            return f"[dim]{name} has no stored memory yet[/]"

        for k, v in facts.items():
            self.console.print(f"  [dim]{k}:[/] {escape(str(v))}")
        for t in traits:
            self.console.print(f"  [dim]trait:[/] {escape(t['trait'])}")
        return ""

    async def _cmd_presets(self, args: str) -> str:
        for p in list_presets():
            self.console.print(f"  [bold]{p['name']}[/]  [dim]{p['description']}[/]")
        return ""

    async def _cmd_status(self, args: str) -> str:
        proj = self.projects.active_name
        all_a = self.supervisor.list_agents()
        bg = [a for a in all_a if not a["active"]]
        tickets = list_tickets(proj)
        rules = self.orchestrator.list_rules(proj)

        self.console.print(f"  [dim]project[/]  {proj}")
        self.console.print(f"  [dim]agents[/]   {len(all_a)} ({len(bg)} background)")
        self.console.print(f"  [dim]tickets[/]  {len(tickets)}")
        self.console.print(f"  [dim]rules[/]    {len(rules)}")
        self.console.print(f"  [dim]model[/]    {self._default_model}")
        return ""

    async def _cmd_update(self, args: str) -> str:
        self.console.print("[dim]checking for updates…[/]")
        pending = await updater.check_for_update()
        if pending is None:
            self._update_available = None
            return "[dim]already up to date[/]"

        self.console.print(f"[yellow]update available:[/] {pending['short']} — {escape(pending['subject'])}")
        self.console.print("[dim]applying…[/]")
        ok, msg = await asyncio.to_thread(updater.apply_update)
        if ok:
            self._update_available = None
            return f"[green]✓[/] {msg}"
        return f"[red]update failed:[/] {escape(msg)}"

    async def _cmd_clear(self, args: str) -> str:
        self.console.clear()
        return ""

    async def _cmd_quit(self, args: str) -> str:
        self.running = False
        return ""

    # ── Background tasks ─────────────────────────────────────────────

    async def _check_updates_background(self):
        try:
            pending = await updater.check_for_update()
            if pending:
                self._update_available = pending
                self.console.print(
                    f"\n [yellow]↑ update available[/] [dim]({pending['short']}) — run /update[/]\n"
                )
        except Exception:
            pass  # network/parsing failures are silent

    # ── Loop ─────────────────────────────────────────────────────────

    DEFAULT_AGENT_NAME = "nova"

    async def _ensure_default_agent(self):
        """If the active project has no agents, spawn one so typing Just Works."""
        proj = self.projects.active
        if proj.agents:
            return
        result = await self.supervisor.spawn_agent(
            self.DEFAULT_AGENT_NAME,
            persona_ref="",
            model=self._default_model,
        )
        if not isinstance(result, str):
            result.set_stream_callbacks(
                on_token=self._on_stream_token,
                on_end=self._on_stream_end,
            )

    async def run(self):
        # Kick off the update check before drawing the banner so we know
        # whether to include the "update available" line — but don't block.
        update_task = asyncio.create_task(self._check_updates_background())

        await self._ensure_default_agent()
        self._show_banner()

        with patch_stdout():
            while self.running:
                try:
                    text = await self.session.prompt_async(self._prompt())

                    if not text.strip():
                        continue

                    if text.strip() == "/":
                        self._show_commands()
                        continue

                    if text.startswith("/"):
                        response = await self.commands.route(text)
                        if response:
                            self.console.print(response)
                        continue

                    await self._handle_input(text)

                except KeyboardInterrupt:
                    continue
                except EOFError:
                    break
                except Exception as e:
                    self.console.print(f"[red]error:[/] {escape(str(e))}")

        update_task.cancel()
        self.console.print("[dim]bye[/]")
        await self.supervisor.shutdown_all()

    async def _handle_input(self, text: str):
        proj = self.projects.active
        if not proj.agents:
            # Shouldn't happen — default agent is spawned at startup — but
            # if every agent was killed, re-spawn the default rather than
            # leaving the user stuck.
            await self._ensure_default_agent()

        for agent in proj.agents.values():
            if not agent.is_busy:
                await agent.direct_message(text)
                return

        first = next(iter(proj.agents.values()))
        await first.direct_message(text)
