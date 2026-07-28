"""Persistent, owner-scoped Ensemble Studio API and live chair runner."""

import asyncio
import json
import uuid
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.database import (
    EnsembleArtifact, EnsembleDecision, EnsembleSession, EnsembleTurn, SessionLocal,
    utcnow_naive,
)
from src.auth_helpers import require_user
from src.ensemble_context import compile_session_packet, plan_turn_policy

PARTICIPANTS = ("Shaun", "Claude", "GPT")
_ACTIVE_RUNS: dict[str, asyncio.Task] = {}


class SessionCreate(BaseModel):
    title: str = Field(default="Untitled ensemble", min_length=1, max_length=200)


class TurnCreate(BaseModel):
    participant: Literal["Shaun", "Claude", "GPT"]
    role: Literal["human", "ai"]
    content: str = Field(min_length=1)


class DecisionCreate(BaseModel):
    content: str = Field(min_length=1)
    created_by: Literal["Shaun", "Claude", "GPT"] = "Shaun"


class ArtifactCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    artifact_type: str = Field(default="file", min_length=1, max_length=80)
    uri: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_by: Literal["Shaun", "Claude", "GPT"] = "Shaun"


class RunCreate(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    mode: Literal[
        "solo_claude", "solo_gpt", "ask_both", "claude_to_gpt",
        "gpt_to_claude", "council_one_round", "local_draft",
        "local_council", "auto", "claude_review", "gpt_build", "full_council",
    ] = "auto"
    target: Literal["claude", "gpt", "room"] = "room"


def _iso(value):
    return value.isoformat() if value else None


def _turn(row):
    return {"id": row.id, "participant": row.participant, "role": row.role,
            "content": row.content, "timestamp": _iso(row.timestamp)}


def _decision(row):
    return {"id": row.id, "content": row.content, "created_by": row.created_by,
            "timestamp": _iso(row.timestamp)}


def _artifact(row):
    return {"id": row.id, "name": row.name, "artifact_type": row.artifact_type,
            "uri": row.uri, "metadata": row.meta_data or {}, "created_by": row.created_by,
            "timestamp": _iso(row.timestamp)}


def _summary(row):
    return {"id": row.id, "title": row.title, "participants": row.participants or list(PARTICIPANTS),
            "created_at": _iso(row.created_at), "updated_at": _iso(row.updated_at)}


def _owned(db, session_id: str, owner: str):
    row = db.query(EnsembleSession).filter(
        EnsembleSession.id == session_id, EnsembleSession.owner == owner
    ).first()
    if not row:
        raise HTTPException(404, "Ensemble session not found")
    return row


def _validate_participant_role(participant: str, role: str) -> None:
    expected = "human" if participant == "Shaun" else "ai"
    if role != expected:
        raise HTTPException(422, f"{participant} turns must use role={expected!r}")


def _touch(session: EnsembleSession) -> None:
    session.updated_at = utcnow_naive()


def _models(row) -> list[str]:
    try:
        return [str(x) for x in json.loads(row.cached_models or "[]") if x]
    except Exception:
        return []


def _chair_specs(owner: str) -> dict[str, Optional[str]]:
    """Choose stable defaults from already-configured, owner-visible endpoints."""
    from core.database import ModelEndpoint

    with SessionLocal() as db:
        endpoints = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()
        endpoints = [ep for ep in endpoints if ep.owner in (None, owner)]
        claude = next((ep for ep in endpoints if "anthropic" in ep.name.lower()
                       or "anthropic.com" in ep.base_url.lower()), None)
        gpt = next((ep for ep in endpoints if "chatgpt subscription" in ep.name.lower()
                    or "chatgpt.com/backend-api/codex" in ep.base_url.lower()), None)

        def choose(ep, preferred):
            if not ep:
                return None
            available = _models(ep)
            model = next((m for want in preferred for m in available if want in m.lower()), None)
            return f"{model}@{ep.name}" if model else None

        local = next((ep for ep in endpoints if "litellm" in ep.name.lower()
                      or ":4000" in ep.base_url), None)
        return {
            "claude": choose(claude, ("claude-opus-4-8", "claude-opus", "claude-sonnet")),
            "gpt": choose(gpt, ("gpt-5.4", "gpt-5", "codex")),
            "qwen": choose(local, ("qwen-workhorse",)),
            "gemma": choose(local, ("gemma-fast",)),
            "router": choose(local, ("apple-fm",)),
        }


async def _call_chair(spec: str, role: str, prompt: str, owner: str,
                      max_tokens: int = 1800) -> tuple[str, str]:
    from src.ai_interaction import _resolve_model
    from src.llm_core import llm_call_async
    from src.ensemble_context import ROLE_PROMPTS

    url, model, headers = _resolve_model(spec, owner=owner)
    content = await llm_call_async(
        url, model,
        [{"role": "system", "content": ROLE_PROMPTS[role]},
         {"role": "user", "content": prompt}],
        headers=headers, timeout=240, max_tokens=max_tokens, temperature=0.35,
        prompt_type="ensemble",
    )
    return model, content.strip()


def setup_ensemble_routes() -> APIRouter:
    router = APIRouter(prefix="/api/ensemble", tags=["ensemble"])

    @router.post("/sessions", status_code=201)
    def create_session(payload: SessionCreate, request: Request):
        owner = require_user(request)
        with SessionLocal() as db:
            row = EnsembleSession(id=str(uuid.uuid4()), owner=owner, title=payload.title.strip(),
                                  participants=list(PARTICIPANTS))
            db.add(row)
            db.commit()
            db.refresh(row)
            return _summary(row)

    @router.get("/sessions")
    def list_sessions(request: Request):
        owner = require_user(request)
        with SessionLocal() as db:
            rows = db.query(EnsembleSession).filter(EnsembleSession.owner == owner).order_by(
                EnsembleSession.updated_at.desc()).all()
            return {"sessions": [_summary(row) for row in rows]}

    @router.get("/status")
    def ensemble_status(request: Request):
        owner = require_user(request)
        specs = _chair_specs(owner)
        return {
            "claude": {"ready": bool(specs["claude"]), "model": specs["claude"]},
            "gpt": {"ready": bool(specs["gpt"]), "model": specs["gpt"],
                    "setup_command": None if specs["gpt"] else "/setup chatgpt-subscription"},
            "local": {
                "ready": bool(specs["qwen"] and specs["gemma"]),
                "qwen": specs["qwen"], "gemma": specs["gemma"], "router": specs["router"],
            },
        }

    @router.get("/sessions/{session_id}")
    def get_session(session_id: str, request: Request):
        owner = require_user(request)
        with SessionLocal() as db:
            row = _owned(db, session_id, owner)
            result = _summary(row)
            result.update({
                "turns": [_turn(x) for x in sorted(row.turns, key=lambda x: x.timestamp)],
                "decisions": [_decision(x) for x in sorted(row.decisions, key=lambda x: x.timestamp)],
                "artifacts": [_artifact(x) for x in sorted(row.artifacts, key=lambda x: x.timestamp)],
            })
            return result

    @router.post("/sessions/{session_id}/turns", status_code=201)
    def append_turn(session_id: str, payload: TurnCreate, request: Request):
        owner = require_user(request)
        with SessionLocal() as db:
            session = _owned(db, session_id, owner)
            _validate_participant_role(payload.participant, payload.role)
            row = EnsembleTurn(id=str(uuid.uuid4()), session_id=session.id, **payload.model_dump())
            db.add(row)
            _touch(session)
            db.commit(); db.refresh(row)
            return _turn(row)

    @router.post("/sessions/{session_id}/decisions", status_code=201)
    def append_decision(session_id: str, payload: DecisionCreate, request: Request):
        owner = require_user(request)
        with SessionLocal() as db:
            session = _owned(db, session_id, owner)
            row = EnsembleDecision(id=str(uuid.uuid4()), session_id=session.id, **payload.model_dump())
            db.add(row)
            _touch(session)
            db.commit(); db.refresh(row)
            return _decision(row)

    @router.post("/sessions/{session_id}/artifacts", status_code=201)
    def append_artifact(session_id: str, payload: ArtifactCreate, request: Request):
        owner = require_user(request)
        with SessionLocal() as db:
            session = _owned(db, session_id, owner)
            data = payload.model_dump(exclude={"metadata"})
            row = EnsembleArtifact(id=str(uuid.uuid4()), session_id=session.id,
                                   meta_data=payload.metadata, **data)
            db.add(row)
            _touch(session)
            db.commit(); db.refresh(row)
            return _artifact(row)

    @router.post("/sessions/{session_id}/run")
    async def run_ensemble(session_id: str, payload: RunCreate, request: Request):
        owner = require_user(request)
        run_key = f"{owner}:{session_id}"
        previous = _ACTIVE_RUNS.get(run_key)
        if previous and not previous.done():
            previous.cancel()
        _ACTIVE_RUNS[run_key] = asyncio.current_task()
        specs = _chair_specs(owner)
        legacy = payload.mode in {"solo_claude", "solo_gpt", "ask_both", "claude_to_gpt",
                                  "gpt_to_claude", "council_one_round"}
        if legacy:
            plan = plan_turn_policy(payload.mode, addressed_chair=payload.target)
            steps = [(t["role"], t["purpose"], t["depends_on"]) for t in plan["turns"]]
        else:
            recipes = {
                "local_draft": [("gemma", "context compression", []), ("qwen", "local draft", [0])],
                "local_council": [("qwen", "proposal", []), ("gemma", "local critique", [0]),
                                  ("qwen", "revised result", [1])],
                "claude_review": [("gemma", "context compression", []), ("qwen", "local work", [0]),
                                   ("claude", "cloud judgment", [1])],
                "gpt_build": [("gemma", "context compression", []), ("qwen", "implementation plan", [0]),
                              ("gpt", "Codex build guidance", [1])],
                "full_council": [("gemma", "context compression", []), ("qwen", "local proposal", [0]),
                                 ("claude", "cloud judgment", [1]), ("gpt", "implementation review", [1, 2])],
                "auto": [("gemma", "context compression", []), ("qwen", "local result", [0])],
            }
            steps = recipes[payload.mode]
        needed = {role for role, _, _ in steps if role in ("claude", "gpt", "qwen", "gemma")}
        missing = sorted(role for role in needed if not specs.get(role))
        if missing:
            detail = {"error": "Chair setup required", "missing": missing}
            if "gpt" in missing:
                detail["action"] = "Run /setup chatgpt-subscription in the main Odysseus chat."
            raise HTTPException(409, detail)

        with SessionLocal() as db:
            session = _owned(db, session_id, owner)
            recent = [_turn(x) for x in sorted(session.turns, key=lambda x: x.timestamp)[-12:]]
            decisions = [_decision(x) for x in sorted(session.decisions, key=lambda x: x.timestamp)[-8:]]
            artifacts = [_artifact(x) for x in sorted(session.artifacts, key=lambda x: x.timestamp)[-8:]]
        packet = compile_session_packet(payload.text, decisions, recent, (), artifacts, payload.target)

        if payload.mode == "auto" and specs.get("router"):
            try:
                _, route = await _call_chair(specs["router"], "router", payload.text[:3000], owner, 12)
                route = route.strip().upper()
                if route.startswith("CLAUDE") and specs.get("claude"):
                    steps.append(("claude", "automatic cloud judgment", [1]))
                elif route.startswith("GPT") and specs.get("gpt"):
                    steps.append(("gpt", "automatic implementation escalation", [1]))
            except Exception:
                pass

        results = []
        by_index = {}
        cloud_calls = 0
        cloud_input_chars = 0
        for index, (role, purpose, dependency_ids) in enumerate(steps):
            dependencies = [by_index[i]["content"] for i in dependency_ids]
            is_cloud = role in ("claude", "gpt", "chair")
            if is_cloud:
                # Cloud chairs see the brief and compact local work, not the full transcript/vault.
                prompt = "## SHAUN'S BRIEF\n" + payload.text[:4000]
                if dependencies:
                    prompt += "\n\n## LOCAL WORK PRODUCT\n" + "\n\n---\n\n".join(x[:6000] for x in dependencies)
                prompt = prompt[:12000]
                cloud_calls += 1
                cloud_input_chars += len(prompt)
            else:
                prompt = packet.rendered_prompt
            if dependencies:
                if not is_cloud:
                    prompt += "\n\n## PRIOR ENSEMBLE OUTPUTS TO REVIEW\n" + "\n\n---\n\n".join(dependencies)
            model_chair = "claude" if role == "chair" else role
            token_cap = 900 if role == "gemma" else 2200
            model, content = await _call_chair(specs[model_chair], role, prompt, owner, token_cap)
            participant = {"claude": "Claude", "gpt": "GPT", "qwen": "Qwen", "gemma": "Gemma"}[model_chair]
            with SessionLocal() as db:
                session = _owned(db, session_id, owner)
                row = EnsembleTurn(id=str(uuid.uuid4()), session_id=session.id,
                                   participant=participant, role="ai", content=content)
                db.add(row); _touch(session); db.commit(); db.refresh(row)
            result = {"index": index, "speaker": model_chair, "participant": participant,
                      "purpose": purpose, "model": model, "content": content,
                      "cloud": is_cloud}
            by_index[index] = result
            results.append(result)
        response = {"session_id": session_id, "mode": payload.mode, "turns": results,
                "usage": {"local_calls": len(results) - cloud_calls, "cloud_calls": cloud_calls,
                          "estimated_cloud_input_tokens": (cloud_input_chars + 3) // 4,
                          "estimated_cloud_output_tokens": sum((len(x["content"]) + 3) // 4 for x in results if x["cloud"])}}
        _ACTIVE_RUNS.pop(run_key, None)
        return response

    @router.post("/sessions/{session_id}/stop")
    async def stop_ensemble(session_id: str, request: Request):
        owner = require_user(request)
        with SessionLocal() as db:
            _owned(db, session_id, owner)
        task = _ACTIVE_RUNS.pop(f"{owner}:{session_id}", None)
        cancelled = bool(task and not task.done())
        if cancelled:
            task.cancel()
        return {"session_id": session_id, "cancelled": cancelled, "status": "stopped"}

    return router
