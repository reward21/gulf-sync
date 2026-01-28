#!/usr/bin/env python3
import os, sys, json, signal, subprocess
from datetime import datetime
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
CONTROL = ROOT / "control"
INBOX = ROOT / "inbox"
SYNC_PACKETS = ROOT / "sync" / "packets"
STATUS_DIR = ROOT / "status"

STATE_FILE = LOGS / "state.json"
LOCK_FILE = LOGS / "BUSY.lock"
STOP_FLAG = CONTROL / "STOP"

VERSION = "0.1.0"


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
    LOGS.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(f"{os.getpid()}\n{now_ct()}\n{step}\n{detail}\n")
    write_state("BUSY", step, detail)


def clear_busy():
    if LOCK_FILE.exists():
        LOCK_FILE.unlink()
    write_state("IDLE", "", "")


def is_stop_requested():
    return STOP_FLAG.exists()


# ---------- Ctrl-C soft/hard stop ----------
_interrupt_count = 0


def handle_sigint(signum, frame):
    global _interrupt_count
    _interrupt_count += 1
    if _interrupt_count == 1:
        CONTROL.mkdir(parents=True, exist_ok=True)
        STOP_FLAG.write_text(f"soft stop requested at {now_ct()}\n")
        print("\n[soft stop] STOP flag set. Finishing current step then exiting…")
    else:
        print("\n[hard stop] Forcing exit NOW.")
        os._exit(130)


# ---------- Ollama call ----------
def ollama_chat(prompt: str) -> str:
    base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
    url = f"{base}/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read().decode("utf-8")
    j = json.loads(body)
    return j.get("message", {}).get("content", "").strip()


# ---------- Git helpers ----------
def run_git(args):
    return subprocess.check_output(["git"] + args, cwd=str(ROOT)).decode("utf-8", errors="ignore").strip()


def git_has_changes():
    out = run_git(["status", "--porcelain"])
    return bool(out.strip())


def git_commit_and_push(message: str, push: bool):
    run_git(["add", "."])
    run_git(["commit", "-m", message])
    if push:
        run_git(["push"])


def changed_files_top(n=3):
    try:
        out = run_git(["show", "--name-only", "--pretty=format:"])
        files = [f for f in out.splitlines() if f.strip()]
        return files[:n]
    except Exception:
        return []


