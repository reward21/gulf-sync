#!/usr/bin/env python3
import json
import os
import re
import signal
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List


@dataclass
class BridgeContext:
    root: Path
    inbox_dir: Path
    status_dir: Path
    stop_flag: Path
    now_ct: Callable[[], str]
    ensure_dirs: Callable[[], None]
    set_busy: Callable[[str, str], None]
    set_idle: Callable[[], None]
    stop_requested: Callable[[], bool]
    soft_stop_handler: Callable[[int, Any], None]
    hard_kill_handler: Callable[[int, Any], None]
    run_cycle: Callable[..., int]
    load_env: Callable[[], None]


def _contracts_dir(ctx: BridgeContext) -> Path:
    return ctx.root / "sync" / "contracts" / "backtest"


def _last_run_file(ctx: BridgeContext) -> Path:
    return ctx.status_dir / "last_backtest_run_id.txt"


def backtest_api_base(ctx: BridgeContext) -> str:
    ctx.load_env()
    return os.environ.get("BACKTEST_API_URL", "http://127.0.0.1:8765").strip().rstrip("/")


def http_json_post(url: str, payload: dict, timeout: int = 30) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    out = json.loads(raw or "{}")
    if not isinstance(out, dict):
        raise RuntimeError(f"Expected JSON object from POST {url}")
    return out


def sql_quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def api_query(base: str, sql: str, limit: int = 5000):
    data = http_json_post(f"{base}/api/query", {"sql": sql, "limit": int(limit)})
    if not data.get("ok"):
        raise RuntimeError(str(data.get("error") or "api query failed"))
    cols = data.get("columns", [])
    rows = data.get("rows", [])
    if not isinstance(cols, list) or not isinstance(rows, list):
        raise RuntimeError("invalid api query response shape")
    return cols, rows


def _rows_to_dicts(cols, rows):
    out = []
    for r in rows:
        if isinstance(r, (list, tuple)):
            out.append({str(cols[i]): r[i] if i < len(r) else None for i in range(len(cols))})
    return out


def latest_backtest_run_id(base: str) -> str:
    cols, rows = api_query(base, "SELECT run_id FROM runs ORDER BY created_at_utc DESC LIMIT 1", limit=1)
    items = _rows_to_dicts(cols, rows)
    if not items:
        raise RuntimeError("no runs found via /api/query")
    run_id = str(items[0].get("run_id") or "").strip()
    if not run_id:
        raise RuntimeError("latest run_id was empty")
    return run_id


def _safe_run_id(run_id: str) -> str:
    rid = str(run_id or "").strip()
    if not rid:
        raise ValueError("run_id is empty")
    if not re.match(r"^[A-Za-z0-9_.:-]+$", rid):
        raise ValueError(f"run_id contains unsupported characters: {rid!r}")
    return rid


