# gulf-sync

Local “Jarvis-style” agent workspace for Gulf Chain coordination.

## What this does (MVP)
- You drop short quick-logs into `inbox/`
- The local agent reads them, generates a sync packet + status updates
- It auto-commits + pushes to GitHub
- It posts a notification to Discord (sandbox) with Top 3 changes + Next actions

## Commands (planned)
- agent run
- agent chat
- agent status
- agent stop
- agent --help / --version / --list

## Setup
- Copy `.env.example` to `.env` and fill values (do NOT commit `.env`)