# ---------- Discord notify ----------
def discord_post(text: str):
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        return
    payload = json.dumps({"content": text}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def log_discord_error(e: Exception):
    err_path = ROOT / "logs" / "discord_errors.log"
    err_path.parent.mkdir(parents=True, exist_ok=True)
    with err_path.open("a") as f:
        f.write(f"{now_ct()} {repr(e)}\n")


# ---------- Core workflow ----------
def latest_inbox_entries(limit=3):
    INBOX.mkdir(parents=True, exist_ok=True)
    files = sorted([p for p in INBOX.glob("*.md") if p.name != "_template.md"], reverse=True)
    return files[:limit]


def build_sync_packet():
    SYNC_PACKETS.mkdir(parents=True, exist_ok=True)
    STATUS_DIR.mkdir(parents=True, exist_ok=True)

    inbox_files = latest_inbox_entries(limit=3)
    inbox_text = ""
    for p in inbox_files:
        inbox_text += f"\n\n---\nSOURCE: {p.name}\n---\n{p.read_text()}\n"

    prompt = f"""
You are a coordination agent for Cole. Create a short Sync Packet.

Return EXACTLY this structure:

### Sync Packet — {now_ct()}

**Top 3 changes (planned)**
- ...
- ...
- ...

**Next actions**
- ...
- ...
- ...

**Notes**
- ...

Use the inbox sources below. Be concise.

INBOX SOURCES:
{inbox_text}
""".strip()

    try:
        packet = ollama_chat(prompt)
        if not packet:
            raise RuntimeError("Empty response from model.")
    except Exception as e:
        packet = f"""### Sync Packet — {now_ct()}

**Top 3 changes (planned)**
- (Ollama unavailable) Review inbox files: {", ".join(p.name for p in inbox_files) or "none"}
- Generate sync packet once model is running
- Commit + push updates

**Next actions**
- Add quick log in inbox/
- Run agent again
- Verify Discord webhook is set

**Notes**
- Error: {e}
"""

    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_path = SYNC_PACKETS / f"{ts}_sync_packet.md"
    out_path.write_text(packet + "\n")

    (STATUS_DIR / "tech.md").write_text(packet + "\n")
    return out_path, packet


def cmd_run(push=True, notify=True):
    if LOCK_FILE.exists():
        print("Agent is BUSY. Run `./gs status`.")
        return 2

    set_busy("run", "generating sync packet")
    try:
        if is_stop_requested():
            print("STOP flag set. Exiting.")
            return 0

        out_path, packet = build_sync_packet()

        if is_stop_requested():
            print("STOP requested. Exiting before commit.")
            return 0

        if git_has_changes():
            msg = f"Sync packet update ({now_ct()})"
            set_busy("git", "committing changes")
            git_commit_and_push(msg, push=push)

        if notify:
            top = changed_files_top(3)
            top_lines = "\n".join([f"- {f}" for f in top]) if top else "- (no file list)"
            discord_text = f"""✅✅✅ **gulf-sync run complete** ({now_ct()})

🧠 **Top 3 changed files**
{top_lines}

🎯 **Next actions**
- Check latest sync packet in `sync/packets/`
- Add new quick log if needed
- Run `./gs chat` for follow-ups ✨
"""
            try:
                discord_post(discord_text)
            except Exception as e:
                log_discord_error(e)
                print(f"[warn] Discord notify failed: {e}")

        print(f"DONE. Wrote: {out_path}")
        return 0

    finally:
        # Clear STOP flag after a clean run
        if STOP_FLAG.exists():
            STOP_FLAG.unlink()
        clear_busy()


def cmd_chat():
    print("Local chat mode. Type /exit to quit.")
    while True:
        user = input("\nYou> ").strip()
        if user.lower() in ("/exit", "exit", "quit"):
            break
        set_busy("chat", "responding")
        try:
            resp = ollama_chat(user)
        except Exception as e:
            resp = f"(Ollama error) {e}"
        finally:
            clear_busy()
        print(f"\nAgent> {resp}")


def cmd_status():
    if STATE_FILE.exists():
        print(STATE_FILE.read_text())
    else:
        print(json.dumps({"status": "IDLE", "ts": now_ct()}, indent=2))


def cmd_stop():
    CONTROL.mkdir(parents=True, exist_ok=True)
    STOP_FLAG.write_text(f"stop requested at {now_ct()}\n")
    print("STOP flag created. Agent will stop at the next safe checkpoint.")


def cmd_list():
    print("""Available commands:
  agent run        Run one sync cycle (write packet, commit, push, notify)
  agent chat       Interactive chat in terminal
  agent status     Show BUSY/IDLE + current step
  agent stop       Soft stop (sets STOP flag)
Options:
  -h, --help       Help
  -v, --version    Version
  -l, --list       List commands
""")


def main():
    load_env()
    signal.signal(signal.SIGINT, handle_sigint)

    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        cmd_list()
        return 0
    if args[0] in ("-v", "--version"):
        print(VERSION)
        return 0
    if args[0] in ("-l", "--list"):
        cmd_list()
        return 0

    cmd = args[0]
    if cmd == "run":
        return cmd_run(push=True, notify=True)
    if cmd == "chat":
        cmd_chat()
        return 0
    if cmd == "status":
        cmd_status()
        return 0
    if cmd == "stop":
        cmd_stop()
        return 0

    print(f"Unknown command: {cmd}")
    cmd_list()
    return 2


if __name__ == "__main__":
    sys.exit(main())