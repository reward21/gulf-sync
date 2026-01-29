# gulf-sync — Model command + safer chat

This patch adds a top-level `./gs model` command and makes `./gs agent chat`:
- print the model on every reply
- support `/model` and `/model set <name>` inside chat
- stop crashing on Ollama HTTP errors (it will show an error and keep going)
- use a system prompt that correctly states it's **local/offline** and has **no file access** unless you paste content

## New commands

```bash
./gs model            # show current model + list installed models
./gs model list       # list installed models
./gs model set llama3.1:8b
./gs model url        # show Ollama URL settings
./gs model set-url http://127.0.0.1:11434/api/generate
```

## In-chat shortcuts

```text
/model
/model set llama3.1:8b
```

## Quick sanity test

```bash
python3 -m py_compile agent/agent.py && echo "✅ syntax OK"
./gs model
./gs agent chat
```
