# Message bus for inter-agent communication
# Pub/sub pattern with asyncio.Queue per subscriber

from __future__ import annotations
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Coroutine, Any

TOPIC_PATTERNS = {
    "agent": "agent.{name}.{type}",       # agent.skeptic.review, agent.coder.result
    "system": "system.{event}",            # system.project.switch, system.shutdown
    "broadcast": "broadcast.{type}",       # broadcast.message, broadcast.status
}


@dataclass
class Message:
    topic: str
    sender: str
    content: str
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    target: str | None = None  # specific agent to route to


class MessageBus:
    """Async pub/sub message bus. Agents subscribe to topics and get messages via queues."""

    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._agent_queues: dict[str, asyncio.Queue] = {}  # direct agent mailboxes
        self._running = True

    def subscribe(self, topic: str) -> asyncio.Queue:
        """Subscribe to a topic pattern. Returns a queue the subscriber reads from.
        Supports wildcards: 'agent.skeptic.*' matches 'agent.skeptic.review'
        """
        q: asyncio.Queue = asyncio.Queue()
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(q)
        return q

    def unsubscribe(self, topic: str, q: asyncio.Queue):
        if topic in self._subscribers:
            self._subscribers[topic] = [s for s in self._subscribers[topic] if s is not q]

    def agent_mailbox(self, agent_name: str) -> asyncio.Queue:
        """Direct mailbox for an agent (addressed by target field)."""
        if agent_name not in self._agent_queues:
            self._agent_queues[agent_name] = asyncio.Queue()
        return self._agent_queues[agent_name]

    async def publish(self, msg: Message):
        if not self._running:
            return

        # Direct delivery to named agent
        if msg.target and msg.target in self._agent_queues:
            await self._agent_queues[msg.target].put(msg)
            return

        # Topic-based delivery with wildcard matching
        delivered = set()
        for pattern, queues in self._subscribers.items():
            if self._topic_matches(pattern, msg.topic):
                for q in queues:
                    q_id = id(q)
                    if q_id not in delivered:
                        await q.put(msg)
                        delivered.add(q_id)

    def _topic_matches(self, pattern: str, topic: str) -> bool:
        """Check if topic matches a pattern (supports * wildcard at end)."""
        if pattern.endswith(".*"):
            return topic.startswith(pattern[:-1])
        return pattern == topic

    async def shutdown(self):
        self._running = False


# Singleton
_bus: MessageBus | None = None


def get_bus() -> MessageBus:
    global _bus
    if _bus is None:
        _bus = MessageBus()
    return _bus