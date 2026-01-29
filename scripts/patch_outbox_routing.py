#!/usr/bin/env python3
"""
Patch gulf-sync agent/agent.py to add:
- OUTBOX routing: sync/outbox/<chat>/next.md
- CANON context snippets for better routing
- Write sync/packets/latest.md when a new packet is created

Safe: makes a timestamped .bak copy before editing.
Idempotent: won't re-insert if already present.
"""

from __future__ import annotations
from pathlib import Path
import re
import datetime

REPO_ROOT = Path.cwd()
AGENT = REPO_ROOT / "agent" / "agent.py"

CONSTANTS_BLOCK = """CANON_DIR = ROOT / "canon"
OUTBOX_DIR = ROOT / "sync" / "outbox"
LATEST_PACKET_FILE = SYNC_PACKETS / "latest.md"

CHAT_KEYS = ["gulf_chain_index", "spy_backtest", "risk_gate", "tech"]
"""

HELPERS_BLOCK = """\
def read_text_if_exists(p: Path, max_bytes=200_000) -> str:
    if not p.exists():
        return ""
    try:
        return p.read_text(errors="ignore")[:max_bytes]
    except Exception:
        return ""


def canon_context_snippet(max_chars=6000) -> str:
    """Collect small snippets from canon files (if present) to help routing."""
    parts = []
    if not CANON_DIR.exists():
        return ""
    for name in ["gulf_chain_index.md", "risk_gate_spec.md", "spy_backtest_pipeline.md", "FEATURES_TRACKER.md"]:
        p = CANON_DIR / name
        if p.exists():
            txt = read_text_if_exists(p, max_bytes=120_000).strip()
            if txt:
                parts.append(f"## {name}\n" + txt[:1500])
    blob = "\n\n".join(parts).strip()
    return blob[:max_chars]


def ensure_outbox_files():
    for k in CHAT_KEYS:
        (OUTBOX_DIR / k).mkdir(parents=True, exist_ok=True)


def route_outboxes(packet_text: str):
    """Write sync/outbox/<chat>/next.md files from the newest packet (local Ollama)."""
    load_env()
    ensure_outbox_files()

    inbox_files = latest_inbox_entries(limit=3)
    inbox_text = ""
    for p in inbox_files:
        try:
            inbox_text += f"\n\n---\nSOURCE: {p.name}\n---\n{p.read_text(errors='ignore')}\n"
        except Exception:
            pass

    canon_blob = canon_context_snippet()

    prompt = f"""You are TechGPT. You route updates to 4 ChatGPT threads by writing one markdown message per thread.

THREADS (keys must match exactly):
1) gulf_chain_index
2) spy_backtest
3) risk_gate
4) tech

GOAL:
- Each message should be actionable, short, and specific to that thread.
- DO NOT invent progress. Use only what's in PACKET + INBOX + CANON.
- Include a small "✅✅✅ Top 3 changes" list and "🎯 Next actions" list in each message.
- If a thread has nothing to do, say "No action needed" and keep it short.

OUTPUT FORMAT (STRICT):
Return VALID JSON only. No code fences. No commentary.
Keys must be exactly: gulf_chain_index, spy_backtest, risk_gate, tech
Values must be markdown strings.

CANON (snippets):
{canon_blob}

INBOX (latest):
{inbox_text}

PACKET (latest):
{packet_text}
"""

    try:
        raw = ollama_chat(prompt).strip()
        import json as _json
        data = _json.loads(raw)
    except Exception:
        data = {k: packet_text for k in CHAT_KEYS}

    for k in CHAT_KEYS:
        msg = (data.get(k) or "").strip()
        if not msg:
            msg = "No action needed."
        out_path = OUTBOX_DIR / k / "next.md"
        out_path.write_text(msg + "\n")
    return True
"""

LATEST_WRITE_SNIPPET = """\
    # Stable pointer for automation: overwrite latest.md when a new packet is created.
    try:
        LATEST_PACKET_FILE.write_text(packet + "\n")
    except Exception:
        pass
"""

ROUTE_CALL_SNIPPET = """\
        # Route per-thread outbox messages (sync/outbox/<chat>/next.md)
        set_busy("route", "writing outboxes")
        try:
            route_outboxes(packet)
        except Exception as e:
            print(f"[warn] Outbox routing failed: {e}")
"""

