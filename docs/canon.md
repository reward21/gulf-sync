# GULF-SYNC — CANON (Source of Truth)

**Spec:** `gulfsync_canon_v1.0`  
**Created:** 2026-02-03 (America/Chicago)  
**Last Updated:** 2026-02-03 (America/Chicago)

---

## 0) Why this file exists

`gulf-sync` is the **shared mailbox + blackboard** for Gulf Chain.  
It exists to eliminate manual copy/paste between chats by giving every “role” (human, runner, council, orchestrator) the **same deterministic inputs and outputs**.

If anything conflicts across README / chat instructions / notes, **this Canon wins** unless updated here.

---

## 1) Core definition

**GulfSync = a file-first protocol** that:
1) accepts human/agent inputs as **Inbox** notes,
2) produces a **timestamped Sync Packet** (append-only),
3) writes **per-thread Outbox messages** (“next.md”) that can be pasted into the target thread/UI,
4) optionally commits + pushes to GitHub and notifies downstream systems.

GulfSync **does not** decide truth; it **routes** and **records** it.

---

## 2) Non-negotiables (governance + safety)

### 2.1 Determinism over vibes
- Outputs must be reproducible from committed inputs.
- “Same inbox + same code + same config” ⇒ same packet/outbox.

### 2.2 Public repo hygiene (hard rule)
- **DO NOT leak sensitive/private data** — ever.
- Secrets **must never** be committed (tokens, keys, personal info).
- Prefer “least privilege” defaults.

### 2.3 Append-only history
- Sync packets are append-style artifacts (`sync/packets/YYYY-MM-DD_HHMM_sync_packet.md`).
- “Latest” pointers may be overwritten, but **history files are immutable** once created.

---

## 3) Scope vs non-scope

### In scope (v1)
- Inbox → packet → outbox routing
- Stable “latest pointers”
- Optional Git commit/push
- Optional notifications (Discord/webhook)
- Minimal status indicators (IDLE/BUSY + timestamps)

### Not in scope (v1)
- Running backtests inside GulfSync
- Strategy logic, Risk Gate logic, Council voting logic
- Direct file-system authority in external UIs
- Automated execution of trades

GulfSync is the **transport + audit trail**, not the trading brain.

---

## 4) Canonical repo layout (contract)

### 4.1 Inbox (human/agent input)
- `inbox/`
  - `YYYY-MM-DD_quicklog.md` (your daily input)
  - `quicklog_template.md` (optional template)

**Rule:** If inbox content doesn’t change, `agent run` should not emit a new packet.

### 4.2 Packets (append-only output)
- `sync/packets/`
  - `YYYY-MM-DD_HHMM_sync_packet.md` (immutable history)
  - `latest.md` (stable pointer, overwritten each run)

### 4.3 Outbox (per-thread “next message”)
- `sync/outbox/<thread_key>/next.md` (stable pointer, overwritten as routing updates)

**Thread keys must be stable strings**, e.g.:
- `gulf_chain_index`
- `risk_council`
- `risk_gate`
- `spy_backtest`
- `tech`

### 4.4 Canon (reference snippets)
- `canon/`
  - long-lived reference notes the system can quote
  - example: constraints, naming doctrine, “how to paste packets”, etc.

### 4.5 Runtime control + state
- `control/STOP` (soft stop flag for loops)
- `status/state.json` (runtime status; **treated as runtime**, not source-of-truth)

---

## 5) Command semantics (what each command *means*)

### `./gs agent run`
**One** deterministic sync cycle:
1) detect inbox changes
2) write (or reuse) packet
3) update `sync/packets/latest.md`
4) route to `sync/outbox/**/next.md`
5) optionally commit + push + notify

### `./gs agent loop`
Continuous mode:
- repeats `agent run` every interval (default 15s)
- **soft stop:** first Ctrl+C sets `control/STOP`
- **hard stop:** second Ctrl+C exits immediately

### `./gs agent stop`
Creates/sets `control/STOP` so `agent loop` exits gracefully.

### `./gs agent status`
Shows whether the system considers itself IDLE/BUSY and what it was doing.

### `./gs agent chat`
Optional local chat convenience (Ollama terminal chat).  
**It does not route packets** unless you explicitly design it to write into `inbox/`.

---

## 6) What is “source of truth” here?

### Canonical truth *about trading* lives elsewhere
- Risk Council / Risk Gate / strategy specs live in Gulf Chain Canon docs.
- GulfSync only carries messages + pointers.

### Canonical truth *about routing* lives here
- Thread keys
- folder layout contract
- how packets/outbox are generated
- what must be ignored for public hygiene

---

## 7) Public-repo hygiene rules (must follow)

### 7.1 Always ignore secrets
- `.env`
- `*.key`
- any API key files
- any local-only tokens, cookies, auth blobs

### 7.2 Ignore runtime state that changes constantly
- `status/state.json`
- locks, logs, PID-ish runtime markers

### 7.3 Keep *protocol artifacts* in Git
- packets (history) ✅
- `sync/packets/latest.md` ✅ (ok to overwrite)
- outbox `next.md` ✅ (ok to overwrite)

Reason: the public repo is the “shared mailbox” for humans + agents.

---

## 8) Integration intent (OpenWebUI + agents)

GulfSync is designed so an Orchestrator can:
- read `sync/packets/latest.md`
- read `sync/outbox/<thread>/next.md`
- paste the outbox into the correct WebUI chat
- paste responses back into `inbox/` as new quicklogs or reply files

This is **human-in-the-loop by default** until you explicitly add automation.

---

## 9) Minimal operating workflow (happy path)

1) You write an update into `inbox/YYYY-MM-DD_quicklog.md`
2) Run:
   - `./gs agent run` (one cycle) **or**
   - `./gs agent loop` (continuous until STOP)
3) You open:
   - `sync/packets/latest.md` (global view)
   - `sync/outbox/<thread>/next.md` (per-thread message)
4) Paste outbox text into the target chat
5) Paste chat’s response back into a new inbox quicklog
6) Repeat

---

## 10) Change discipline

- Any material protocol change requires:
  - bumping a `spec` string (e.g. `gulfsync_canon_v1.1`)
  - adding a short bullet to a Change Log file (recommended: `canon/CHANGELOG.md`)

---

## 11) Change Log (append-only)

- 2026-02-03 — `gulfsync_canon_v1.0` created.
