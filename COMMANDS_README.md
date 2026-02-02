# gulf-sync — Commands Reference

This is the **single commands doc** for `gulf-sync` (run everything from the repo root).

---

## Help / discovery

```bash
./gs --help
./gs --list
./gs --version
```

---

## Sync runner (the “one cycle” loop)

```bash
./gs agent run
```
Run **one** sync cycle (read inbox → write packet → update outbox → optionally commit/push/notify).

```bash
./gs agent status
```
Show `BUSY/IDLE` + current step.

```bash
./gs agent stop
```
Soft stop (creates `control/STOP` so the runner exits cleanly).

---

## Local chat (Ollama)

```bash
./gs agent chat
```
Interactive terminal chat using your local Ollama server.

Notes:
- The chat is **local/offline**.
- It has **no file access** unless you paste content in.
- It prints the active model on replies.
- It won’t crash on Ollama HTTP errors (it prints the error and keeps going).

### In-chat shortcuts

```text
/model
/model set <name>
```

---

## Model (Ollama) commands

```bash
./gs model
```
Show the current model + list installed models.

```bash
./gs model list
```
List installed models (via Ollama `/api/tags`).

```bash
./gs model set <model>
```
Set `OLLAMA_MODEL` in `.env`.

```bash
./gs model url
```
Show the current Ollama URL setting.

```bash
./gs model set-url <url>
```
Set `OLLAMA_URL` in `.env`.

### Example

```bash
./gs model
./gs model set llama3.1:8b
./gs model url
./gs model set-url http://127.0.0.1:11434/api/generate
```

---

## Quick sanity test

```bash
python3 -m py_compile agent/agent.py && echo "✅ syntax OK"
./gs model
./gs agent chat
```

