# gulf-sync — Working Documentation (Cole)
_Last updated: 2026-01-28 21:35 CT_

This document captures what we set up, what exists in the repo right now, how it works, and what to do next.

---

## 0) The original problem we’re solving

You had multiple ChatGPT threads (Gulf Chain Index, SPY Backtest Pipeline, RISK GATE, TechGPT) and you were **manually copy/pasting** information between:
- ChatGPT ↔ Google Docs/Drive
- and between different threads (indirectly via those docs)

Goal: **get it out of your hands** by creating a local “sync bus” that:
- captures updates (quick logs / packets),
- commits/pushes them to a private GitHub repo,
- notifies you (Discord),
- and (next) writes “targeted next messages” per chat into `sync/outbox/<chat>/next.md`.

---

## 1) What you have running now (current MVP)

### ✅ Repo
- GitHub repo created: **gulf-sync**
- Local clone at: `~/Projects/gulf-sync`
- Git push works (SSH keys are working).

### ✅ Launcher
- You have a launcher script named: `./gs`
- It supports flags:
  - `-v, --version`
  - `-l, --list`
  - `-h, --help`
- It exposes the agent commands.

### ✅ Agent commands (what you can run)
From repo root (`~/Projects/gulf-sync`):

- `./gs agent run`  
  Runs one sync cycle:
  - checks inbox signature (no-change gate)
  - writes a sync packet into `sync/packets/`
  - commits + pushes
  - posts a Discord notification (if enabled / when changes occur)

- `./gs agent chat`  
  Terminal chat mode (local Ollama model).  
  **Note:** unless you add routing/tool calls, chat mode is “LLM replies only.”

- `./gs agent status`  
  Shows BUSY/IDLE + current step (state files under `status/` + `logs/`).

- `./gs agent stop`  
  Soft stop flag (creates STOP flag in control). Useful for shutting down loops safely.

---

## 2) Local LLM setup (Ollama)

You installed Ollama and pulled local models. Verified via:

```
ollama list
llama3.1:8b
llama3.2:3b
llama3.2:1b
```

The agent’s chat mode uses:
- `OLLAMA_URL` (defaults to `http://127.0.0.1:11434`)
- `OLLAMA_MODEL` (defaults to `llama3.1:8b`)

This means **no paid API spend** for agent chat + routing (when routing is enabled).

---

## 3) Discord notifications

### What we did
- You created a Discord webhook and stored it in your `.env`.
- The agent posts notifications to your sandbox Discord server.

### Troubleshooting you encountered
- Early on you saw `HTTP Error 403: Forbidden` from Python’s `urllib`.
- Your manual curl test succeeded with `HTTP/2 204` (Discord accepted the webhook).
- We adjusted the agent to handle failures more gracefully (warn vs crash).

### Key fact
If curl works but Python fails:
- it’s usually one of:
  - wrong URL being read (env parsing / whitespace / quotes),
  - bad payload encoding,
  - a blocked/rotated webhook,
  - or request headers/formatting differences.

Right now you confirmed:
- no duplicate spam beyond your runs,
- two runs = two notifications (expected).

---

## 4) The “packet” concept (what packets are)

A **packet** is a single markdown snapshot that represents “what changed” and “what’s next.”

It’s meant to be:
- small enough to skim,
- structured enough to route,
- and easy for any chat/thread to consume.

Packets are written here:
- `sync/packets/YYYY-MM-DD_HHMM_sync_packet.md`

These are your **history**.

### No-change gate
The agent tries to avoid creating packets (and avoid Discord spam) when nothing meaningful changed.
That’s why back-to-back runs can behave differently:
- If the inbox signature didn’t change, it can skip posting.
- If you add a new quick log (or change content), the signature changes → new packet → Discord alert.

---

## 5) Added scaffolding files (downloaded zip you applied)

You added these “linking” scaffolds:

### `canon/FEATURES_TRACKER.md`
A persistent checklist of features you’ve requested.

### `sync/packets/latest.md` (placeholder)
A stable file path intended to always contain the newest packet.
This is important because automation needs **one stable target**.

### `sync/outbox/<chat>/next.md`
Outboxes for each chat thread:

- `sync/outbox/gulf_chain_index/next.md`
- `sync/outbox/spy_backtest/next.md`
- `sync/outbox/risk_gate/next.md`
- `sync/outbox/tech/next.md`

These are intended to be the **“next message to paste”** into each chat.

### `inbox/quicklog_template.md`
A template you can use to quickly capture updates you want the system to pick up.

### `APPLY.md`
Short instructions for applying the zip.

---

