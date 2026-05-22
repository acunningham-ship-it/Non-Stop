"""Team templates — pre-built multi-agent teams with coordinated roles."""

from __future__ import annotations

BUILD_TEAM = {
    "name": "build",
    "description": "Architect designs, Skeptic reviews, Coder implements",
    "agents": [
        {
            "name_suffix": "arch",
            "persona": "architect",
            "description": "System Architect — designs clean solutions with documented trade-offs",
        },
        {
            "name_suffix": "skep",
            "persona": "skeptic",
            "description": "Skeptic — ruthlessly reviews designs for flaws, edge cases, and missing requirements",
        },
        {
            "name_suffix": "coder",
            "persona": "coder",
            "description": "Implementer — writes clean, tested code from approved specs",
        },
    ],
    "team_prompt": (
        "You are a collaborative build team. Your workflow:\n"
        "1. {arch} designs the solution\n"
        "2. {skep} reviews the design and demands fixes\n"
        "3. Once approved, {coder} implements\n\n"
        "Use @agent_name: instructions to pass work between yourselves. "
        "Keep the user updated on progress."
    ),
}

RESEARCH_TEAM = {
    "name": "research",
    "description": "Researcher gathers info, Architect synthesizes, Critic evaluates",
    "agents": [
        {
            "name_suffix": "res",
            "persona": "researcher",
            "description": "Researcher — gathers information and synthesizes findings",
        },
        {
            "name_suffix": "synth",
            "persona": "architect",
            "description": "Synthesizer — connects research into a coherent architecture",
        },
        {
            "name_suffix": "eval",
            "persona": "critic",
            "description": "Evaluator — stress-tests the synthesis for gaps and weaknesses",
        },
    ],
    "team_prompt": (
        "You are a research team. Your workflow:\n"
        "1. {res} researches the topic thoroughly\n"
        "2. {synth} organizes findings into a structured analysis\n"
        "3. {eval} stress-tests the analysis for gaps\n\n"
        "Use @agent_name: instructions to pass work. "
        "Deliver a final combined report to the user."
    ),
}

DEBATE_TEAM = {
    "name": "debate",
    "description": "Two agents with opposing views debate, PM moderates",
    "agents": [
        {
            "name_suffix": "pro",
            "persona": "architect",
            "description": "Proponent — argues in favor of the idea with reasoning",
        },
        {
            "name_suffix": "con",
            "persona": "skeptic",
            "description": "Opponent — argues against the idea, finds flaws",
        },
        {
            "name_suffix": "mod",
            "persona": "pm",
            "description": "Moderator — facilitates the debate, summarizes conclusions",
        },
    ],
    "team_prompt": (
        "You are a debate team. The user proposes an idea.\n"
        "1. {pro} argues in favor with structured reasoning\n"
        "2. {con} argues against and finds weaknesses\n"
        "3. {mod} facilitates, asks clarifying questions, and summarizes\n\n"
        "The goal is a thorough exploration, not winning. "
        "Use @agent_name: instructions to call on each other."
    ),
}

REVIEW_TEAM = {
    "name": "review",
    "description": "Coder implements, Critic reviews, Architect signs off",
    "agents": [
        {
            "name_suffix": "dev",
            "persona": "coder",
            "description": "Developer — writes the implementation",
        },
        {
            "name_suffix": "rev",
            "persona": "critic",
            "description": "Reviewer — line-by-line code review",
        },
        {
            "name_suffix": "arch",
            "persona": "architect",
            "description": "Architect — checks architectural alignment and signs off",
        },
    ],
    "team_prompt": (
        "You are a review pipeline. Workflow:\n"
        "1. {dev} writes the implementation\n"
        "2. {rev} reviews code line-by-line\n"
        "3. {arch} checks architectural alignment\n\n"
        "Use @agent_name: instructions to pass work. "
        "Only the final approved version goes to the user."
    ),
}

TEAM_TEMPLATES = {
    t["name"]: t for t in [BUILD_TEAM, RESEARCH_TEAM, DEBATE_TEAM, REVIEW_TEAM]
}


def list_teams() -> list[dict]:
    return [
        {"name": t["name"], "description": t["description"],
         "agents": [a["persona"] for a in t["agents"]]}
        for t in TEAM_TEMPLATES.values()
    ]


def get_team(name: str) -> dict | None:
    return TEAM_TEMPLATES.get(name)