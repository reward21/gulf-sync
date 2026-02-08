# GulfSync Protocol — Agent Workflow (v1)

## Purpose
Define how GulfSync coordinates backtests, governance, and routing between agents without chat-to-chat memory.

## Roles
- **Runner**: Executes backtests or tasks and writes artifacts.
- **GulfSync Agent**: Packages results, routes messages, updates state.
- **Council**: Reviews evidence packets.
- **Orchestrator**: Decides what runs next (human or automated).

## Workflow (Agent-Readable)
1. Watch `inbox/` for new input files.
2. If new input exists:
   - Read latest inbox entry.
   - Generate a sync packet in `sync/packets/YYYY-MM-DD_HHMM_sync_packet.md`.
3. Update stable pointer:
   - Overwrite `sync/packets/latest.md`.
4. Route messages:
   - Write one `sync/outbox/<thread>/next.md` per target thread.
5. Update runtime state:
   - Write status to `status/state.json`.
6. If in loop mode:
   - Sleep N seconds.
   - Repeat until `control/STOP` exists.

## STOP Behavior
- First Ctrl+C: create `control/STOP` (soft stop).
- Second Ctrl+C: hard exit.

## Guarantees
- Append-only packets.
- Deterministic routing.
- No hidden state outside repo.

## Non-Goals
- No strategy optimization.
- No execution authority.

