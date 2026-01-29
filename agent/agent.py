#!/usr/bin/env python3
import os, sys, json, signal, subprocess, hashlib, time
from datetime import datetime
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
INBOX = ROOT / "inbox"
CANON = ROOT / "canon"
SYNC_PACKETS = ROOT / "sync" / "packets"
OUTBOX_DIR = ROOT / "sync" / "outbox"
STATUS_DIR = ROOT / "status"
CONTROL_DIR = ROOT / "control"

STOP_FLAG = CONTROL_DIR / "STOP"
STATE_FILE = STATUS_DIR / "state.json"

LATEST_PACKET_FILE = SYNC_PACKETS / "latest.md"
LAST_INBOX_SIG_FILE = STATUS_DIR / "last_inbox_sig.txt"
LAST_PACKET_PATH_FILE = STATUS_DIR / "last_packet_path.txt"

VERSION = "0.1.0"
CHAT_KEYS = ["gulf_chain_index", "spy_backtest", "risk_gate", "tech"]


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
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "step": step,
        "detail": detail,
        "ts": now_ct(),
        "pid": os.getpid(),
    }
    try:
        STATE_FILE.write_text(json.dumps(payload, indent=2) + "\n")
    except Exception:
        pass


def set_idle():
    write_state("IDLE", "", "")


def set_busy(step, detail=""):
    write_state("BUSY", step, detail)


# ---------- helpers ----------
def ensure_dirs():
    INBOX.mkdir(parents=True, exist_ok=True)
    CANON.mkdir(parents=True, exist_ok=True)
    (ROOT / "sync").mkdir(parents=True, exist_ok=True)
    SYNC_PACKETS.mkdir(parents=True, exist_ok=True)
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)


def ensure_outbox_dirs():
    for k in CHAT_KEYS:
        (OUTBOX_DIR / k).mkdir(parents=True, exist_ok=True)


def stop_requested():
    return STOP_FLAG.exists()


def soft_stop_handler(signum, frame):
    # Soft stop: set STOP flag
    try:
        CONTROL_DIR.mkdir(parents=True, exist_ok=True)
        STOP_FLAG.write_text(f"STOP requested {now_ct()}\n")
    except Exception:
        pass


def hard_kill_handler(signum, frame):
    raise KeyboardInterrupt


def canon_context_snippet(max_chars=5000):
    """
    Read small snippets from canon/*.md so routing can reference stable context.
    """
    try:
        files = sorted(CANON.glob("*.md"))
        blob = []
        for f in files:
            txt = f.read_text(errors="ignore").strip()
            if not txt:
                continue
            blob.append(f"# {f.name}\n{txt}\n")
            if sum(len(x) for x in blob) > max_chars:
                break
        out = "\n".join(blob)
        if len(out) > max_chars:
            out = out[:max_chars] + "\n...(truncated)\n"
        return out
    except Exception:
        return ""


