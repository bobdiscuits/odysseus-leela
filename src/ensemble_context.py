"""Deterministic context compilation and turn planning for model ensembles.

This module is deliberately provider-agnostic: it prepares data, but never calls a
model or any external service.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence


DEFAULT_SECTION_BUDGETS: dict[str, int] = {
    "brief": 4_000,
    "decisions": 3_000,
    "recent_turns": 6_000,
    "leela_excerpts": 5_000,
    "artifacts": 3_000,
    "addressed_chair": 500,
}

ROLE_PROMPTS = {
    "router": (
        "You are a tiny routing model. Decide whether a request can stay local or needs "
        "one cloud specialist. Reply with exactly LOCAL, CLAUDE, or GPT. Use CLAUDE for "
        "high-stakes judgment or final editorial review; GPT for implementation requiring "
        "Codex; otherwise LOCAL."
    ),
    "gemma": (
        "You are the fast local context worker. Extract requirements, retrieve the salient "
        "facts supplied in the packet, remove repetition, and produce a compact work brief. "
        "Do not invent missing context."
    ),
    "qwen": (
        "You are the local workhorse. Perform the substantive planning, drafting, analysis, "
        "or coding requested by Shaun. Use prior local output as evidence, be concrete, and "
        "return work that a cloud chair can review without reading the full transcript."
    ),
    "claude": (
        "You are the continuity and judgment member of the council. Preserve "
        "intent and prior decisions, identify ambiguity and risk, and make a "
        "clear recommendation. Do not invent missing context."
    ),
    "gpt": (
        "You are the GPT/Codex construction and implementation member of the "
        "council. Turn the supplied context into concrete, correct, testable "
        "work; state implementation details and verify constraints."
    ),
    "chair": (
        "You are the council chair. Reconcile the member responses into one "
        "decision, respecting the brief and recorded decisions."
    ),
}

POLICIES = frozenset(
    {"solo_claude", "solo_gpt", "ask_both", "claude_to_gpt", "gpt_to_claude", "council_one_round"}
)


@dataclass(frozen=True)
class CompiledSessionPacket:
    """Compilation result. ``packet`` is suitable for JSON persistence."""

    packet: dict[str, Any]
    rendered_prompt: str

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


def _stable_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return "\n".join(_stable_text(item) for item in value if item is not None).strip()
    return str(value).strip()


def _clip(text: str, budget: int) -> tuple[str, bool]:
    if budget < 0:
        raise ValueError("section budgets must be non-negative")
    if len(text) <= budget:
        return text, False
    marker = "…[truncated]"
    if budget <= len(marker):
        return marker[:budget], True
    return text[: budget - len(marker)].rstrip() + marker, True


def compile_session_packet(
    brief: Any,
    decisions: Any = (),
    recent_turns: Any = (),
    leela_excerpts: Any = (),
    artifacts: Any = (),
    addressed_chair: Any = "",
    *,
    section_budgets: Mapping[str, int] | None = None,
) -> CompiledSessionPacket:
    """Compile a stable, character-bounded session packet and prompt.

    Values may be strings, sequences, or JSON-like mappings. Mapping keys are
    sorted so identical semantic inputs always render identically.
    """

    budgets = dict(DEFAULT_SECTION_BUDGETS)
    if section_budgets:
        unknown = set(section_budgets) - set(budgets)
        if unknown:
            raise ValueError(f"unknown section budgets: {sorted(unknown)}")
        budgets.update(section_budgets)

    raw = {
        "brief": brief,
        "decisions": decisions,
        "recent_turns": recent_turns,
        "leela_excerpts": leela_excerpts,
        "artifacts": artifacts,
        "addressed_chair": addressed_chair,
    }
    sections: dict[str, str] = {}
    truncation: dict[str, bool] = {}
    for name in DEFAULT_SECTION_BUDGETS:  # fixed order is part of the format
        sections[name], truncation[name] = _clip(_stable_text(raw[name]), int(budgets[name]))

    packet: dict[str, Any] = {
        "format": "odysseus.ensemble.session-packet.v1",
        "sections": sections,
        "section_budgets": budgets,
        "truncated": truncation,
    }
    headings = {
        "brief": "BRIEF",
        "decisions": "DECISIONS",
        "recent_turns": "RECENT TURNS",
        "leela_excerpts": "RETRIEVED LEELA EXCERPTS",
        "artifacts": "ARTIFACTS",
        "addressed_chair": "ADDRESSED CHAIR",
    }
    rendered = "\n\n".join(f"## {headings[k]}\n{sections[k]}" for k in DEFAULT_SECTION_BUDGETS)
    return CompiledSessionPacket(packet=packet, rendered_prompt=rendered)


def plan_turn_policy(policy: str, *, addressed_chair: str = "chair") -> dict[str, Any]:
    """Return a bounded execution plan. No policy creates more than three turns."""

    if policy not in POLICIES:
        raise ValueError(f"unsupported turn policy {policy!r}; expected one of {sorted(POLICIES)}")

    specs = {
        "solo_claude": [("claude", (), "response")],
        "solo_gpt": [("gpt", (), "response")],
        "ask_both": [("claude", (), "response"), ("gpt", (), "response")],
        "claude_to_gpt": [("claude", (), "analysis"), ("gpt", (0,), "response")],
        "gpt_to_claude": [("gpt", (), "draft"), ("claude", (0,), "response")],
        "council_one_round": [
            ("claude", (), "judgment"),
            ("gpt", (), "implementation"),
            ("chair", (0, 1), "synthesis"),
        ],
    }
    turns = []
    for index, (role, inputs, purpose) in enumerate(specs[policy]):
        turns.append(
            {
                "index": index,
                "role": role,
                "addressed_to": addressed_chair if role != "chair" else "council",
                "depends_on": list(inputs),
                "purpose": purpose,
                "role_prompt": ROLE_PROMPTS[role],
            }
        )
    return {"policy": policy, "max_turns": 3, "turn_count": len(turns), "turns": turns}


# Concise aliases for orchestration callers.
compile_packet = compile_session_packet
plan_policy = plan_turn_policy
