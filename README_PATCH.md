# gulf-sync — Outbox Routing Patch

This adds automatic routing so each run writes:

- sync/outbox/gulf_chain_index/next.md
- sync/outbox/spy_backtest/next.md
- sync/outbox/risk_gate/next.md
- sync/outbox/tech/next.md

It uses your local Ollama model (OLLAMA_URL/OLLAMA_MODEL) and:
- newest packet
- latest inbox notes
- small canon snippets

## Apply
From repo root:

python3 scripts/patch_outbox_routing.py
chmod +x agent/agent.py

Then test:

./gs agent run
ls -la sync/outbox/*/next.md
cat sync/outbox/tech/next.md
