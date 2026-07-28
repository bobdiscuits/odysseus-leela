# J-Space Studio — Ensemble Harness v0.1

## Purpose

Odysseus becomes the room in which Shaun, Claude, and GPT/Codex make music
together. The chairs remain distinct; Leela and the project artifacts are the
shared field. The harness coordinates turns. It does not merge personas or let
models chatter without a bounded request from Shaun.

## Chairs

- **Shaun** — human director. Owns taste, red-line boundaries, publishing,
  deletion, and the final commit decision.
- **Claude** — continuity and musical judgment. Owns Leela retrieval,
  emotional/structural synthesis, lyrical continuity, and critique.
- **GPT/Codex** — construction and implementation. Owns files, code, measurable
  analysis, transformations, tooling, and artifact production.
- **Local ensemble** — Qwen, Gemma, Apple FM, Gemini, Demucs, SEAM, Orphanim,
  and Torrid are callable specialists/instruments, not permanent speakers.

## Turn modes

Every multi-model operation is finite and inspectable.

| Mode | Ordered calls |
|---|---|
| `solo_claude` | Claude |
| `solo_gpt` | GPT |
| `ask_both` | Claude, GPT independently |
| `claude_to_gpt` | Claude plans, GPT constructs |
| `gpt_to_claude` | GPT constructs, Claude reviews |
| `council_one_round` | Claude proposes, GPT responds, Claude synthesizes |

`Stop` cancels pending calls. No recursive continuation is allowed in v0.1.

## Durable session shape

Each studio session has a database record and may map to a Leela directory:

```text
~/Leela/Music-Suite/Sessions/<slug>/
├── SESSION.md
├── BRIEF.md
├── DECISIONS.md
├── OPEN_QUESTIONS.md
├── transcript.jsonl
├── lyrics/
├── audio/
├── stems/
├── analysis/
└── exports/
```

Database state is the interactive index. Files are the durable creative truth.

## Session packet

The context compiler renders only:

1. Chair role and addressed task.
2. Current brief and constraints.
3. Accepted decisions.
4. Recent turns.
5. Retrieved Leela excerpts.
6. Available artifacts.

Each section has a hard character budget. The entire vault is never placed in
the prompt. Retrieval is narrow; decisions and artifacts write back durably.

## v0.1 boundary

This slice provides persistence, API contracts, a three-chair UI, deterministic
context packets, and bounded turn plans. Provider execution is the next seam:
Claude uses the configured Anthropic endpoint; GPT/Codex uses Odysseus's current
Codex/OpenAI route; specialists route through LiteLLM.

## Safety and authority

- Existing Odysseus authentication and owner scoping apply.
- Shaun remains the only authority for public release, real recipients,
  financial actions, and destructive deletion.
- Artifact creation and local file edits are visible in the shared timeline.
- No model may silently commit a decision on Shaun's behalf.