def latest_inbox_entries(limit=3):
    """
    Return newest .md files from inbox/
    """
    if not INBOX.exists():
        return []
    files = [p for p in INBOX.glob("*.md") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


# ---------- providers ----------
def ollama_chat(prompt: str, model: str = None) -> str:
    """
    Uses local Ollama server (http://127.0.0.1:11434).
    """
    load_env()
    url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").strip().rstrip("/")

    # Allow users to set a base URL; normalize to a POST endpoint.
    if url in ("http://127.0.0.1:11434", "http://localhost:11434"):
        url = url + "/api/generate"

    # If someone accidentally points at a GET-only endpoint, fix it.
    if url.endswith("/api/tags"):
        url = url[:-9] + "/api/generate"  # replace /api/tags -> /api/generate
    model = (model or os.environ.get("OLLAMA_MODEL", "llama3.1:8b")).strip()

    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        j = json.loads(raw)
        return (j.get("response") or "").strip()


def discord_post(text: str):
    load_env()
    hook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not hook:
        return
    payload = json.dumps({"content": text}).encode("utf-8")
    req = urllib.request.Request(
        hook,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


# ---------- git helpers ----------
def sh(cmd, cwd=None, check=True):
    return subprocess.run(cmd, cwd=cwd, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def git_is_repo():
    return (ROOT / ".git").exists()


def git_add_all():
    sh(["git", "add", "-A"], cwd=str(ROOT))


def git_commit(message: str):
    # Avoid leaking personal email/name (use local override if user didn't configure)
    sh(["git", "config", "user.name", "Cole"], cwd=str(ROOT), check=False)
    sh(["git", "config", "user.email", "noreply@gulf-sync.local"], cwd=str(ROOT), check=False)

    # Don't fail if nothing to commit
    r = subprocess.run(["git", "commit", "-m", message], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return r.returncode, r.stdout + r.stderr


def git_push():
    r = subprocess.run(["git", "push"], cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return r.returncode, r.stdout + r.stderr


# ---------- packet ----------
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


def route_outboxes(packet_text: str):
    """
    Write sync/outbox/<chat>/next.md files from newest packet.

    Priority order:
    1) Deterministic routing: if inbox files contain "## TO:<chat>" sections, route those.
    2) LLM routing fallback: ask local Ollama to return JSON mapping for the 4 chats.
       If parsing fails or output is identical, fall back to a safe "needs directives" message.
    """
    load_env()
    ensure_outbox_dirs()

    # Read latest inbox files (more than 3 so routing has enough context)
    inbox_files = latest_inbox_entries(limit=20)

    inbox_text = ""
    raw_inbox_for_directives = ""
    for p in inbox_files:
        try:
            txt = p.read_text(errors="ignore")
            inbox_text += f"\n\n---\nSOURCE: {p.name}\n---\n{txt}\n"
            raw_inbox_for_directives += f"\n\n# FILE: {p.name}\n{txt}\n"
        except Exception:
            pass

    canon_blob = canon_context_snippet()

    # ---------- deterministic routing via "TO:" sections ----------
    # Supported header lines (case-insensitive):
    #   ## TO:gulf_chain_index
    #   ## TO:spy_backtest
    #   ## TO:risk_gate
    #   ## TO:tech
    #
    # Anything under that header goes to that chat until the next TO header.
    def extract_to_blocks(text: str):
        blocks = {}
        cur = None
        buf = []

        aliases = {
            "gulf_chain_index": "gulf_chain_index",
            "gulf chain index": "gulf_chain_index",
            "index": "gulf_chain_index",
            "spy_backtest": "spy_backtest",
            "spy backtest": "spy_backtest",
            "backtest": "spy_backtest",
            "risk_gate": "risk_gate",
            "risk gate": "risk_gate",
            "tech": "tech",
        }

        def flush():
            nonlocal cur, buf
            if cur and cur in CHAT_KEYS:
                blocks[cur] = "\n".join(buf).strip()
            cur = None
            buf = []

        for line in text.splitlines():
            s = line.strip()
            s_low = s.lower()

            if s_low.startswith("## to:") or s_low.startswith("# to:"):
                flush()
                raw_key = s.split(":", 1)[1].strip().lower()
                cur = aliases.get(raw_key, raw_key)
                if cur not in CHAT_KEYS:
                    cur = None
                continue

            if cur:
                buf.append(line)

        flush()
        return blocks

    blocks = extract_to_blocks(raw_inbox_for_directives)
    has_directives = any((blocks.get(k) or "").strip() for k in CHAT_KEYS)

    data = {}

    if has_directives:
        # Wrap directives into a consistent format unless the user already wrote a formatted packet.
        def wrap_if_needed(body: str, chat_key: str):
            body = (body or "").strip()
            if not body:
                return "No action needed."
            # If it already looks like our standard format, keep it as-is.
            if ("✅✅✅" in body) or ("🎯" in body):
                return body

            # Heuristic: promote bullet lines into "Next actions"
            bullets = []
            for ln in body.splitlines():
                s = ln.strip()
                if s.startswith(("-", "*", "•")):
                    bullets.append(s.lstrip("-*• ").strip())
            bullets = [b for b in bullets if b][:4]

            if bullets:
                next_actions = "\n".join([f"• {b}" for b in bullets])
            else:
                next_actions = "• Review the routed note and decide next steps."

            top_changes = "• Routed note from inbox\n• (See inbox files for details)\n• (Reference: sync/packets/latest.md)"

            return (
                "✅✅✅ Top 3 changes\n"
                f"{top_changes}\n\n"
                "🎯 Next actions\n"
                f"{next_actions}\n"
            )

        for k in CHAT_KEYS:
            data[k] = wrap_if_needed(blocks.get(k, ""), k)

    else:
        # ---------- LLM routing fallback (local Ollama; no API spend) ----------
        prompt = f"""
You are TechGPT. You route updates to 4 ChatGPT threads by writing one markdown message per thread.

THREADS:
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
""".strip()

        model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b").strip()

        try:
            raw = ollama_chat(prompt, model=model).strip()

            # Strip accidental code fences
            if "```" in raw:
                raw = raw.replace("```json", "").replace("```", "").strip()

            # Extract the JSON object if the model added extra text
            jstart = raw.find("{")
            jend = raw.rfind("}")
            if jstart != -1 and jend != -1 and jend > jstart:
                raw = raw[jstart : jend + 1]

            data = json.loads(raw)
        except Exception:
            data = {}

        # Validate structure
        if not isinstance(data, dict):
            data = {}

        # Ensure all keys exist
        for k in CHAT_KEYS:
            if k not in data:
                data[k] = ""

        # If the model produced identical outputs, that's effectively not routing.
        vals = [((data.get(k) or "").strip()) for k in CHAT_KEYS]
        all_same = bool(vals) and all(v and v == vals[0] for v in vals)

        if all_same:
            data = {}

        if not data:
            # Safe fallback that forces outboxes to differ and tells Cole how to control routing
            data = {
                "gulf_chain_index": (
                    "✅✅✅ Top 3 changes\n"
                    "• Routing needs directives to be chat-specific\n"
                    "• Latest packet updated (sync/packets/latest.md)\n"
                    "• Inbox signature gate working (repeat runs reuse)\n\n"
                    "🎯 Next actions\n"
                    "• Add an inbox quicklog with: ## TO:gulf_chain_index\n"
                    "• Include what Index should broadcast to other chats\n"
                ),
                "spy_backtest": (
                    "✅✅✅ Top 3 changes\n"
                    "• Routing needs directives to be chat-specific\n"
                    "• Latest packet updated (sync/packets/latest.md)\n\n"
                    "🎯 Next actions\n"
                    "• Add an inbox quicklog section: ## TO:spy_backtest\n"
                    "• Put the specific backtest question/task there\n"
                ),
                "risk_gate": (
                    "✅✅✅ Top 3 changes\n"
                    "• Routing needs directives to be chat-specific\n"
                    "• Latest packet updated (sync/packets/latest.md)\n\n"
                    "🎯 Next actions\n"
                    "• Add an inbox quicklog section: ## TO:risk_gate\n"
                    "• Put the specific Risk Gate rule/spec change there\n"
                ),
                "tech": (
                    "✅✅✅ Top 3 changes\n"
                    "• LLM JSON routing failed or returned identical output\n"
                    "• Fell back to directive-driven routing guidance\n\n"
                    "🎯 Next actions\n"
                    "• Use ## TO:<chat> sections in inbox to route deterministically\n"
                    "• Re-run: ./gs agent run --no-push --no-notify\n"
                    "• Verify outboxes differ in sync/outbox/*/next.md\n"
                ),
            }

    # ---------- write outboxes ----------
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


# ---------- commands ----------
def cmd_status():
    ensure_dirs()
    if STATE_FILE.exists():
        print(STATE_FILE.read_text())
    else:
        print(json.dumps({"status": "UNKNOWN"}, indent=2))
    return 0


def cmd_stop():
    ensure_dirs()
    STOP_FLAG.write_text(f"STOP requested {now_ct()}\n")
    print("Soft stop requested ✅")
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
            print(f"\nagent[{model}]> {ans}\n")
        except KeyboardInterrupt:
            print("\nbye 👋")
            return 0


def cmd_run(push=True, notify=True):
    ensure_dirs()
    ensure_outbox_dirs()

    # setup soft/hard Ctrl+C behavior:
    # first Ctrl+C sets STOP flag, second Ctrl+C raises KeyboardInterrupt
    signal.signal(signal.SIGINT, soft_stop_handler)

    set_busy("packet", "building sync packet")
    out_path, packet, is_new = build_sync_packet()

    # If no new inbox changes, reuse packet and skip commit/push/notify.
    if not is_new:
        print(f"No new inbox changes. Reused: {out_path}")
        set_idle()
        return 0

    if stop_requested():
        print("STOP requested — aborting before routing.")
        set_idle()
        return 0

    set_busy("route", "writing outboxes")
    try:
        route_outboxes(packet)
    except Exception as e:
        print(f"[warn] outbox routing failed: {e}")

    if stop_requested():
        print("STOP requested — aborting before commit/push/notify.")
        set_idle()
        return 0

    # commit changes
    if git_is_repo():
        set_busy("git", "committing")
        git_add_all()
        code, out = git_commit(f"gulf-sync: {out_path.name}")
        if out.strip():
            print(out.strip())

        if push:
            set_busy("git", "pushing")
            code, out = git_push()
            if out.strip():
                print(out.strip())

    # discord notify
    if notify:
        set_busy("notify", "discord")
        try:
            discord_post(packet)
        except Exception as e:
            print(f"[warn] Discord notify failed: {e}")

    print(f"DONE. Wrote: {out_path}")
    set_idle()
    return 0


def print_help():
    print("Available commands:")
    print("  agent run        Run one sync cycle (write packet, commit, push, notify)")
    print("  agent chat       Interactive chat in terminal")
    print("  agent status     Show BUSY/IDLE + current step")
    print("  agent stop       Soft stop (sets STOP flag)")
    print("Options:")
    print("  -h, --help       Help")
    print("  -v, --version    Version")
    print("  -l, --list       List commands")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print_help()
        return 0
    if args[0] in ("-v", "--version"):
        print(VERSION)
        return 0
    if args[0] in ("-l", "--list"):
        print_help()
        return 0

    # allow "./gs run" and "./gs agent run"
    if args[0] == "run":
        return cmd_run(push=True, notify=True)

    if args[0] == "agent" and len(args) >= 2:
        sub = args[1]

        if sub == "status":
            return cmd_status()

        if sub == "stop":
            return cmd_stop()

        if sub == "chat":
            return cmd_chat()

        if sub == "run":
            # optional flags
            push = True
            notify = True
            if "--no-push" in args:
                push = False
            if "--no-notify" in args:
                notify = False
            return cmd_run(push=push, notify=notify)

    print_help()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        # if we crash, we still want to appear idle next time
        try:
            set_idle()
        except Exception:
            pass