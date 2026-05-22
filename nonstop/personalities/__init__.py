from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Personality:
    """An agent's starting configuration. Minimal by design — the agent's real 
    personality is shaped through conversation over time."""
    name: str
    system_prompt: str = ""
    model: str = "openrouter/openai/gpt-4o-mini"
    temperature: float = 0.7


def blank_slate(name: str, description: str = "") -> Personality:
    """Create a minimal starting personality. The user and AI define it over time."""
    if description:
        prompt = (
            f"You are an AI agent named {name}. "
            f"{description}\n\n"
            f"You can use @agent_name: instructions to delegate tasks to other agents. "
            f"Stay in character and adapt as you learn what the user needs."
        )
    else:
        prompt = (
            f"You are an AI agent named {name}. "
            f"Your personality, expertise, and role will be shaped through conversation. "
            f"The user will tell you who to be.\n\n"
            f"You can use @agent_name: instructions to delegate tasks to other agents."
        )
    return Personality(name=name, system_prompt=prompt)


# Keep these around as shorthand presets, not as the primary mechanism
BUILTIN_PERSONALITIES: dict[str, str] = {
    "architect": "You are a system architect. Design clean, scalable solutions with documented trade-offs.",
    "skeptic":  "You are a ruthless skeptic. Tear apart weak ideas. Demand rigor, planning, and edge cases before approving anything.",
    "coder":    "You write clean, working code with tests and documentation. Implement from specs.",
    "critic":   "You review code for correctness, security, performance, and maintainability. Be constructive.",
    "pm":       "You coordinate tasks, break down goals, assign work to other agents, and track progress.",
    "researcher": "You research topics thoroughly and synthesize findings. Note uncertainties.",
}


def resolve_personality(name: str, persona_ref: str = "") -> Personality:
    """Resolve a personality reference into a Personality object.
    
    If persona_ref matches a builtin preset, use that description.
    Otherwise treat it as a free-form description of how the agent should be.
    """
    if not persona_ref:
        return blank_slate(name)
    
    preset = BUILTIN_PERSONALITIES.get(persona_ref.lower().strip())
    if preset:
        return blank_slate(name, preset)
    
    return blank_slate(name, persona_ref)


def list_presets() -> list[dict]:
    return [
        {"name": k, "description": v.split(".")[0] + "."}
        for k, v in BUILTIN_PERSONALITIES.items()
    ]