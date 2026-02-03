# gulf-sync ✅

**Local-first “blackboard” repo for coordinating Gulf Chain agents, backtests, and governance — without copy/paste between chats.**

`gulf-sync` does **not** trade or backtest by itself. It **routes files**:
**inbox → packet → outbox**, and keeps an append-only audit trail via Git.

---

## Quick start

```bash
git clone https://github.com/reward21/gulf-sync.git
cd gulf-sync

# first-time setup
cp .env.example .env   # fill values; NEVER commit .env

# run one cycle
./gs agent run
```

---

## How it works (mental model)

- **Inbox (`inbox/`)** = *your inputs* (notes, requests, directives)
- **Packets (`sync/packets/`)** = *append-only history* (what happened + what to do next)
- **Outbox (`sync/outbox/<thread>/next.md`)** = *per-thread “next message”* (overwritten each cycle)

If there are **no inbox changes**, `agent run` will reuse the most recent packet and may produce no new outbox updates by design.

---

## Commands

### Runner

```bash
./gs agent run
```
Run **one** sync cycle:
reads inbox → writes/updates packet → updates outbox → optionally commit/push/notify.

### Loop

```bash
./gs agent loop
```
Run continuously until stopped (default every **15s**).

- **Ctrl+C once** = soft stop (creates `control/STOP`)
- **Ctrl+C twice** = hard stop (force quit)

Optional flags:
```bash
./gs agent loop --interval 30
./gs agent loop --interval=60
./gs agent loop --no-push
./gs agent loop --no-notify
```
### Status

```bash
./gs agent status
```
Show BUSY/IDLE + current step.

### Stop (Two ways to stop:)

  1. In loop mode terminal session:
    - **Ctrl+C once** = soft stop (creates `control/STOP`)
    - **Ctrl+C twice** = hard stop (force quit)

  2. In another terminal session
```bash
cd /gulf-sync
./gs agent stop
```
Soft stop request (creates `control/STOP`). Useful if you want to stop a loop from another terminal.

### Local terminal chat (Ollama)

```bash
./gs agent chat
```
Interactive terminal chat using your **local** Ollama server.

**Important:** this chat does **not** automatically read/write repo files — it’s for quick reasoning or small paste-in tasks.

### Model helpers (Ollama)

```bash
./gs model
./gs model list
./gs model set <model>
./gs model url
./gs model set-url <url>
```

---

## Repo layout

### Inputs
```
inbox/
  YYYY-MM-DD_quicklog.md
  quicklog_template.md
```

### Generated packets (history)
```
sync/packets/
  YYYY-MM-DD_HHMM_sync_packet.md
  latest.md
```

### Generated outbox (per-thread routing)
```
sync/outbox/
  gulf_chain_index/next.md
  spy_backtest/next.md
  risk_gate/next.md
  tech/next.md
```

### Canon (stable, long-lived docs)
```
canon/
  *.md
```

### Runtime state (local-only)
```
status/
  state.json
  last_inbox_sig.txt
  last_packet_path.txt
```

### Control + logs (local-only)
```
control/
  STOP

logs/
  *.log
```

---

## Public repo hygiene (non-negotiable)

Keep secrets and runtime state **out of Git**:
- `.env`, keys, tokens, credentials
- `status/*`
- logs, locks, local DB/caches

If something sensitive ever gets committed, rewrite history immediately (e.g., `git filter-repo`) and rotate the secret.

---

## What this enables

- Deterministic coordination across agents (“same truth”)
- Reproducible governance (Risk Council / Canon promotion) via packets + evidence pointers
- A clean place for OpenWebUI runners to read/write without mixing chat memory with system state
