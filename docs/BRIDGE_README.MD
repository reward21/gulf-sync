# GulfSync Bridge README

## Purpose

The bridge pulls **compact governance summaries** from the local multigate-backtest SQLite web API and writes them into GulfSync as:

- contract JSON (metadata + rollups + pointers)
- inbox routing note (for risk/governance threads)

It does **not** copy raw market data, large reports, charts, or SQLite files into this repo.

---

## Requirements

1. `multigate-backtest` API web server running (default: `http://127.0.0.1:8765`)
2. `gulf-sync` repo available locally

Optional env var:

```bash
BACKTEST_API_URL=http://127.0.0.1:8765
```

Default fallback is `http://127.0.0.1:8765`.

---

## Commands

Show bridge help:

```bash
./gs bridge help
```

Pull latest run once:

```bash
./gs bridge pull
```

Pull a specific run:

```bash
./gs bridge pull --run-id 20260211_195432_193aa326
```

Force re-import even if already imported:

```bash
./gs bridge pull --run-id 20260211_195432_193aa326 --force
```

Watch mode (poll API repeatedly):

```bash
./gs bridge loop --interval 20
```

Watch + route through normal GulfSync cycle when a new run appears:

```bash
./gs bridge loop --interval 20 --route
```

Watch + route + push/notify:

```bash
./gs bridge loop --interval 20 --route --push --notify
```

---

## What Gets Written

On successful import of a new `run_id`, bridge writes:

- `sync/contracts/backtest/<run_id>_governance_contract.json`
- `sync/contracts/backtest/latest.json`
- `inbox/<timestamp>_bridge_backtest_<run_id>.md`

Local state marker (dedupe):

- `status/last_backtest_run_id.txt`

If `run_id` is unchanged and `--force` is not used:

- no new files are written
- terminal prints:

```text
[bridge] no new run. latest=<run_id>
```

---

## Contract Contents (Compact)

Each contract JSON includes:

- `schema_version`
- `source` (API base)
- `run` metadata (symbol/vendor/timeframe/spec/version)
- `governance_summary`
  - `gate_metrics`
  - `decision_counts` (PASS/FAIL)
  - `top_denials_by_gate` (top denial codes)
  - `best_pf_gate`, `best_pf`
  - `council_precheck`
- `artifact_pointers`
  - report path
  - chart path
  - db path
  - resolved data path
  - sidecar path

This is intentionally small and pointer-based.

---

## Expected Terminal Output

Successful import:

```text
[bridge] imported run_id=20260211_195432_193aa326
[bridge] contract=/.../sync/contracts/backtest/20260211_195432_193aa326_governance_contract.json
[bridge] inbox=/.../inbox/2026-02-11_143135_bridge_backtest_20260211_195432_193aa326.md
```

Bridge loop:

```text
[bridge-loop] polling every 20s (route=True, push=False, notify=False)
[bridge-loop] no new run (20260211_195432_193aa326)
[bridge-loop] new run imported: 20260211_201201_ab12cd34
```

---

## Troubleshooting

Connection refused:

- confirm API web server is running
- confirm `BACKTEST_API_URL`

No runs found:

- ensure `runs` table has rows in backtester DB

No new imports:

- expected when latest `run_id` matches `status/last_backtest_run_id.txt`
- use `--force` to re-import

