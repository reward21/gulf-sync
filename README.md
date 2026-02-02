# gulf-sync

**Local-first coordination and synchronization layer for the Gulf Chain trading system.**

`gulf-sync` is a lightweight, file-based “blackboard” used to keep AI agents, backtesters, governance processes, and humans in sync — without manual copy/paste between chat threads.

It provides a single, inspectable source of truth backed by Git, designed to be readable by both humans and AI systems.

---

##  Commands

`COMMANDS` is the readme for the available commands to use giulf-sync

Refer to COMMANDS_SECTION.md

---

## What gulf-sync is

`gulf-sync` is **coordination infrastructure**.

It does not trade, backtest, optimize strategies, or execute orders. Instead, it ensures that every participant in the system — human or machine — reads and writes from the same shared state in a deterministic, auditable way.

Core principles:
- Local-first execution
- Git-backed synchronization
- Append-only history
- Explicit state (no hidden memory)
- Markdown-first, AI-friendly files

---

## What gulf-sync does (MVP)

On each run, the local agent:

1. Reads new input files from the inbox
2. Generates a timestamped **Sync Packet** (append-only)
3. Updates a stable pointer to the latest packet
4. Routes one “next message” per logical thread
5. Updates local runtime state
6. Optionally commits and pushes changes to GitHub
7. Optionally notifies external systems (e.g. Discord sandbox)

This replaces fragile chat memory with deterministic, replayable coordination.

---

## Repository structure

### Inbox — inputs (human or agent)

```
inbox/
  YYYY-MM-DD_quicklog.md
  quicklog_template.md
```

Short updates, questions, or directives. Treated as immutable input.

---

### Sync packets — append-only history

```
sync/packets/
  YYYY-MM-DD_HHMM_sync_packet.md
  latest.md
```

Each packet is a snapshot of system context. Historical packets are never modified.  
`latest.md` is a stable pointer for easy reading.

---

### Outbox — per-thread routing

```
sync/outbox/
  gulf_chain_index/next.md
  spy_backtest/next.md
  risk_gate/next.md
  tech/next.md
```

Each logical thread or agent reads only its assigned `next.md`.  
These files are overwritten on each run and are not part of the permanent record.

---

### Canon — stable reference documents

```
canon/
  *.md
```

Governance rules, specs, decisions, and long-lived reference material.

---

### Runtime state (local-only)

```
status/
  state.json
  last_inbox_sig.txt
  last_packet_path.txt
```

Tracks IDLE/BUSY status and last processed inputs.  
Never committed to Git. Safe to delete if needed.

---

### Control and logs

```
control/
  STOP

logs/
  *.log
```

`control/STOP` acts as a soft stop flag.  
Logs are local diagnostics only.

---

## What gulf-sync is NOT

- Not a trading engine
- Not a backtester
- Not a strategy optimizer
- Not an execution system
- Not a database

It is **coordination infrastructure**.

---

## Intended workflow

1. **You or an agent** drops a quicklog into `inbox/`
2. `gulf-sync` generates a new packet in `sync/packets/`
3. `gulf-sync` routes per-thread directives into `sync/outbox/<thread>/next.md`
4. Each thread/agent reads its outbox message and responds (by writing back into `inbox/` or producing artifacts elsewhere)
5. Governance workflows (Council, Canon promotion) reference packets and evidence artifacts as immutable inputs

---

## Notes on public repos

This repo is safe to keep public **only if runtime state and secrets are never committed**.

Recommended `.gitignore` coverage includes:
- `.env` and any keys
- `status/*` runtime state
- local logs / locks
- any local DB files or caches

---

## Status

This is an MVP coordination layer intended to support:
- Gulf Chain multi-agent workflows
- backtest run routing and reporting
- deterministic governance (Risk Council / Canon promotion)
- reproducible state and audit trails
