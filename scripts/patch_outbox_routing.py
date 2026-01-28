#!/usr/bin/env python3
"""
Patch gulf-sync agent/agent.py to add:
- Outbox routing: sync/outbox/<chat>/next.md
- Optional canon context snippets (canon/*.md)
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

HELPERS_BLOCK = r'''
def read_text_if_exists(p: Path, max_bytes=200_000) -> str:
    if not p.exists():
        return ""
    try:
        return p.read_text(errors="ignore")[:max_bytes]
    except Exception:
        return ""


def canon_context_snippet(max_chars=6000) -> str:
    # Collect small snippets from canon files (if present) to help routing.
    if not CANON_DIR.exists():
        return ""
    parts = []
    for name in ["gulf_chain_index.md", "risk_gate_spec.md", "spy_backtest_pipeline.md", "FEATURES_TRACKER.md"]:
        p = CANON_DIR / name
        if p.exists():
            txt = read_text_if_exists(p, max_bytes=120_000).strip()
            if txt:
                parts.append(f"## {name}\n" + txt[:1500])
    blob = "\n\n".join(parts).strip()
    return blob[:max_chars]


def ensure_outbox_dirs():
    for k in CHAT_KEYS:
        (OUTBOX_DIR / k).mkdir(parents=True, exist_ok=True)


def route_outboxes(packet_text: str):
    """
    Write sync/outbox/<chat>/next.md files from newest packet using local Ollama.
    Uses: PACKET + latest INBOX entries + small CANON snippets.
    """
    load_env()
    ensure_outbox_dirs()

    # Latest inbox files (if any)
    inbox_files = latest_inbox_entries(limit=3)
    inbox_text = ""
    for p in inbox_files:
        try:
            inbox_text += f"\n\n---\nSOURCE: {p.name}\n---\n{p.read_text(errors='ignore')}\n"
        except Exception:
            pass

    canon_blob = canon_context_snippet()

    prompt = f"""
You are TechGPT. You route updates to 4 ChatGPT threads by writing one markdown message per thread.

THREADS (keys must match exactly):
- gulf_chain_index
- spy_backtest
- risk_gate
- tech

GOAL:
- Each message should be actionable, short, and specific to that thread.
- DO NOT invent progress. Use only what's in PACKET + INBOX + CANON.
- Include:
  - "✅✅✅ Top 3 changes"
  - "🎯 Next actions"
- If a thread has nothing to do, say "No action needed."

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
        # Fallback: dump packet to each outbox if parsing fails
        data = {k: packet_text for k in CHAT_KEYS}

    for k in CHAT_KEYS:
        msg = (data.get(k) or "").strip()
        if not msg:
            msg = "No action needed."
        out_path = OUTBOX_DIR / k / "next.md"
        out_path.write_text(msg + "\n")

    return True
