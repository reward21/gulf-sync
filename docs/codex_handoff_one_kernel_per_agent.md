# Codex Handoff — One Jupyter Kernel Per Agent (Choice A)

**Target file:** `/Users/cole/Projects/gulfchain/gulf-sync/agent/agent.py`

**Goal:** Replace the current **single shared Jupyter kernel** with a **kernel pool keyed by `agent_key`**, so each agent/thread gets an isolated Python runtime (imports, variables, state).

---

## Constraints

- Keep behavior identical by default: if no key is provided, use `"default"`.
- No new external dependencies beyond existing `jupyter_client`.
- Must not break non-kernel paths (shell execution, routing, etc.).
- Add safe cleanup so kernels are shut down on process exit.
- Keep the changes minimal and readable.

---

## Summary of Changes

1. Replace single-kernel globals with a dict `_KERNELS` keyed by `agent_key`.
2. Update `_shutdown_kernel()` to support shutdown by key **or** shutdown all.
3. Update `_ensure_kernel()` to be per-key.
4. Update `_execute_python()` to accept `agent_key`.
5. Wire `agent_key` into `cmd_chat()` so each chat process has its own kernel.
6. Shutdown all kernels on process exit.

---

## 1) Replace the “single kernel globals” with a kernel pool

### Find this block (near the top)
It starts at:

`# ---------- jupyter-backed code interpreter (optional) ----------`

And currently defines:

- `_KERNEL_MGR = None`
- `_KERNEL_CLIENT = None`
- `_KERNEL_CWD = None`

### Replace that whole kernel-global section with:

```python
# ---------- jupyter-backed code interpreter (optional) ----------
# Choice A: one kernel per agent_key (isolated runtime/state per agent)
_KERNELS = {}  # agent_key -> {"km": KernelManager, "kc": KernelClient, "cwd": Path}

_SHELL_CWD = None
AUTO_PY_DEFAULT = os.environ.get("GS_AUTO_PY", "false").lower() == "true"
AUTO_SH_DEFAULT = os.environ.get("GS_AUTO_SH", "false").lower() == "true"
DEFAULT_KERNEL_KEY = os.environ.get("GS_KERNEL_KEY", "default").strip() or "default"
```

> Keep `_SHELL_CWD`, AUTO flags, etc. intact—just re-home them after this new section if needed.

---

## 2) Update `_shutdown_kernel` to support per-key shutdown (and shutdown all)

### Find current `_shutdown_kernel()` (no args)
It currently clears the single global kernel variables.

### Replace it with:

```python
def _shutdown_kernel(agent_key: str | None = None):
    """
    Shutdown kernels.
    - agent_key=None => shutdown ALL kernels
    - agent_key="x"  => shutdown only that kernel
    """
    global _KERNELS
    try:
        if agent_key is None:
            keys = list(_KERNELS.keys())
        else:
            keys = [agent_key] if agent_key in _KERNELS else []

        for k in keys:
            entry = _KERNELS.get(k) or {}
            kc = entry.get("kc")
            km = entry.get("km")

            try:
                if kc:
                    kc.stop_channels()
            except Exception:
                pass

            try:
                if km:
                    km.shutdown_kernel(now=True)
            except Exception:
                pass

            _KERNELS.pop(k, None)
    except Exception:
        # last-resort safety: don't crash shutdown path
        pass
```

---

## 3) Update `_ensure_kernel` to be per-agent

### Find current `_ensure_kernel(cwd: Path)`
It checks the single global and (re)starts one kernel.

### Replace it with `_ensure_kernel(cwd, agent_key)`:

```python
def _ensure_kernel(cwd: Path, agent_key: str | None = None):
    agent_key = (agent_key or DEFAULT_KERNEL_KEY).strip() or "default"

    entry = _KERNELS.get(agent_key)
    if entry and entry.get("cwd") == cwd and entry.get("kc"):
        return entry["kc"]

    # restart only this agent_key kernel
    _shutdown_kernel(agent_key)

    try:
        from jupyter_client import KernelManager
    except Exception as e:
        raise RuntimeError(
            "jupyter_client is not available for this Python. "
            "Install it in the interpreter used by ./gs (e.g., `pip install jupyter_client`)."
        ) from e

    km = KernelManager()
    km.start_kernel(cwd=str(cwd))
    kc = km.client()
    kc.start_channels()

    _KERNELS[agent_key] = {"km": km, "kc": kc, "cwd": cwd}
    return kc
```

---

## 4) Update `_execute_python` to accept `agent_key`

### Find `_execute_python(...)`
Current signature:

```python
def _execute_python(code: str, cwd: Path = None, timeout_s: int = 20) -> dict:
```

### Change signature to:

```python
def _execute_python(code: str, cwd: Path = None, timeout_s: int = 20, agent_key: str | None = None) -> dict:
```

### Change kernel acquisition line from:

```python
kc = _ensure_kernel(cwd)
```

to:

```python
kc = _ensure_kernel(cwd, agent_key=agent_key)
```

Everything else in `_execute_python` stays the same.

---

## 5) Wire the key into `cmd_chat` (so chat has its own kernel)

### In `cmd_chat()` (near the top of the function)
Right after `load_env()`, add:

```python
kernel_key = f"chat:{os.getpid()}"
```

This gives each chat process its own persistent kernel.

### Update `/py reset` handler
Currently it calls:

```python
_shutdown_kernel()
```

Change to:

```python
_shutdown_kernel(kernel_key)
```

### Update *all* `_execute_python(...)` calls inside `cmd_chat`
Change each:

```python
result = _execute_python(code)
```

to:

```python
result = _execute_python(code, agent_key=kernel_key)
```

And any call that passes `cwd=run_cwd` becomes:

```python
result = _execute_python(code, cwd=run_cwd, agent_key=kernel_key)
```

---

## 6) Add shutdown on process exit

### At the bottom: `if __name__ == "__main__":`
In the `finally:` block, add kernel shutdown before `set_idle()`:

```python
    finally:
        try:
            _shutdown_kernel(None)  # shutdown ALL kernels
        except Exception:
            pass
        # if we crash, we still want to appear idle next time
        try:
            set_idle()
        except Exception:
            pass
```

---

## Acceptance Checks

1. Start chat: `./gs agent chat`
2. Run: `/py x=123; print(x)` → prints `123`
3. Run: `/py print(x)` → still prints `123` (kernel state persists in that chat agent)
4. In another terminal, start a second chat process and run `/py print('hello')` → should be isolated from first chat’s variables.
5. `/py reset` inside chat resets only that chat’s kernel.
6. Exiting the process does not leave kernels running.

---

## Optional Follow-Up (Not required for this change)

This design supports **true per-thread kernels** later by passing explicit keys such as:

- `agent_key="risk_gate"`
- `agent_key=f"handle:{thread}"`

Wherever you later add Python execution outside chat.