def build_governance_contract(base: str, run_id: str) -> dict:
    rid = _safe_run_id(run_id)
    qrid = sql_quote(rid)

    run_cols, run_rows = api_query(
        base,
        (
            "SELECT run_id, created_at_utc, date_start_et, date_end_et, params_json, "
            "report_path, equity_curve_path FROM runs "
            f"WHERE run_id={qrid} LIMIT 1"
        ),
        limit=1,
    )
    run_items = _rows_to_dicts(run_cols, run_rows)
    if not run_items:
        raise RuntimeError(f"run_id not found: {rid}")
    run_row = run_items[0]

    params = {}
    try:
        params = json.loads(str(run_row.get("params_json") or "{}"))
        if not isinstance(params, dict):
            params = {}
    except Exception:
        params = {}

    gm_cols, gm_rows = api_query(
        base,
        (
            "SELECT gate_id, trade_count, win_rate, pf, expectancy, maxdd, "
            "worst_day, worst_trade, zero_trade_day_pct, ending_equity "
            "FROM gate_metrics "
            f"WHERE run_id={qrid} ORDER BY gate_id"
        ),
        limit=200,
    )
    gate_metrics = _rows_to_dicts(gm_cols, gm_rows)

    gd_cols, gd_rows = api_query(
        base,
        (
            "SELECT gate_id, "
            "SUM(CASE WHEN decision='PASS' THEN 1 ELSE 0 END) AS pass_count, "
            "SUM(CASE WHEN decision='FAIL' THEN 1 ELSE 0 END) AS fail_count "
            "FROM gate_decisions "
            f"WHERE run_id={qrid} GROUP BY gate_id ORDER BY gate_id"
        ),
        limit=200,
    )
    decision_counts = _rows_to_dicts(gd_cols, gd_rows)

    dc_cols, dc_rows = api_query(
        base,
        (
            "SELECT gate_id, COALESCE(denial_code,'UNKNOWN') AS denial_code, COUNT(*) AS n "
            "FROM gate_decisions "
            f"WHERE run_id={qrid} AND decision='FAIL' "
            "GROUP BY gate_id, COALESCE(denial_code,'UNKNOWN') "
            "ORDER BY gate_id, n DESC"
        ),
        limit=500,
    )
    denial_rows = _rows_to_dicts(dc_cols, dc_rows)

    denials_by_gate = {}
    for row in denial_rows:
        gid = str(row.get("gate_id") or "").strip() or "UNKNOWN"
        denials_by_gate.setdefault(gid, [])
        if len(denials_by_gate[gid]) < 5:
            denials_by_gate[gid].append(
                {
                    "denial_code": row.get("denial_code"),
                    "count": int(row.get("n") or 0),
                }
            )

    best_gate = None
    best_pf = None
    for row in gate_metrics:
        try:
            pf = float(row.get("pf"))
        except Exception:
            continue
        gid = str(row.get("gate_id") or "")
        if not gid:
            continue
        if best_pf is None or pf > best_pf:
            best_pf = pf
            best_gate = gid

    return {
        "schema_version": "gulfsync_backtest_governance_contract_v1",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "type": "multigate-backtest-api",
            "api_base": base,
        },
        "run": {
            "run_id": rid,
            "created_at_utc": run_row.get("created_at_utc"),
            "date_start_et": run_row.get("date_start_et"),
            "date_end_et": run_row.get("date_end_et"),
            "symbol": params.get("source_symbol"),
            "vendor": params.get("source_vendor"),
            "dataset": params.get("source_dataset"),
            "schema": params.get("source_schema"),
            "bar_timeframe": params.get("bar_timeframe"),
            "timezone": params.get("timezone"),
            "rth_window": {
                "enabled": bool(params.get("rth_enabled", False)),
                "start": params.get("rth_start"),
                "end": params.get("rth_end"),
            },
            "start_equity": params.get("start_equity"),
            "spec_version": params.get("spec_version"),
            "strategy_version": params.get("strategy_version"),
        },
        "governance_summary": {
            "gate_metrics": gate_metrics,
            "decision_counts": decision_counts,
            "top_denials_by_gate": denials_by_gate,
            "best_pf_gate": best_gate,
            "best_pf": best_pf,
            "council_precheck": {
                "status": "NEEDS_MORE_EVIDENCE",
                "reason": "contract contains single-run summary; attach multi-window evidence packet for council vote",
            },
        },
        "artifact_pointers": {
            "report_path": run_row.get("report_path"),
            "equity_curve_path": run_row.get("equity_curve_path"),
            "db_path": params.get("db_path"),
            "resolved_data_path": params.get("resolved_data_path"),
            "source_sidecar_path": params.get("source_sidecar_path"),
        },
    }


def _bridge_decision_line(decision_counts: list, gate_id: str) -> str:
    for row in decision_counts:
        if str(row.get("gate_id") or "") == gate_id:
            return f"PASS={int(row.get('pass_count') or 0)}, FAIL={int(row.get('fail_count') or 0)}"
    return "PASS=0, FAIL=0"