def insert_after_pattern(src: str, pattern: str, insert: str) -> str:
    m = re.search(pattern, src, flags=re.MULTILINE)
    if not m:
        raise RuntimeError(f"Pattern not found: {pattern}")
    idx = m.end()
    return src[:idx] + insert + src[idx:]


def main():
    if not AGENT.exists():
        raise SystemExit(f"Not found: {AGENT} (run this from repo root: {REPO_ROOT})")

    s = AGENT.read_text()

    # Backup
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = AGENT.with_suffix(f".py.bak_{ts}")
    bak.write_text(s)

    # 1) Insert constants if missing
    if "OUTBOX_DIR" not in s:
        if re.search(r'^STATUS_DIR\s*=\s*ROOT\s*/\s*"status"\s*$', s, flags=re.MULTILINE):
            s = insert_after_pattern(s, r'^STATUS_DIR\s*=\s*ROOT\s*/\s*"status"\s*$', "\n" + CONSTANTS_BLOCK)
        elif re.search(r'^SYNC_PACKETS\s*=\s*ROOT\s*/\s*"sync"\s*/\s*"packets"\s*$', s, flags=re.MULTILINE):
            s = insert_after_pattern(s, r'^SYNC_PACKETS\s*=\s*ROOT\s*/\s*"sync"\s*/\s*"packets"\s*$', "\n" + CONSTANTS_BLOCK)
        else:
            raise RuntimeError("Could not locate STATUS_DIR or SYNC_PACKETS to insert OUTBOX constants.")

    # 2) Insert helpers after latest_inbox_entries
    if "def route_outboxes" not in s:
        m = re.search(r'^def\s+latest_inbox_entries\(.*?\):.*?(?=^def\s+|\Z)', s, flags=re.MULTILINE | re.DOTALL)
        if not m:
            raise RuntimeError("Could not locate latest_inbox_entries() to insert helper functions.")
        insert_at = m.end()
        s = s[:insert_at] + "\n\n" + HELPERS_BLOCK + "\n\n" + s[insert_at:]

    # 3) Write latest.md after tech.md write OR after packet write
    if "LATEST_PACKET_FILE.write_text" not in s:
        if re.search(r'\(STATUS_DIR\s*/\s*"tech\.md"\)\.write_text\(packet\s*\+\s*"\\n"\s*\)', s):
            s = insert_after_pattern(
                s,
                r'\(STATUS_DIR\s*/\s*"tech\.md"\)\.write_text\(packet\s*\+\s*"\\n"\s*\)',
                "\n" + LATEST_WRITE_SNIPPET
            )
        else:
            s = insert_after_pattern(
                s,
                r'out_path\.write_text\(packet\s*\+\s*"\\n"\s*\)',
                "\n" + LATEST_WRITE_SNIPPET
            )

    # 4) Call route_outboxes(packet) inside cmd_run after build_sync_packet
    if "Outbox routing failed" not in s:
        if re.search(r'if\s+not\s+changed:\s*\n\s*print\(.+?\)\s*\n\s*return\s+0', s, flags=re.MULTILINE):
            s = insert_after_pattern(
                s,
                r'if\s+not\s+changed:\s*\n\s*print\(.+?\)\s*\n\s*return\s+0',
                "\n" + ROUTE_CALL_SNIPPET
            )
        else:
            m2 = re.search(r'out_path\s*,\s*packet.*?=\s*build_sync_packet\(\)', s)
            if not m2:
                m2 = re.search(r'out_path\s*,\s*packet\s*=\s*build_sync_packet\(\)', s)
            if not m2:
                raise RuntimeError("Could not locate build_sync_packet() call in cmd_run.")
            s = s[:m2.end()] + "\n" + ROUTE_CALL_SNIPPET + s[m2.end():]

    AGENT.write_text(s)

    print(f"✅ Patched: {AGENT}")
    print(f"🗄️  Backup:  {bak.name}")
    print("")
    print("Next:")
    print("  chmod +x agent/agent.py")
    print("  ./gs agent run")
    print("  ls -la sync/outbox/*/next.md")
    print("  cat sync/outbox/tech/next.md | head")

if __name__ == "__main__":
    main()
