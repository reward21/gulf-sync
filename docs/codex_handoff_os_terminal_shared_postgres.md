# Codex Handoff — OS Terminal “Kernel” (shared session) + Postgres Agent Memory

## Goal
Update the current `agent.py` so that:

1) **Code execution uses a shared, persistent OS-level terminal session** (one long-lived shell per running agent process).  
2) **Agent memory uses Postgres** (a dedicated DB just for agent memory), not SQLite.  
3) The agent can run **any language/tool available on the OS** via shell (python, node, git, etc.) using natural-language → command translation already in `cmd_chat`.

This should work without starting JupyterLab, without Jupyter kernels, and without requiring Cole to manually type terminal commands beyond launching `./gs agent chat`.

---

## Non-negotiables / constraints
- **Shared live terminal session**: state persists inside the running process (cwd, env exports, shell history/aliases if you choose).
- **No Jupyter dependency**: remove/disable `jupyter_client` usage entirely.
- **Postgres is the memory source of truth** for `mem_add`, `mem_recent`, `mem_clear`, `mem_format`.
- Keep behavior **safe**: block obviously dangerous shell commands unless explicitly confirmed (optional but recommended; see Safety Gate).

---

## Files to edit
- `agent/agent.py` (this file)

---

## Part A — Replace Jupyter kernel execution with a shared OS terminal session

### A1) Delete / retire the Jupyter kernel implementation
In `agent.py`, remove (or fully disable) the Jupyter-backed section:

- Globals: `_KERNEL_MGR`, `_KERNEL_CLIENT`, `_KERNEL_CWD`
- Functions: `_shutdown_kernel()`, `_ensure_kernel()`, `_execute_python()`
- Any `/py reset` references that call `_shutdown_kernel()`

We will keep `/py ...` as a command, but it will run **through the shared shell session** instead.

### A2) Add a shared terminal session (“OS kernel”) implementation
Add a **single** global terminal session that persists across all chat interactions within the process.

Add these imports near the top:
- `import pty, select, fcntl, termios, tty`
(If you want minimal imports, you can do just `pty, select` plus basic os/time.)

Add new globals:
- `_TERM_PROC = None`
- `_TERM_FD = None`
- `_TERM_LOCK = False` (simple lock; a real threading.Lock is fine too)
- `_TERM_CWD = None` (optional; the shell maintains cwd, but we can track it)

Implement these functions:

#### `_term_start(cwd: Path) -> None`
- Start a persistent interactive bash:
  - `pty.fork()` then in child `os.execvp("bash", ["bash", "--noprofile", "--norc", "-i"])`
  - Set `os.chdir(str(cwd))` before exec.
- In parent, store the master FD in `_TERM_FD`.
- Configure the shell for easier parsing:
  - Send: `export PS1=""; export PROMPT_COMMAND=""; stty -echo`
  - (If `stty -echo` causes issues, omit and just parse markers.)

#### `_term_stop() -> None`
- If fd exists, send `exit` and close FD.
- Reset globals.

#### `_term_ensure(cwd: Path) -> None`
- Start the session if not started.
- If started and you want to “cd” to a new cwd, run `cd <cwd>` in-session (optional).
- Default cwd for first boot should be **Cole’s chosen root**:
  - Use `JUPYTER_ROOT` env as the terminal “root” too (or rename to `GS_ROOT` but keep compatibility).
  - If unset, default to `Path.home()`.

#### `_term_run(cmd: str, timeout_s: int = 20) -> dict`
- Execute `cmd` inside the persistent shell and capture stdout/stderr-ish output.
- Use an end-marker strategy:
  - Generate marker: `marker = "__GS_END__" + uuid_or_timehash`
  - Wrap command as:
    - `cmd_wrapped = f"{cmd}\nRC=$?\necho {marker} $RC\n"`
  - Write to FD.
  - Read from FD until marker line appears or timeout.
  - Return:
    ```json
    {"cwd":"<best-effort>", "stdout":"...", "stderr":"", "returncode": <int>}
    ```
  - Note: with a pty, stderr is usually merged into stdout; that’s fine for MVP.

**Important**: Keep the existing `_normalize_cwd()` logic and reuse it when changing cwd.

### A3) Update `_run_shell()` to use the shared terminal session
Replace current `_run_shell()` implementation (which uses `subprocess.run`) with:

- Determine cwd:
  - `cwd = (cwd or _SHELL_CWD or _py_root_dir()).resolve()`
- Call `_term_ensure(cwd)`
- Call `_term_run(cmd, timeout_s=timeout_s)`
- If cmd is a clean `cd <dir>` (no `&&`/`;`), keep the current behavior:
  - Validate with `_normalize_cwd`
  - Update `_SHELL_CWD`
  - Also run `cd` in the terminal session so the shared shell actually changes cwd