def write_bridge_inbox(ctx: BridgeContext, contract_relpath: str, contract: dict) -> Path:
    ctx.inbox_dir.mkdir(parents=True, exist_ok=True)
    run = contract.get("run", {}) if isinstance(contract, dict) else {}
    gov = contract.get("governance_summary", {}) if isinstance(contract, dict) else {}
    rid = str(run.get("run_id") or "unknown")
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out = ctx.inbox_dir / f"{stamp}_bridge_backtest_{rid}.md"

    best_gate = gov.get("best_pf_gate") or "n/a"
    best_pf = gov.get("best_pf")
    try:
        best_pf_s = f"{float(best_pf):.4f}"
    except Exception:
        best_pf_s = "n/a"

    decision_counts = gov.get("decision_counts", []) if isinstance(gov, dict) else []
    g1_line = _bridge_decision_line(decision_counts, "G1")
    g2_line = _bridge_decision_line(decision_counts, "G2")

    text = (
        f"## FROM: bridge\n"
        f"## SOURCE: multigate-backtest-api\n"
        f"## RUN_ID: {rid}\n"
        f"## CREATED: {ctx.now_ct()}\n\n"
        f"## TO:risk_gate\n"
        f"- New governance contract imported: `{contract_relpath}`\n"
        f"- run_id: `{rid}`\n"
        f"- best_pf_gate: `{best_gate}` (pf={best_pf_s})\n"
        f"- quick decision counts: G1({g1_line}), G2({g2_line})\n"
        f"- request: evaluate this contract against the Council rubric and return PASS/FAIL/NEEDS_MORE_EVIDENCE with machine-readable constraints.\n\n"
        f"## TO:gulf_chain_index\n"
        f"- Record pointer: `{contract_relpath}` for run `{rid}`\n"
        f"- request: note governance status and any canon-layer implications.\n\n"
        f"## TO:tech\n"
        f"- Bridge import successful for run `{rid}` from local API.\n"
        f"- request: confirm routing + packet generation path stays minimal (no raw data copy).\n"
    )
    out.write_text(text, encoding="utf-8")
    return out


def bridge_pull(ctx: BridgeContext, run_id: str = "", force: bool = False):
    ctx.ensure_dirs()
    base = backtest_api_base(ctx)
    rid = _safe_run_id(run_id) if run_id else latest_backtest_run_id(base)

    last_file = _last_run_file(ctx)
    last = last_file.read_text().strip() if last_file.exists() else ""
    if (not force) and last and rid == last:
        return {
            "new": False,
            "run_id": rid,
            "reason": "already imported",
            "contract_path": "",
            "inbox_path": "",
        }

    ctx.set_busy("bridge", f"pulling run_id={rid}")
    try:
        contract = build_governance_contract(base, rid)
        contracts_dir = _contracts_dir(ctx)
        contracts_dir.mkdir(parents=True, exist_ok=True)
        contract_name = f"{rid}_governance_contract.json"
        contract_path = contracts_dir / contract_name
        blob = json.dumps(contract, indent=2, ensure_ascii=True) + "\n"
        contract_path.write_text(blob, encoding="utf-8")

        latest_path = contracts_dir / "latest.json"
        latest_path.write_text(blob, encoding="utf-8")

        rel_contract = str(contract_path.relative_to(ctx.root))
        inbox_path = write_bridge_inbox(ctx, rel_contract, contract)

        last_file.write_text(rid + "\n", encoding="utf-8")
    finally:
        ctx.set_idle()

    return {
        "new": True,
        "run_id": rid,
        "contract_path": str(contract_path),
        "inbox_path": str(inbox_path),
    }


