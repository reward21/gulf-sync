#!/usr/bin/env python3
import os, sys, json, signal, subprocess, hashlib
from datetime import datetime
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
CONTROL = ROOT / "control"
INBOX = ROOT / "inbox"
SYNC_PACKETS = ROOT / "sync" / "packets"
STATUS_DIR = ROOT / "status"

CANON_DIR = ROOT / "canon"
OUTBOX_DIR = ROOT / "sync" / "outbox"
LATEST_PACKET_FILE = SYNC_PACKETS / "latest.md"

CHAT_KEYS = ["gulf_chain_index", "spy_backtest", "risk_gate", "tech"]

STATE_FILE = STATUS_DIR / "state.json"
STOP_FILE = CONTROL / "STOP"
LAST_INBOX_SIG_FILE = STATUS_DIR / "last_inbox_sig.txt"
LAST_PACKET_PATH_FILE = STATUS_DIR / "last_packet_path.txt"


# ---------- tiny env loader (no deps) ----------
def load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()


def now_ct():
    # MVP label (not DST-aware). Good enough for now.
    return datetime.now().strftime("%Y-%m-%d %H:%M CT")


def write_state(status, step="", detail=""):
    LOGS.mkdir(parents=True, exist_ok=True)
    data = {
        "status": status,
        "step": step,
        "detail": detail,
        "ts": now_ct(),
        "pid": os.getpid(),
    }
    STATE_FILE.write_text(json.dumps(data, indent=2))


def set_busy(step="starting", detail=""):
    write_state("BUSY", step=step, detail=detail)


def set_idle(detail=""):
    write_state("IDLE", step="", detail=detail)


def soft_stop():
    CONTROL.mkdir(parents=True, exist_ok=True)
    STOP_FILE.write_text(now_ct() + "\n")
    return 0


def should_stop():
    return STOP_FILE.exists()


def clear_stop_flag():
    if STOP_FILE.exists():
        try:
            STOP_FILE.unlink()
        except Exception:
            pass


# ---------- providers ----------
def discord_post(text: str):
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError("DISCORD_WEBHOOK_URL not set")
    payload = json.dumps({"content": text}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        _ = resp.read()
    return True


def ollama_chat(prompt: str, model: str = None):
    # Uses local Ollama (no API spend)
    load_env()
    if not model:
        model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b").strip()
    data = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        j = json.loads(resp.read().decode("utf-8"))
    return j["response"]


def read_file_safe(p: Path, max_bytes=200_000):
    data = p.read_bytes()
    if len(data) > max_bytes:
        data = data[:max_bytes]
    try:
        return data.decode("utf-8")
    except Exception:
        return data.decode("utf-8", errors="ignore")


def latest_inbox_entries(limit=3):
    """Return newest inbox markdown files (newest first).

    Sort primarily by modified time (mtime), then by name for stability.
    """
    INBOX.mkdir(parents=True, exist_ok=True)
    paths = list(INBOX.glob("*.md"))

    def _key(p: Path):
        try:
            return (p.stat().st_mtime_ns, p.name)
        except Exception:
            return (0, p.name)

    files = sorted(paths, key=_key, reverse=True)
    return files[:limit]


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
        data = json.loads(raw)
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


def inbox_signature(files):
    """Stable signature of current inbox inputs.

    Includes filename + modified time + size + contents, so new/edited files
    always trigger a new signature even if the text is similar.
    """
    h = hashlib.sha256()
    for p in sorted(files, key=lambda x: x.name):
        # metadata
        try:
            st = p.stat()
            h.update(p.name.encode("utf-8"))
            h.update(b"|")
            h.update(str(st.st_mtime_ns).encode("utf-8"))
            h.update(b"|")
            h.update(str(st.st_size).encode("utf-8"))
            h.update(b"\n")
        except Exception:
            h.update(p.name.encode("utf-8"))
            h.update(b"\n")

        # content
        try:
            h.update(p.read_bytes())
        except Exception:
            h.update(p.read_text(errors="ignore").encode("utf-8"))

        h.update(b"\n---\n")

    return h.hexdigest()


def build_sync_packet():
    load_env()

    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_PACKETS.mkdir(parents=True, exist_ok=True)

    inbox_files = latest_inbox_entries(limit=20)
    sig = inbox_signature(inbox_files)
    last_sig = LAST_INBOX_SIG_FILE.read_text().strip() if LAST_INBOX_SIG_FILE.exists() else ""

    # If the inbox hasn't changed since last run, reuse the last packet and skip commit/notify.
    if sig and sig == last_sig and LAST_PACKET_PATH_FILE.exists():
        rel = LAST_PACKET_PATH_FILE.read_text().strip()
        if rel:
            out_path = (ROOT / rel) if not Path(rel).is_absolute() else Path(rel)
            if out_path.exists():
                try:
                    packet = (STATUS_DIR / "tech.md").read_text()
                except Exception:
                    packet = out_path.read_text()
                return out_path, packet, False

    inbox_text = ""
    for p in inbox_files:
        inbox_text += f"\n\n---\nSOURCE: {p.name}\n---\n{p.read_text(errors='ignore')}\n"

    prompt = f"""You are TechGPT, the system integrator for Cole's gulf-sync workflow.
Your job: summarize what changed, what you did, and what Cole should do next.

OUTPUT FORMAT (STRICT):
- Title line: "✅✅✅ gulf-sync run complete ({now_ct()})"
- Then section header: "🧠 Top 3 changed files"
  - bullet list of up to 3 file paths (repo-relative)
- Then section header: "🎯 Next actions"
  - bullet list of 2–4 short next actions

Context (recent inbox):{inbox_text}

Now produce the output.
"""

    model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b").strip()
    try:
        packet = ollama_chat(prompt, model=model).strip()
    except Exception:
        # fallback: minimal packet if model unavailable
        packet = f"✅✅✅ gulf-sync run complete ({now_ct()})\n\n🧠 Top 3 changed files\n• (unknown)\n\n🎯 Next actions\n• Review inbox updates\n"

    out_name = datetime.now().strftime("%Y-%m-%d_%H%M") + "_sync_packet.md"
    out_path = SYNC_PACKETS / out_name
    out_path.write_text(packet + "\n")

    # Stable pointer for automation: overwrite latest.md when a new packet is created.
    try:
        LATEST_PACKET_FILE.write_text(packet + "\n")
    except Exception:
        pass

    # Store last sig + last packet path
    LAST_INBOX_SIG_FILE.write_text(sig)
    try:
        LAST_PACKET_PATH_FILE.write_text(str(out_path.relative_to(ROOT)) + "\n")
    except Exception:
        LAST_PACKET_PATH_FILE.write_text(str(out_path) + "\n")

    # Keep a tech status copy
    try:
        (STATUS_DIR / "tech.md").write_text(packet + "\n")
    except Exception:
        pass

    return out_path, packet, True


def git_commit_push(msg="gulf-sync: sync", push=True):
    # Only commit if there are changes (avoid empty commits)
    r = subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "git status failed")
    if not r.stdout.strip():
        return False

    subprocess.check_call(["git", "add", "-A"], cwd=str(ROOT))
    subprocess.check_call(["git", "commit", "-m", msg], cwd=str(ROOT))
    if push:
        subprocess.check_call(["git", "push"], cwd=str(ROOT))
    return True


