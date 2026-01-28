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

STATE_FILE = LOGS / "state.json"
LOCK_FILE = LOGS / "BUSY.lock"
STOP_FLAG = CONTROL / "STOP"

LAST_INBOX_SIG_FILE = STATUS_DIR / "last_inbox_sig.txt"
LAST_PACKET_PATH_FILE = STATUS_DIR / "last_packet_path.txt"

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
        # IMPORTANT: override any shell-exported env vars so .env wins
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


def soft_stop():
    CONTROL.mkdir(parents=True, exist_ok=True)
    STOP_FLAG.write_text(now_ct() + "\n")


def hard_stop():
    # forceful: remove lock, remove stop
    if LOCK_FILE.exists():
        LOCK_FILE.unlink()
    if STOP_FLAG.exists():
        STOP_FLAG.unlink()
    write_state("IDLE", "", "")


def run(cmd, check=True):
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def git_has_changes():
    r = run(["git", "status", "--porcelain"], check=False)
    return bool(r.stdout.strip())


def git_commit_and_push(message, push=True):
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", message])
    if push:
        run(["git", "push"])


def changed_files_top(n=3):
    # shows top N changed files by a stable heuristic (hash prefix of name)
    # avoids needing a full diff parse for MVP
    r = run(["git", "diff", "--name-only", "HEAD~1..HEAD"], check=False)
    files = [x.strip() for x in r.stdout.splitlines() if x.strip()]
    if not files:
        # fall back to staged/working files if no last commit diff
        r2 = run(["git", "status", "--porcelain"], check=False)
        files = [ln[3:] for ln in r2.stdout.splitlines() if len(ln) > 3]
    def score(name):
        return int(hashlib.sha256(name.encode()).hexdigest()[:8], 16)
    files = sorted(set(files), key=score, reverse=True)
    return files[:n]


def discord_post(text):
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        return

    payload = json.dumps({"content": text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            _ = resp.read()
            return
    except Exception:
        # fallback: curl (sometimes more tolerant of SSL/weird python env issues)
        try:
            subprocess.run(
                ["curl", "-sS", "-H", "Content-Type: application/json", "-d", json.dumps({"content": text}), url],
                check=False,
            )
        except Exception:
            raise


def ollama_chat(prompt, model="llama3.1:8b"):
    # Ollama REST API default
    url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        j = json.loads(resp.read().decode("utf-8"))
    return j["message"]["content"]


def read_file_safe(p: Path, max_bytes=200_000):
    data = p.read_bytes()
    if len(data) > max_bytes:
        data = data[:max_bytes]
    try:
        return data.decode("utf-8")
    except Exception:
        return data.decode("utf-8", errors="ignore")


def latest_inbox_entries(limit=3):
    INBOX.mkdir(parents=True, exist_ok=True)
    files = sorted([p for p in INBOX.glob("*.md")], key=lambda x: x.name, reverse=True)
    return files[:limit]


def inbox_signature(files):
    """Stable signature of the current inbox inputs (names + contents)."""
    h = hashlib.sha256()
    for p in sorted(files, key=lambda x: x.name):
        h.update(p.name.encode('utf-8'))
        h.update(b'\n')
        try:
            h.update(p.read_bytes())
        except Exception:
            h.update(p.read_text(errors='ignore').encode('utf-8'))
        h.update(b'\n---\n')
    return h.hexdigest()


def build_sync_packet():
    load_env()

    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    SYNC_PACKETS.mkdir(parents=True, exist_ok=True)

    inbox_files = latest_inbox_entries(limit=3)
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
        inbox_text += f"\n\n---\nSOURCE: {p.name}\n---\n{p.read_text()}\n"

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
        files = changed_files_top(3)
        packet = (
            f"✅✅✅ gulf-sync run complete ({now_ct()})\n\n"
            f"🧠 Top 3 changed files\n"
            + "\n".join([f"- {f}" for f in files]) + "\n\n"
            "🎯 Next actions\n"
            "- Check latest sync packet in `sync/packets/`\n"
            "- Add new quick log if needed\n"
            "- Run `./gs chat` for follow-ups ✨\n"
        )

    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    out_path = SYNC_PACKETS / f"{ts}_sync_packet.md"
    out_path.write_text(packet + "\n")

    (STATUS_DIR / "tech.md").write_text(packet + "\n")
    # Persist last-run markers so repeat runs don't spam commits/notifications.
    LAST_INBOX_SIG_FILE.write_text(sig + "\n")
    try:
        rel = out_path.relative_to(ROOT)
        LAST_PACKET_PATH_FILE.write_text(str(rel) + "\n")
    except Exception:
        LAST_PACKET_PATH_FILE.write_text(str(out_path) + "\n")

    return out_path, packet, True


def cmd_status():
    load_env()
    if STATE_FILE.exists():
        print(STATE_FILE.read_text())
    else:
        print(json.dumps({"status": "IDLE", "step": "", "detail": "", "ts": now_ct(), "pid": None}, indent=2))


def cmd_run(push=True, notify=True):
    load_env()
    if LOCK_FILE.exists():
        print("Agent is BUSY. Run `./gs status`.")
        return 2

    set_busy("run", "generating sync packet")
    try:
        if is_stop_requested():
            print("STOP flag set. Exiting.")
            return 0

        out_path, packet, changed = build_sync_packet()

        if not changed:
            print(f"No new inbox changes. Reused: {out_path}")
            return 0

        if is_stop_requested():
            print("STOP requested. Exiting before commit.")
            return 0

        if git_has_changes():
            msg = f"Sync packet update ({now_ct()})"
            set_busy("git", "committing changes")
            git_commit_and_push(msg, push=push)

        if notify:
            set_busy("notify", "posting to discord")
            files = changed_files_top(3)
            discord_text = packet.strip()

            # ensure top 3 changed files are present in message (in case model didn't include them)
            if "Top 3" not in discord_text:
                discord_text += "\n\n🧠 Top 3 changed files\n" + "\n".join([f"- {f}" for f in files])
                discord_text += "\n\n🎯 Next actions\n- Check latest sync packet in `sync/packets/`\n- Run `./gs chat` ✨\n"

            try:
                discord_post(discord_text)
            except Exception as e:
                print(f"[warn] Discord notify failed: {e}")

        print(f"DONE. Wrote: {out_path}")
        return 0
    finally:
        clear_busy()
        # clear STOP flag after a run attempt (MVP choice)
        if STOP_FLAG.exists():
            STOP_FLAG.unlink()


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


def cmd_stop():
    soft_stop()
    print("STOP flag set (soft stop).")
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


def main():
    if len(sys.argv) == 1:
        usage()
        return 0

    if sys.argv[1] in ("-h", "--help"):
        usage()
        return 0
    if sys.argv[1] in ("-v", "--version"):
        print(VERSION)
        return 0
    if sys.argv[1] in ("-l", "--list"):
        usage()
        return 0

    if sys.argv[1] != "agent":
        usage()
        return 2

    if len(sys.argv) < 3:
        usage()
        return 2

    cmd = sys.argv[2]
    if cmd == "run":
        return cmd_run(push=True, notify=True)
    if cmd == "chat":
        return cmd_chat()
    if cmd == "status":
        return cmd_status() or 0
    if cmd == "stop":
        return cmd_stop()

    usage()
    return 2


if __name__ == "__main__":
    sys.exit(main())