def cmd_bridge(ctx: BridgeContext, args: list) -> int:
    sub = (args[0] if args else "pull").strip().lower()

    if sub in ("help", "-h", "--help"):
        print("""Bridge commands:
  ./gs bridge pull [--run-id <id>] [--force]
    Pull one run from local backtest API and write:
      - sync/contracts/backtest/<run_id>_governance_contract.json
      - sync/contracts/backtest/latest.json
      - inbox/<timestamp>_bridge_backtest_<run_id>.md

    Flags:
      --run-id <id>     import a specific run_id (default: latest run)
      --run-id=<id>     same as above
      --force           re-import even if run_id was already imported

    Typical terminal output:
      [bridge] imported run_id=20260211_195432_193aa326
      [bridge] contract=/.../sync/contracts/backtest/20260211_195432_193aa326_governance_contract.json
      [bridge] inbox=/.../inbox/2026-02-11_143135_bridge_backtest_20260211_195432_193aa326.md

  ./gs bridge loop [--interval 20] [--route] [--push] [--notify]
    Poll local backtest API repeatedly.
    On a new run_id:
      - imports compact contract
      - optionally routes via `agent run` when --route is set

    Flags:
      --interval 20     polling interval in seconds
      --interval=20     same as above
      --route           trigger `agent run` after successful import
      --push            only used with --route (enables git push)
      --notify          only used with --route (enables Discord notify)

    Typical terminal output:
      [bridge-loop] polling every 20s (route=True, push=False, notify=False)
      [bridge-loop] no new run (20260211_195432_193aa326)
      [bridge-loop] new run imported: 20260211_201201_ab12cd34

Environment:
  BACKTEST_API_URL      default: http://127.0.0.1:8765
""")
        return 0

    if sub == "pull":
        run_id = ""
        force = False

        if "--force" in args:
            force = True
        if "--run-id" in args:
            try:
                run_id = str(args[args.index("--run-id") + 1]).strip()
            except Exception:
                run_id = ""
        for a in args:
            if a.startswith("--run-id="):
                run_id = a.split("=", 1)[1].strip()

        try:
            out = bridge_pull(ctx, run_id=run_id, force=force)
        except Exception as e:
            print(f"[bridge] failed: {e}")
            return 2

        if not out.get("new"):
            print(f"[bridge] no new run. latest={out.get('run_id')}")
            return 0

        print(f"[bridge] imported run_id={out.get('run_id')}")
        print(f"[bridge] contract={out.get('contract_path')}")
        print(f"[bridge] inbox={out.get('inbox_path')}")
        return 0

    if sub == "loop":
        interval_s = 20
        route = "--route" in args
        push = "--push" in args
        notify = "--notify" in args

        if "--interval" in args:
            try:
                interval_s = int(args[args.index("--interval") + 1])
            except Exception:
                interval_s = 20
        for a in args:
            if a.startswith("--interval="):
                try:
                    interval_s = int(a.split("=", 1)[1])
                except Exception:
                    interval_s = 20

        try:
            if ctx.stop_flag.exists():
                ctx.stop_flag.unlink()
        except Exception:
            pass

        signal.signal(signal.SIGINT, ctx.soft_stop_handler)
        signal.signal(signal.SIGTERM, ctx.hard_kill_handler)

        print(f"[bridge-loop] polling every {interval_s}s (route={route}, push={push}, notify={notify})")
        while not ctx.stop_requested():
            try:
                out = bridge_pull(ctx, run_id="", force=False)
                if out.get("new"):
                    print(f"[bridge-loop] new run imported: {out.get('run_id')}")
                    if route:
                        ctx.run_cycle(push=push, notify=notify)
                else:
                    print(f"[bridge-loop] no new run ({out.get('run_id')})")
            except Exception as e:
                print(f"[bridge-loop] error: {e}")

            if ctx.stop_requested():
                break
            time.sleep(max(1, int(interval_s)))

        ctx.set_idle()
        print("[bridge-loop] STOP detected; exiting")
        return 0

    print("Unknown bridge subcommand.")
    print("Usage:")
    print("  ./gs bridge pull [--run-id <id>] [--force]")
    print("  ./gs bridge loop [--interval 20] [--route] [--push] [--notify]")
    return 2