### A4) Re-implement `_execute_python()` as “python via shared shell”
We still want `/py` and auto-python to work. But it will run as a command in the shell:

Implement `_execute_python(code: str, cwd: Path=None, timeout_s: int=20) -> dict` as:

- Resolve cwd same way as `_run_shell`
- Build a heredoc:
  - `cmd = "python3 - <<'PY'\n" + code + "\nPY"`
- Run: `res = _run_shell(cmd, cwd=cwd, timeout_s=timeout_s)`
- Return a structure matching the old callers:
  ```python
  return {
    "cwd": res["cwd"],
    "stdout": res.get("stdout",""),
    "stderr": res.get("stderr",""),
    "result": "",
    "display": "",
  }
  ```

This keeps the rest of the agent logic intact without Jupyter.

### A5) Update chat commands that referenced the kernel
In `cmd_chat()`:
- `/py reset` should call `_term_stop()` (and maybe restart on next command), not `_shutdown_kernel()`.
- `/cwd <path>` should:
  - set `os.environ["JUPYTER_ROOT"]` (keep name for compatibility),
  - set `_SHELL_CWD`,
  - and run `cd` inside the terminal session (or `_term_stop()` so next run starts in the new cwd).

---

## Part B — Replace SQLite memory with Postgres memory

### B1) New env var: Postgres DSN
Add env support for:
- `GS_PG_DSN` (preferred)
  - example: `postgresql://cole:password@127.0.0.1:5432/gs_agents`
- Fallback to standard libpq env vars if DSN missing:
  - `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`

### B2) Add Postgres connector
Use **psycopg (v3)** if available; fallback to `psycopg2` if that’s what’s installed.

At top-level imports (near others), do NOT hard-fail on import. Instead:

- Try:
  - `import psycopg`
- Else try:
  - `import psycopg2 as psycopg`
- If neither exists:
  - Raise a clear RuntimeError when memory functions are called:
    - “Postgres driver missing. Install `psycopg[binary]`…”

### B3) Create table if missing (same schema)
Replace `_mem_connect()` to connect to Postgres instead of sqlite:

- Connect with DSN / env.
- Ensure table exists:
  ```sql
  CREATE TABLE IF NOT EXISTS gs_agent_memory (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    role TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL
  );
  ```
- You can optionally put it in a schema (env `GS_PG_SCHEMA`, default `public`).

### B4) Update memory ops
Rewrite:
- `mem_add()`: INSERT row, truncate at `MEMORY_MAX_CHARS`.
- `mem_recent(limit)`: SELECT order by id desc limit, then reverse in python.
- `mem_clear()`: TRUNCATE or DELETE.

Keep `mem_format()` unchanged (it calls mem_recent).

---

## Part C — Safety Gate (small but important)
Because this is now a real OS shell with persistence, add a basic guard before executing shell commands generated by the LLM:

Implement a simple denylist check inside the auto-shell execution path (and optionally for `/sh` too):
- Block commands containing:
  - `rm -rf /`, `:(){:|:&};:`, `mkfs`, `dd if=`, `shutdown`, `reboot`, `sudo`, `kill -9 1`, etc.
- If detected, respond:
  - “Blocked dangerous command. If you really want this, run it manually.”

This prevents accidental nukes from a hallucinated command.

---

## Part D — What Cole will do outside code (one-time setup)
Cole will create a dedicated Postgres DB for agent memory. You don’t need to code this, but the agent must support it.

Example (FYI only):
- Create DB: `createdb gs_agents`
- Create user if needed, grant, etc.
- Set env var in `.envrc` or `.env`:
  - `export GS_PG_DSN="postgresql://.../gs_agents"`

---

## Acceptance tests
After changes:

1) `./gs agent chat`
2) Run:
   - `/sh pwd` then `/sh cd ~/Projects` then `/sh pwd`
   - Open a *second* `./gs agent chat` in another terminal:
     - **They will NOT share state across processes.**
     - They WILL share state inside the same running process instance.
3) `/py print("hi")` prints `hi`.
4) `mem_add()` + `mem_recent()` work and write into Postgres table `gs_agent_memory`.

---

## Important note about “two chats”
If Cole opens **two separate terminal windows** each running `./gs agent chat`, those are **two separate processes** and cannot share a live shell session without adding a daemon/server. That’s expected.  
This patch delivers: **shared session within one running agent process** (the thing you asked for to start).

(Do NOT add a server/daemon in this patch.)

---

## Deliverable
Submit a single PR that:
- Removes Jupyter kernel code paths
- Adds persistent pty-backed shell session
- Switches memory backend to Postgres
- Keeps existing command UX (`/sh`, `/py`, `/auto ...`) working
