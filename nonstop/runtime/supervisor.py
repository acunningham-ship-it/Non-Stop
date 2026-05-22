from __future__ import annotations
import asyncio

from nonstop.bus import get_bus, Message
from nonstop.personalities import Personality, resolve_personality
from nonstop.runtime.agent import Agent
from nonstop.runtime.memory import AgentMemory
from nonstop.runtime.teams import TEAM_TEMPLATES, get_team
from nonstop.projects.manager import ProjectManager


class Supervisor:
    """Manages all agents across all projects."""

    def __init__(self, projects: ProjectManager):
        self.projects = projects
        self.bus = get_bus()
        self.orchestrator = None  # set externally after init

    # ── Agent lifecycle ──────────────────────────────────────────────

    async def spawn_agent(
        self,
        name: str,
        persona_ref: str = "",
        project_name: str | None = None,
        model: str = "",
    ) -> Agent | str:
        proj_name = project_name or self.projects.active_name
        proj = self.projects.projects.get(proj_name)
        if not proj:
            return f"No such project: {proj_name}"
        if name in proj.agents:
            return f"Agent '{name}' already exists in project '{proj_name}'"

        personality = resolve_personality(name, persona_ref)
        if model:
            personality.model = model
        mem = AgentMemory(name, proj_name)

        agent = Agent(
            name=name,
            personality=personality,
            bus=self.bus,
            project_name=proj_name,
            memory=mem,
        )
        agent.start()
        proj.agents[name] = agent

        await self.bus.publish(Message(
            topic="system.agent.spawned",
            sender="system",
            content=f"Agent '{name}' spawned in project '{proj_name}'",
            metadata={"agent": name, "project": proj_name},
        ))

        return agent

    async def spawn_team(self, team_name: str, project_name: str | None = None
                         ) -> list[Agent | str]:
        """Spawn a coordinated team of agents. Returns list of Agents or errors."""
        team = get_team(team_name)
        if not team:
            return [f"No team template '{team_name}'. Options: {', '.join(TEAM_TEMPLATES.keys())}"]

        proj_name = project_name or self.projects.active_name
        proj = self.projects.projects.get(proj_name)
        if not proj:
            return [f"No such project: {proj_name}"]

        base_name = f"team-{team_name}"
        results = []
        spawned = []

        for i, agent_def in enumerate(team["agents"]):
            agent_name = f"{base_name}-{agent_def['name_suffix']}" if len(team["agents"]) > 1 else base_name
            if agent_name in proj.agents:
                results.append(f"Agent '{agent_name}' already exists")
                continue

            personality = resolve_personality(agent_name, agent_def["description"])
            mem = AgentMemory(agent_name, proj_name)
            agent = Agent(
                name=agent_name,
                personality=personality,
                bus=self.bus,
                project_name=proj_name,
                memory=mem,
            )
            agent.start()
            proj.agents[agent_name] = agent
            spawned.append(agent)

            # Notify
            await self.bus.publish(Message(
                topic="system.agent.spawned",
                sender="system",
                content=f"Agent '{agent_name}' spawned as part of team '{team_name}'",
            ))

        # If multiple agents, inject team coordination prompt
        if len(spawned) > 1:
            agent_names = {
                a["name_suffix"]: f"{base_name}-{a['name_suffix']}"
                for a in team["agents"]
            }
            team_prompt = team["team_prompt"].format(**agent_names)

            await self.bus.publish(Message(
                topic="system.team.formed",
                sender="system",
                content=f"Team '{team_name}' formed: {', '.join(a.name for a in spawned)}",
            ))

            # Send team prompt to first agent to start the workflow
            if spawned:
                await spawned[0].direct_message(
                    f"[team setup] You are now part of team '{team_name}'.\n{team_prompt}"
                )

        results.extend(spawned)
        return results

    async def kill_agent(self, name: str, project_name: str | None = None) -> str | None:
        proj_name = project_name or self.projects.active_name
        proj = self.projects.projects.get(proj_name)
        if not proj:
            return f"No such project: {proj_name}"
        agent = proj.agents.pop(name, None)
        if not agent:
            return f"No agent '{name}' in project '{proj_name}'"
        await agent.stop()
        await self.bus.publish(Message(topic="system.agent.killed", sender="system",
                                       content=f"Agent '{name}' stopped"))
        return None

    def list_agents(self, project_name: str | None = None) -> list[dict]:
        agents = []
        for pname, proj in self.projects.projects.items():
            if project_name and pname != project_name:
                continue
            for aname, agent in proj.agents.items():
                traits = agent.memory.get_profile()
                agents.append({
                    "name": agent.name,
                    "personality": agent.personality.system_prompt[:60] + "...",
                    "busy": agent.is_busy,
                    "project": pname,
                    "active": pname == self.projects.active_name,
                    "traits": [t["trait"] for t in traits[:3]],
                })
        return agents

    def get_agent(self, name: str) -> Agent | None:
        return self.projects.get_agent(name)

    async def send_to_agent(self, agent_name: str, content: str) -> str | None:
        agent = self.projects.get_agent(agent_name)
        if not agent:
            return f"No agent '{agent_name}' found"
        await agent.direct_message(content)
        return None

    async def shutdown_all(self):
        for proj in self.projects.projects.values():
            for name, agent in list(proj.agents.items()):
                await agent.stop()
        await self.bus.shutdown()