## 6) The planned “routing” upgrade (outbox routing)

### What routing means
Routing means: **after a run**, the agent writes a targeted message for each chat thread into:

`sync/outbox/<chat>/next.md`

So instead of you hunting packets and deciding what to send to each chat, the agent creates four “ready-to-paste” messages.

### Why this matters
It directly addresses your original pain:
- You stop assembling messages manually.
- You stop copy/pasting raw packets everywhere.
- You get “one file per chat” that says exactly what that chat needs next.

### Status
I generated a **patch bundle** (`gulf-sync_outbox_routing_patch.zip`) that can modify `agent/agent.py` to add:
- CANON snippets
- inbox context
- packet context
- local Ollama routing (JSON output)
- writing the outbox files

If you apply it, after `./gs agent run` you should see updated:
- `sync/outbox/*/next.md`

---

## 7) The big architecture (how chats “talk” without direct chat-to-chat messaging)

ChatGPT threads do not directly message each other.

So “chat-to-chat communication” is implemented by a **shared artifact bus**:

### The bus
- Your Git repo is the bus.
- Packets are the shared update stream.
- Outboxes are per-thread “instructions/messages.”

### The flow
1) You capture notes in `inbox/` (quick log)
2) `./gs agent run` produces:
   - packet history: `sync/packets/…`
   - (optionally) stable pointer: `sync/packets/latest.md`
   - (optionally) outboxes: `sync/outbox/<chat>/next.md`
3) You paste outbox files into their respective ChatGPT threads (for now).
4) Later we can automate that “paste step” via:
   - UI automation, or
   - an API-based orchestrator, or
   - a desktop agent framework.

This is the cleanest “no API spend” path to reduce friction immediately.

---

## 8) Folder map (what everything is for)

Top-level:
- `agent/` — Python agent code (`agent.py`) + providers
- `canon/` — stable “source of truth” docs (specs, index, risk gate, etc.)
- `inbox/` — your inputs (quick logs, notes)
- `sync/packets/` — timestamped history packets
- `sync/outbox/` — per-chat “next message” outputs
- `status/` — current state / last run info
- `logs/` — logs and lock/busy artifacts
- `control/` — stop flags or control files
- `scripts/` — helper scripts / patches
- `.env` — secrets and config (Discord webhook, model selection, etc.)

---

## 9) Key operational notes (things that bit you already)

### “permission denied: ./agent”
This happened because `./agent` was a directory, not an executable file.
You solved it by using `./gs` as the launcher and running `agent/agent.py`.

### SSH keys
- Keys are global for your user, not per-project folder.
- The public key is safe to upload to GitHub.
- The private key stays on disk (do not paste it anywhere).

---

## 10) What you can do right now (recommended next steps)

### A) Commit the scaffolding (if you haven’t yet)
You saw those new files as untracked.
Recommended:
- remove the delivery zip from repo root (don’t commit it)
- add and commit the new scaffolding

Example:
```
rm gulf-sync_additions.zip
git add APPLY.md canon/ inbox/ sync/outbox/ sync/packets/latest.md
git commit -m "Add features tracker + outbox scaffolding"
git push
```

### B) Add outbox routing (to reduce your work immediately)
Apply the routing patch, then:
- run `./gs agent run`
- open `sync/outbox/*/next.md`

### C) Add “latest.md” writing (stable pointer)
So every run updates:
- `sync/packets/latest.md`

This is useful for automation and for humans.

---

## 11) What “Jarvis mode” means in this project (realistic definition)

“Jarvis mode” here is two parts:

1) **Natural language → safe tool execution**
- You talk to the agent (“send discord update”, “run sync”, “show latest”).
- It routes to whitelisted actions.

2) **Automation loops**
- scheduled runs (every N minutes)
- only commits when changed
- safe stop + status reporting

We can do this without paid APIs by using:
- Ollama for reasoning/routing
- small guardrails (whitelisted commands, confirm-before-commit for risky actions)

---

## 12) Security reminders
- Keep `.env` out of git (`.gitignore` should ignore it).
- Discord webhooks are secrets (treat like passwords).
- Keep your repo private if it contains strategy/risk material.

---

## 13) Glossary (quick)
- **Packet**: a markdown update snapshot generated by the agent
- **Outbox**: per-chat “next message” file
- **Inbox**: your note drop folder
- **Canon**: stable source-of-truth docs/specs
- **Bus**: the repo as a shared communication layer

---

## 14) Current ask / direction
Your direction is: **prioritize routing** so the system reduces copy/paste.
UI can be tracked in the feature tracker, but not the priority right now.

