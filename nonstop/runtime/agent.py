from __future__ import annotations
import asyncio
import re
import time
from datetime import datetime, timezone

from nonstop.bus import Message, get_bus
from nonstop.personalities import Personality
from nonstop.providers.openrouter import OpenRouterProvider
from nonstop.runtime.memory import AgentMemory


class Agent:
    """An agent is an async worker with conversation context and a bus connection.
    
    Personality is a blank slate — shaped through conversation over time.
    Uses streaming responses so the UI can show tokens in real-time.
    """

    def __init__(
        self,
        name: str,
        personality: Personality,
        bus=None,
        project_name: str = "default",
        provider: OpenRouterProvider | None = None,
        memory: AgentMemory | None = None,
    ):
        self.name = name
        self.personality = personality
        self.project = project_name
        self.bus = bus or get_bus()
        self.provider = provider or OpenRouterProvider()
        self.memory = memory or AgentMemory(name, project_name)

        # Build system prompt with memory + proactive instructions
        system_prompt = self._build_system_prompt()

        # Conversation context
        self.messages: list[dict] = [
            {"role": "system", "content": system_prompt}
        ]

        # Internal state
        self._mailbox = self.bus.agent_mailbox(name)
        self._subscriptions: list[tuple[str, asyncio.Queue]] = []
        self._task: asyncio.Task | None = None
        self._running = True
        self._thinking = False
        self._on_stream_token = None
        self._on_stream_end = None
        self._message_count = 0
        self.log: list[dict] = []

    # ── System prompt with memory + proactive instructions ───────────

    def _build_system_prompt(self) -> str:
        """Build the full system prompt including memory recall and proactive behavior."""
        base = self.personality.system_prompt

        # Load memory
        mem = self.memory.memory_summary()
        traits = self.memory.get_profile()

        parts = [base, ""]

        if traits:
            learned = ", ".join(f"{t['trait']}" for t in traits[:3])
            parts.append(f"Your learned traits: {learned}")

        if mem:
            parts.append(f"\nWhat you remember:\n{mem}")

        parts.append(
            "\n── Agent capabilities ──\n"
            "1. DELEGATION: Use @agent_name: instructions to pass tasks to other agents.\n"
            "2. MEMORY: I save important facts automatically. To save something explicitly:\n"
            '   Say "remember that X is Y" in your response.\n'
            "3. KANBAN: You can reference tickets by #id. Create tickets when tasks span multiple steps.\n"
            "4. PROACTIVE BROADCAST: If you've been idle or have an important update,\n"
            "   broadcast it so other agents and the user can see: @broadcast: your message here.\n"
            "5. ORCHESTRATION: You can request rules with: \"when X happens, tell Y to do Z\"."
        )

        return "\n".join(parts)

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for topic, q in self._subscriptions:
            self.bus.unsubscribe(topic, q)
        await self.provider.close()

    @property
    def is_busy(self) -> bool:
        return self._thinking

    # ── Callbacks for streaming UI ───────────────────────────────────

    def set_stream_callbacks(self, on_token=None, on_end=None):
        """Set callbacks for streaming responses.
        
        on_token(name, token, accumulated) — called on each new token
        on_end(name, full_response)        — called when stream completes
        """
        self._on_stream_token = on_token
        self._on_stream_end = on_end

    # ── Core loop ────────────────────────────────────────────────────

    async def _run(self):
        poll_queues = [self._mailbox] + [q for _, q in self._subscriptions]

        while self._running:
            try:
                done, pending = await asyncio.wait(
                    [asyncio.create_task(q.get()) for q in poll_queues],
                    timeout=1.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    msg = task.result()
                    await self._handle_message(msg)
                for task in pending:
                    task.cancel()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log("error", str(e))

    async def _handle_message(self, msg: Message):
        """Process an incoming message with streaming response."""
        self._log("received", f"[{msg.sender}] {msg.content[:100]}")
        self._thinking = True
        self._message_count += 1

        # Feed into context
        self.messages.append({
            "role": "user",
            "content": f"[From {msg.sender}]: {msg.content}",
        })

        try:
            # Stream the response
            accumulated = ""
            stream = await self.provider.chat(
                messages=self.messages,
                model=self.personality.model,
                temperature=self.personality.temperature,
                stream=True,
            )
            async for token in stream:
                accumulated += token
                if self._on_stream_token:
                    self._on_stream_token(self.name, token, accumulated)

            # Response complete
            self.messages.append({"role": "assistant", "content": accumulated})
            self._log("response", accumulated[:200])

            # Notify end of stream
            if self._on_stream_end:
                self._on_stream_end(self.name, accumulated)

            # Extract memory from response
            self._extract_memory(accumulated)
            # Extract traits from user message
            self._extract_traits(msg.content)
            # Handle proactive broadcasts
            await self._handle_broadcasts(accumulated)
            # Handle orchestration rules
            await self._handle_orchestration_rules(accumulated)

            # Check for delegation to other agents
            await self._check_for_delegation(accumulated, msg)

            # Publish result to bus
            await self.bus.publish(Message(
                topic=f"agent.{self.name}.result",
                sender=self.name,
                content=accumulated,
                target=msg.sender,
            ))
            await self.bus.publish(Message(
                topic="broadcast.result",
                sender=self.name,
                content=accumulated[:500],
            ))

        except Exception as e:
            self._log("error", f"LLM call failed: {e}")
            await self.bus.publish(Message(
                topic=f"agent.{self.name}.error",
                sender=self.name,
                content=str(e),
                target=msg.sender,
            ))
        finally:
            self._thinking = False

    # ── Memory extraction ────────────────────────────────────────────

    def _extract_memory(self, text: str):
        for match in re.finditer(
            r"remember\s+that\s+(.+?)\s+is\s+(.+?)(?:\.|$|\n)",
            text, re.IGNORECASE
        ):
            key = match.group(1).strip().lower().replace(" ", "_")
            value = match.group(2).strip()
            self.memory.remember(key, value)

    def _extract_traits(self, text: str):
        for match in re.finditer(
            r"you\s+(?:are|should\s+be)\s+(?:a|an)?\s*(.+?)(?:\.|$|\n|,|\s+who)",
            text.lower(), re.IGNORECASE
        ):
            trait = match.group(1).strip()
            if trait and len(trait) < 50:
                self.memory.learn_trait(trait[:30], confidence=0.7)

    async def _handle_broadcasts(self, text: str):
        for match in re.finditer(r"@broadcast:\s*(.+?)(?=\n@|\n*$)", text, re.DOTALL):
            msg_text = match.group(1).strip()
            await self.bus.publish(Message(
                topic="broadcast.agent",
                sender=self.name,
                content=f"[broadcast from {self.name}]: {msg_text}",
                metadata={"project": self.project},
            ))

    async def _handle_orchestration_rules(self, text: str):
        from runtime.orchestrator import parse_natural_rule
        import sqlite3
        result = parse_natural_rule(text)
        if result:
            import os
            trigger, action = result
            db_path = os.path.expanduser("~/.nonstop_rules.db")
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT INTO rules (project, trigger, action, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                (self.project, trigger, action, self.name, time.time()),
            )
            conn.commit()
            conn.close()

    async def _check_for_delegation(self, response: str, original_msg: Message):
        """Parse @agent_name: instructions for inter-agent delegation."""
        for match in re.finditer(
            r"@(\w[\w-]*):\s*(.+?)(?=\n@|\n*$)", response, re.DOTALL
        ):
            target_name = match.group(1)
            instructions = match.group(2).strip()
            if target_name != self.name:
                await self.bus.publish(Message(
                    topic=f"agent.{target_name}.task",
                    sender=self.name,
                    content=instructions,
                    metadata={"delegated_by": self.name, "project": self.project},
                    target=target_name,
                ))

    # ── Direct input ─────────────────────────────────────────────────

    async def direct_message(self, content: str):
        """Send a direct message (from user or another agent)."""
        await self.bus.publish(Message(
            topic=f"agent.{self.name}.direct",
            sender="user",
            content=content,
            target=self.name,
        ))

    # ── Utilities ────────────────────────────────────────────────────

    def _log(self, msg_type: str, content: str):
        self.log.append({
            "type": msg_type,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })