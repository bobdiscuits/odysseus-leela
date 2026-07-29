# SETUP — J-Space Studio

J-Space Studio is a three-chair collaboration room layered on top of
[Odysseus](https://github.com/pewdiepie-archdaemon/odysseus). You (a human) sit with a
local model, a Claude chair, and a GPT chair, and route work between them with 12 run
modes — several of which are dependency-graph recipes rather than single calls.

**This is software you run yourself.** It talks only to endpoints you configure, on
your own machine, with your own keys. Nothing here connects to anyone else's instance.

---

## 0. The one thing that surprises people

**Chairs are not configured with environment variables.** There is nothing to put in
`.env` for them. Chair resolution happens at runtime by *matching model endpoints you
add in the Odysseus UI*, by name or URL. Get the naming right and the chairs light up;
get it wrong and they silently resolve to nothing and recipes return 409.

The matching contract is in section 3. Read it before you configure anything.

---

## 1. Prerequisites

- Odysseus itself, installed and running. Follow upstream's README first — this
  document assumes you already have a working Odysseus.
- **LiteLLM** serving an OpenAI-compatible API on port **4000** (for the local chairs).
- Optionally, an **Anthropic API key** (for the Claude chair).
- A local inference backend behind LiteLLM — Ollama, LM Studio, vLLM, whatever you use.

You do not need all three chairs. The room degrades honestly: modes that need a missing
chair report which one and why, rather than failing opaquely.

---

## 2. Stand up LiteLLM with the three aliases

The local chairs are resolved by **model alias**, so your LiteLLM config must publish
these exact names:

| Alias | Role in the room | Suggested model |
|---|---|---|
| `qwen-workhorse` | Drafting, the bulk of local work | A mid-size instruct model |
| `gemma-fast` | Context compression | A small, fast model |
| `apple-fm` | Router — decides whether to escalate to cloud at all | Anything tiny and cheap |

A minimal `config.yaml`:

```yaml
model_list:
  - model_name: qwen-workhorse
    litellm_params:
      model: ollama/<your-drafting-model>
      api_base: http://localhost:11434
  - model_name: gemma-fast
    litellm_params:
      model: ollama/<your-small-model>
      api_base: http://localhost:11434
  - model_name: apple-fm
    litellm_params:
      model: openai/<your-router-model>
      api_base: http://localhost:11435/v1
      api_key: none

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

Generate a real master key and keep it in LiteLLM's own environment, never in a config
file and never in this repo:

```
python -c "import secrets;print('sk-'+secrets.token_hex(32))"
```

Start it bound to loopback:

```
litellm --config config.yaml --host 127.0.0.1 --port 4000
```

Sanity check before moving on — both must succeed:

```
curl http://127.0.0.1:4000/health/liveliness
curl http://127.0.0.1:4000/v1/models
```

If `/v1/models` returns a 500 while liveliness is fine, one of your upstreams is
erroring and poisoning the whole list. Fix that before wiring the chairs, or they will
resolve to nothing for reasons that look like a J-Space bug and are not.

---

## 3. Add the endpoints in Odysseus — the naming contract

In the Odysseus UI, add each endpoint under model endpoints. The resolver matches on
these rules, and **only** these rules:

### Local chairs (qwen / gemma / router)

Matched if the endpoint **name contains `litellm`** (case-insensitive) **or** the
**base URL contains `:4000`**.

```
Name:     LiteLLM
Base URL: http://127.0.0.1:4000/v1
API key:  your LiteLLM virtual key
```

Then the room picks `qwen-workhorse`, `gemma-fast`, and `apple-fm` off that endpoint by
alias. If those aliases are not in the model list, those chairs stay empty.

### Claude chair

Matched if the endpoint **name contains `anthropic`** **or** the **base URL contains
`anthropic.com`**.

```
Name:     Anthropic
Base URL: https://api.anthropic.com/v1
API key:  your own Anthropic key
```

Model preference order is `claude-opus-4-8`, then `claude-opus`, then `claude-sonnet` —
the first one your key can see wins.

Your key is stored encrypted at rest in the `model_endpoints` table. It never enters
`.env`, never enters git, and never leaves your machine.

### GPT chair — optional, and read this first

Matched if the endpoint **name contains `chatgpt subscription`** **or** the **base URL
contains `chatgpt.com/backend-api/codex`**. Set up in the main Odysseus chat with:

```
/setup chatgpt-subscription
```

> ⚠️ **This chair drives a private consumer web API using your ChatGPT subscription
> session. That violates OpenAI's terms of service and risks a full account ban.** It is
> also fragile — tokens rotate and Cloudflare challenges break it without warning. Worse,
> it parks a full-account session token on disk, which is a strictly worse artifact to
> leak than a scoped API key.
>
> **Treat it as a toy chair, not load-bearing.** Every recipe that uses GPT has a
> Claude-only or local-only sibling. If you would rather not take the risk, skip this
> section entirely — the room works fine as a two-chair room.

---

## 4. Verify

Open J-Space Studio in the Odysseus UI. The chair rail shows readiness per chair. A chair
that is not ready tells you which endpoint it could not find.

Then run a mode in ascending order of dependency:

1. `local_draft` — needs only the LiteLLM chairs.
2. `claude_review` — gemma compresses, qwen drafts, Claude judges.
3. `full_council` — adds the GPT chair on the end.

---

## 5. The privacy doctrine — please keep it

This is deliberate design, not an accident of implementation:

**Cloud chairs never see the transcript.** They receive the brief plus compacted local
work, capped, with usage accounted. The local chairs see everything; the cloud chairs
see what you decided to send them.

If you fork this and remove that boundary, you have built a different thing. Say so
plainly to whoever runs it.

---

## 6. What is *not* in this repo

By design, and verified before publication:

- No `.env`. No API keys. No session tokens.
- No `data/` — no database, no chat history, no workspace records, no endpoint rows.
- No `logs/`, no `backups/`.
- No personal notes, vault content, hostnames, or tailnet addresses.

You get the code. You bring the keys, the models, and the machine.

---

## License

Odysseus and this fork are **AGPL-3.0-or-later**. If you run a modified version as a
network service, you must offer your users the corresponding source. If you redistribute
it, it stays AGPL. Keep the license file.