def cmd_status():
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        print(STATE_FILE.read_text())
        return 0
    print(json.dumps({"status": "IDLE", "step": "", "detail": "", "ts": now_ct(), "pid": os.getpid()}, indent=2))
    return 0


def cmd_run(push=True, notify=True):
    load_env()
    clear_stop_flag()

    set_busy("packet", "building packet")
    out_path, packet, changed = build_sync_packet()

    # Route per-thread outbox messages (sync/outbox/<chat>/next.md)
    try:
        set_busy("route", "writing outboxes")
    except Exception:
        pass
    try:
        route_outboxes(packet)
    except Exception as e:
        print(f"[warn] Outbox routing failed: {e}")

    # If no inbox changes, we're done (routing still wrote outboxes based on latest packet).
    if not changed:
        set_idle("reused packet")
        print(f"No new inbox changes. Reused: {out_path}")
        return 0

    if should_stop():
        set_idle("stopped before commit")
        return 0

    committed = False
    try:
        set_busy("git", "commit/push")
        committed = git_commit_push(msg=f"gulf-sync: {out_path.name}", push=push)
    except Exception as e:
        print(f"[warn] Git commit/push failed: {e}")

    if should_stop():
        set_idle("stopped before notify")
        return 0

    if notify:
        try:
            set_busy("notify", "discord")
            discord_post(packet)
        except Exception as e:
            print(f"[warn] Discord notify failed: {e}")

    set_idle("done")
    if committed:
        print(f"DONE. Wrote: {out_path}")
    else:
        print(f"DONE (no git changes). Wrote: {out_path}")
    return 0


def cmd_chat():
    load_env()
    model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b").strip()
    print(f"gulf-sync chat ({model}). Ctrl+C to exit.\n")
    while True:
        try:
            user = input("you> ").strip()
            if not user:
                continue
            prompt = f"You are TechGPT. Be helpful, concise, and practical.\n\nUser: {user}\nAssistant:"
            ans = ollama_chat(prompt, model=model).strip()
            print(f"\nagent> {ans}\n")
        except KeyboardInterrupt:
            print("\nbye 👋")
            return 0


def usage():
    print("Available commands:")
    print("  agent run        Run one sync cycle (write packet, commit, push, notify)")
    print("  agent chat       Interactive chat in terminal")
    print("  agent status     Show BUSY/IDLE + current step")
    print("  agent stop       Soft stop (sets STOP flag)")
    print("Options:")
    print("  -h, --help       Help")
    print("  -v, --version    Version")
    print("  -l, --list       List commands")


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        usage()
        return 0

    if argv[0] in ("-v", "--version"):
        print("0.1.0")
        return 0

    if argv[0] in ("-l", "--list"):
        usage()
        return 0

    if argv[0] != "agent":
        usage()
        return 2

    if len(argv) < 2:
        usage()
        return 2

    cmd = argv[1]

    if cmd == "status":
        return cmd_status()

    if cmd == "stop":
        return soft_stop()

    if cmd == "chat":
        return cmd_chat()

    if cmd == "run":
        # Allow optional flags:
        #   --no-push
        #   --no-notify
        push = True
        notify = True
        if "--no-push" in argv:
            push = False
        if "--no-notify" in argv:
            notify = False
        return cmd_run(push=push, notify=notify)

    usage()
    return 2


if __name__ == "__main__":
    sys.exit(main())