'''

LATEST_WRITE_SNIPPET_BODY = """# Stable pointer for automation: overwrite latest.md when a new packet is created.
try:
    LATEST_PACKET_FILE.write_text(packet + "\\n")
except Exception:
    pass
"""

ROUTE_CALL_SNIPPET_BODY = """# Route per-thread outbox messages (sync/outbox/<chat>/next.md)
try:
    set_busy("route", "writing outboxes")
except Exception:
    pass

try:
    route_outboxes(packet)
except Exception as e:
    print(f"[warn] Outbox routing failed: {e}")
"""

def indent_block(text: str, indent: str) -> str:
    lines = text.splitlines()
    return "\n".join((indent + ln if ln.strip() else ln) for ln in lines) + "\n"

def insert_after_regex(src: str, pattern: str, insert: str) -> str:
    m = re.search(pattern, src, flags=re.MULTILINE)
    if not m:
        raise RuntimeError(f"Pattern not found:\n{pattern}")
    idx = m.end()
    return src[:idx] + insert + src[idx:]

def find_function_block(src: str, fn_name: str) -> tuple[int, int, str]:
    """
    Return (start_idx, end_idx, block_text) for a top-level `def fn_name(...):` block.
    """
    m = re.search(rf"^def\s+{re.escape(fn_name)}\s*\(.*?\):\s*\n", src, flags=re.MULTILINE)
    if not m:
        raise RuntimeError(f"Could not find function: {fn_name}()")
    start = m.start()
    # end at next top-level def
    m2 = re.search(r"^def\s+\w+\s*\(.*?\):\s*\n", src[m.end():], flags=re.MULTILINE)
    end = (m.end() + m2.start()) if m2 else len(src)
    return start, end, src[start:end]

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
            s = insert_after_regex(s, r'^STATUS_DIR\s*=\s*ROOT\s*/\s*"status"\s*$', "\n" + CONSTANTS_BLOCK)
        elif re.search(r'^SYNC_PACKETS\s*=\s*ROOT\s*/\s*"sync"\s*/\s*"packets"\s*$', s, flags=re.MULTILINE):
            s = insert_after_regex(s, r'^SYNC_PACKETS\s*=\s*ROOT\s*/\s*"sync"\s*/\s*"packets"\s*$', "\n" + CONSTANTS_BLOCK)
        else:
            raise RuntimeError("Could not find STATUS_DIR or SYNC_PACKETS to anchor constants insertion.")

    # 2) Insert helpers after latest_inbox_entries() if missing
    if "def route_outboxes" not in s:
        m = re.search(r'^def\s+latest_inbox_entries\([^)]*\):.*?(?=^def\s+|\Z)', s, flags=re.MULTILINE | re.DOTALL)
        if not m:
            raise RuntimeError("Could not locate latest_inbox_entries() to insert routing helpers.")
        insert_at = m.end()
        s = s[:insert_at] + "\n\n" + HELPERS_BLOCK + "\n\n" + s[insert_at:]

    # 3) Ensure cmd_run writes sync/packets/latest.md when packet is written
    if "LATEST_PACKET_FILE.write_text" not in s:
        # Insert after the line that writes the packet to disk.
        # We match the common shape: out_path.write_text(packet + "\n")
        m_write = re.search(r'^(?P<ind>\s*)out_path\.write_text\(\s*packet\s*\+\s*"\s*\\n"\s*\)\s*$', s, flags=re.MULTILINE)
        if m_write:
            ind = m_write.group("ind")
            s = insert_after_regex(
                s,
                r'^(?P<ind>\s*)out_path\.write_text\(\s*packet\s*\+\s*"\s*\\n"\s*\)\s*$',
                "\n" + indent_block(LATEST_WRITE_SNIPPET_BODY, ind)
            )
        else:
            # fallback anchor: tech.md status write (older versions)
            m_tech = re.search(r'^(?P<ind>\s*)\(STATUS_DIR\s*/\s*"tech\.md"\)\.write_text\(\s*packet\s*\+\s*"\s*\\n"\s*\)\s*$', s, flags=re.MULTILINE)
            if not m_tech:
                raise RuntimeError("Could not find where the packet is written to insert latest.md write.")
            ind = m_tech.group("ind")
            s = insert_after_regex(
                s,
                r'^(?P<ind>\s*)\(STATUS_DIR\s*/\s*"tech\.md"\)\.write_text\(\s*packet\s*\+\s*"\s*\\n"\s*\)\s*$',
                "\n" + indent_block(LATEST_WRITE_SNIPPET_BODY, ind)
            )

    # 4) Insert routing call inside cmd_run() after any build_sync_packet(...) call
    if "Outbox routing failed" not in s:
        start, end, block = find_function_block(s, "cmd_run")

        m_call = re.search(r'^(?P<ind>\s*).*build_sync_packet\s*\(.*\)\s*$', block, flags=re.MULTILINE)
        if not m_call:
            raise RuntimeError("Could not find any build_sync_packet(...) call inside cmd_run().")

        ind = m_call.group("ind")
        # Insert immediately after the matched line
        insert_pos = start + m_call.end()
        insertion = "\n" + indent_block(ROUTE_CALL_SNIPPET_BODY, ind)

        s = s[:insert_pos] + insertion + s[insert_pos:]

    AGENT.write_text(s)
    print(f"✅ Patched: {AGENT}")
    print(f"🗄️  Backup:  {bak.name}")
    print("\nNext:")
    print("  chmod +x agent/agent.py")
    print("  ./gs agent run")
    print("  ls -la sync/outbox/*/next.md")
    print("  head -n 40 sync/outbox/tech/next.md")

if __name__ == "__main__":
    main()