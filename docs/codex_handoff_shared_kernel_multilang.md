# Codex Handoff — Shared live kernel + shared SQLite memory (multi-language kernels)

## Goal (do this now)
Update `agent.py` so **one running agent process** maintains:
1) a **single shared Jupyter kernel** (persistent state) for code execution, and  
2) the existing **shared SQLite memory** (`status/agent_memory.sqlite`) for chat memory.

**Important nuance:** Jupyter “terminal” is *not* a kernel. It’s a server feature.  
This agent already supports “terminal/shell” execution via `subprocess` (`/sh ...`) — we’ll keep that.  
The change requested here is: **make the Jupyter kernel selectable by language**, not Python-only.

So: **shared kernel state + shared SQLite memory**, and the kernel can be `python3`, `ir`, `bash`, etc **if those kernels are installed**.

---

## What the current code does (baseline)
In `agent.py`:
- Jupyter kernel manager/client globals start around **L44**.
- The “Jupyter-backed code interpreter” section begins around **L43**.
- `_ensure_kernel()` around **L76** starts a kernel via `jupyter_client.KernelManager()` (implicitly the default kernel, usually `python3`).
- `_execute_python()` around **L101** sends code to that kernel.
- `_run_shell()` around **L158** runs bash commands via `subprocess` (this is *not* Jupyter terminal; it’s OS shell).

Right now it’s basically: **Python kernel + OS shell**. There is no “choose kernel language” feature.

---

## Required change
### 1) Add “kernel name” configuration (shared across the agent process)
Add a global for the current kernel name, defaulting to `python3`:

- Add near the existing globals around **L44**:
  - `_KERNEL_NAME = os.environ.get("GS_KERNEL_NAME", "python3").strip()`
  - Track it alongside `_KERNEL_CWD`.

Also add an env var for the default:
- `GS_KERNEL_NAME=python3` (user can override in `.envrc` or shell)

### 2) Make `_ensure_kernel` aware of kernel language
Change signature and behavior:

**Before:**
- `def _ensure_kernel(cwd: Path):`
- Restart kernel if CWD changes.

**After:**
- `def _ensure_kernel(cwd: Path, kernel_name: str):`
- Restart kernel if **either** CWD changes **or** kernel_name changes.
- Construct kernel manager with a specific kernel:
  - `km = KernelManager(kernel_name=kernel_name)`

Pseudo-diff intent (not exact patch):
- Replace the existing `_ensure_kernel` around **L76** to:
  - accept `kernel_name`
  - compare `(cwd, kernel_name)` to cached values
  - call `_shutdown_kernel()` if mismatch
  - start kernel with `KernelManager(kernel_name=kernel_name)`

Add a cached `_KERNEL_NAME` and `_KERNEL_SPEC` (or just `_KERNEL_NAME`) so we know what’s currently running.

### 3) Generalize `_execute_python` into `_execute_kernel`
This is a naming clarity change (optional but recommended):
- Rename `_execute_python(code, ...)` → `_execute_kernel(code, ..., kernel_name=None)`
- Default: use current `_KERNEL_NAME`.

Behavior stays the same: send code, collect `stream/execute_result/display_data/error/status`.

**Note:** For non-Python kernels, output may show up mostly as `stream` messages. That’s fine.

### 4) Add commands to list/select kernels at runtime
Inside `cmd_chat()` around **L1007**, add:

- `/kernels` (or `/kernel list`)  
  Prints installed kernel names available on this machine.

Implementation options:
- Shell call: `jupyter kernelspec list --json`
- Or Python: `from jupyter_client.kernelspec import find_kernel_specs`

Example output: `python3`, `ir`, `bash`, `javascript`, etc.

- `/kernel set <name>`  
  Sets `_KERNEL_NAME = <name>`, calls `_shutdown_kernel()` so the next run starts the new kernel.
  Print confirmation.

- Update `/py ...` command
  Keep `/py` as “send code to the current kernel”, even if it isn’t Python.
  (You can rename it later to `/k`, but do not rename right now unless you update docs/help too.)

### 5) Update the auto-execution JSON schema to support kernel choice (minimal)
Right now the LLM decision schema supports:
- `{"action":"python","code":"...","cwd":"..."}`

Change “python” → “kernel” (or keep “python” but add a field):
- Keep existing `action:"python"` for backward compatibility, but allow:
  - `kernel_name`: optional string

So the agent can do:
- `kernel_name = decision.get("kernel_name") or _KERNEL_NAME`

**Important:** Do not force the LLM to guess kernel names.  
Instead:
- If it needs a non-default kernel, it should reply with an instruction like:
  “Run `/kernels` then `/kernel set <name>`.”
That keeps it reliable.

---

## What we are NOT doing (explicitly)
- We are **not** integrating the Jupyter *server* Terminal API (`/api/terminals`).  
  Your `/sh` already gives you terminal behavior and persistent shell CWD (`_SHELL_CWD`).
- We are **not** trying to share one kernel across *multiple separate processes* (two different terminal windows running two separate `./gs agent chat` processes).  
  That requires a shared external kernel/server connection design.

---

## Acceptance tests (Codex must run these)
1) Start chat:
   - `./gs agent chat`
2) List kernels:
   - `/kernels`
   - Should print installed kernel names (at minimum `python3`).
3) Python kernel persistence:
   - `/kernel set python3`
   - `/py x = 5`
   - `/py print(x)`
   - Expected: prints `5` (state persists in the shared kernel).
4) Switch kernel resets state:
   - `/kernel set python3` then `/py x=123`
   - `/kernel set python3` (same kernel name should **not** reset)
   - `/py print(x)` → `123`
   - `/kernel set <different_kernel>` → should reset
5) Shell still works:
   - `/sh pwd`
   - `/sh ls -la`

---

## Notes / constraints
- This requires `jupyter_client` installed in the Python that runs `./gs`.
- Non-Python kernels require their kernelspecs installed on the machine.
- If a kernel name is invalid, print a friendly error and suggest `/kernels`.

---

## Deliverables
- Updated `agent.py` implementing the above.
- Update the help text (printed in `cmd_chat` banner) to include `/kernels` and `/kernel set`.
