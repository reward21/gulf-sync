GULFSYNC — PROTOCOL OVERVIEW (GOOGLE DOCS FRIENDLY)
Last updated: 2026-01-31 (America/Chicago)

1) What GulfSync is
GulfSync is a file-based “shared memory + consensus protocol” for the Gulf Chain ecosystem.
It replaces manual copy/paste between separate ChatGPT threads by making all threads read/write through one shared repo and folder convention.

In one sentence:
GulfSync = a Git repo + a folder protocol + a small runner (“agent”) that turns inbox updates into packets + per-thread next messages.

2) What GulfSync is NOT
- Not Jarvis
- Not a fully autonomous multi-step planner
- Not “chats talking to chats” directly

GulfSync’s job is coordination and state-sharing through files.

3) The problem it solves
ChatGPT threads are isolated. GulfSync creates a stable “communication substrate” so:
- New info goes into inbox files
- A run produces a summary packet
- The run routes targeted “next messages” into per-thread outboxes
- Everything is versioned and shared via GitHub

4) Folder architecture (meaning of each folder)

A) inbox/  (INPUT)
Drop updates here. Anything that should affect the system goes here.
Examples:
- “Backtest results”
- “Risk gate update”
- “Decision made”
- “New requirement”

B) sync/packets/  (RUN RECORD)
Each run may generate a timestamped packet:
- sync/packets/YYYY-MM-DD_HHMM_sync_packet.md
Stable pointer file:
- sync/packets/latest.md  (always overwritten to the newest packet)

C) sync/outbox/<thread>/next.md  (ROUTING OUTPUT)
GulfSync writes one “next message” per chat thread:
- sync/outbox/gulf_chain_index/next.md
- sync/outbox/spy_backtest/next.md
- sync/outbox/risk_gate/next.md
- sync/outbox/tech/next.md

D) canon/  (STABLE CANONICAL CONTEXT)
Long-lived “source of truth” snippets:
- definitions
- mandates
- hard rules
- structure
- non-negotiables

E) status/ logs/ control/  (OPS SURFACE)
- status/state.json : IDLE/BUSY and last step info
- logs/ : lock files + run logs
- control/STOP : soft stop flag for the runner

5) Workflow / data flow (how it runs)

Step 1 — You add/update files in inbox/
Step 2 — Run: ./gs agent run
Step 3 — GulfSync decides:
  - if inbox changed: write new packet + refresh sync/packets/latest.md
  - if inbox unchanged: reuse last packet
Step 4 — GulfSync routes outboxes:
  - writes sync/outbox/<thread>/next.md for each thread
Step 5 — Optional:
  - commits + pushes to GitHub
  - posts a Discord notification

6) “Agent” meaning in this repo
Here “agent” means:
- a deterministic runner that executes a known workflow loop
- reads inbox, writes packet/outboxes, commits/pushes, notifies (optional)

It does not mean full autonomy. It is a controlled automation loop.

7) Core commands (MVP)

Repository location:
cd ~/Projects/gulf-sync

List commands:
./gs --list

Status:
./gs agent status

Run (safe local test):
./gs agent run --no-push --no-notify

Run (normal):
./gs agent run

Stop (soft stop flag):
./gs agent stop

Chat (local Ollama chat CLI):
./gs agent chat

8) Model commands (local Ollama)

Show current model + list installed:
./gs model

List installed:
./gs model list

Set model (writes to .env):
./gs model set llama3.1:8b

Show Ollama URL:
./gs model url

Set Ollama URL:
./gs model set-url http://127.0.0.1:11434

9) Practical reality: how ChatGPT threads use GulfSync today
ChatGPT threads won’t automatically pull from GitHub. So the current workflow is:
- GulfSync writes packet + outboxes to files and pushes to GitHub
- You paste relevant outbox/packet content into each thread
- Threads respond with new content
- You drop responses into inbox/
- GulfSync runs again and routes

The next big “automation jump” will come from:
- UI automation (computer control), OR
- APIs, OR
- a local assistant UI with tool access (Jarvis layer)

10) What’s needed for Gulf Chain usefulness
Right now, routing can look repetitive if inbox content is mostly tooling notes.
To make it truly Gulf Chain useful, inbox/canon must contain real project state:
- Index snapshots
- backtest results + evidence pointers
- risk gate spec deltas + decisions

Once real content flows in, routing becomes differentiated.

END
