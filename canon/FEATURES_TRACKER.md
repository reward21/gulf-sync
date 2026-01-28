# gulf-sync — Features Tracker
_Last updated: 2026-01-28 21:13 CT_

This is the persistent backlog + status board for everything Cole wants gulf-sync to do.

## Legend
- [ ] Not started
- [~] In progress
- [x] Done

---

## Core Sync Loop
- [x] Generate sync packet into `sync/packets/`
- [x] Auto-commit + push to GitHub
- [x] Discord webhook notify
- [x] No-change gate (skip commit/push/notify if inbox unchanged)
- [ ] Always-write `sync/packets/latest.md` (stable pointer to newest packet)
- [ ] `./gs run` shorthand (maps to `./gs agent run`)
- [ ] `./gs latest` (print latest packet to terminal)
- [ ] `./gs log` (create today’s quick log from template)
- [ ] `./gs run --force` (override inbox gate)

## Chat Mode Upgrades (Jarvis steps)
- [ ] Command routing inside `./gs agent chat` (natural language → whitelisted actions)
- [ ] Chat tool: “notify discord …” (ask for message if missing)
- [ ] Chat tool: “run sync” (executes `agent run`)
- [ ] Chat tool: “latest” (prints latest packet)
- [ ] “Plan + approve” mode (agent proposes steps; Cole approves before executing)

## Cross-Chat Communication (Artifact Bus)
Goal: chats “talk” through shared files in this repo.

- [ ] Outboxes per chat: `sync/outbox/<chat>/next.md`
- [ ] Router that writes targeted updates into outboxes (from latest packet + inbox)
- [ ] Packet format: To/From/Topic/Status/Requested actions/Attachments
- [ ] “Inbox per chat” (optional): `sync/inbox/<chat>/` for structured inputs

## Guardrails
- [ ] Protected paths (don’t edit `canon/` unless explicitly allowed)
- [ ] Dry run mode (no git commit/push)
- [ ] Confirm-before-commit mode for risky changes

## Providers / Models
- [~] Local Ollama provider working (chat + packet generation)
- [ ] Provider selection (Ollama now; cloud later)
- [ ] Model selection command (e.g., `./gs model llama3.1:8b`)

## Google Apps Script / Docs
- [ ] Sidebar UI polish + toggles (doc memory on/off, view/clear doc memory)
- [ ] Provider dropdown + key/url config in sidebar

## UI (Local ChatGPT-style)
- [ ] Pick a UI (AnythingLLM / Jan / Open WebUI)
- [ ] Connect UI buttons to gulf-sync commands (run/log/latest/notify)
