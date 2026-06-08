# Troubleshooting

**English** | [中文](troubleshooting.zh-CN.md)

A log of the main problems hit during development, their root causes, and fixes.

---

## 1. hatchling packaging failure

**Stage**: environment setup

**Error**:
```
ValueError: Unable to determine which files to ship inside the wheel
The most likely cause: no directory matches the name of your project (localnow_backend)
```

**Root cause**: hatchling needs a valid Python package directory to work. We created directories but no `__init__.py`, so Python didn't treat them as packages.

**Fix**:
1. Add an empty `__init__.py` to each subdirectory
2. Declare package paths in `pyproject.toml`:
```toml
[tool.hatch.build.targets.wheel]
packages = ["agent", "api", "tools", "llm", "models", "prompts"]
```

**Lesson**: Python recognizes a "package" by the presence of `__init__.py`, even an empty one.

---

## 2. Indentation error with multi-line terminal commands

**Stage**: environment verification

**Error**:
```
IndentationError: unexpected indent
```

**Root cause**: running multi-line code via `python -c "..."` and pasting indented code makes the indentation get parsed as Python syntax.

**Fix**: use heredoc instead:
```bash
uv run python - <<'EOF'
from config import config
print(config.llm_provider)
EOF
```

---

## 3. API key leak

**Stage**: environment setup

**Problem**: pasted `.env` content containing a real API key into a chat window, exposing the key.

**Root cause**: chat content may be logged; once a key appears in a non-secure context it must be treated as leaked.

**Fix**:
1. Immediately revoke the leaked key in the provider console
2. Generate a replacement
3. Ensure `.env` is in `.gitignore` and never committed

**Lesson**: API keys should only ever live in `.env` — never in code, screenshots, chats, or logs.

---

## 4. Inline comments in .env breaking config reads

**Stage**: environment setup

**Problem**:
```bash
LLM_PROVIDER=anthropic  # anthropic | openai | deepseek | ollama
```
Different `python-dotenv` versions handle inline comments inconsistently and may read the value with the comment attached.

**Fix**: put comments on their own line:
```bash
# LLM provider: anthropic | openai | deepseek | ollama
LLM_PROVIDER=anthropic
```

---

## 5. Anthropic API out of credit

**Stage**: data generation

**Error**:
```
anthropic.BadRequestError: 400 - Your credit balance is too low
```

**Root cause**: zero account balance, API calls rejected.

**Fix**: data generation is a one-off task, so we switched to a local Ollama model (qwen3:8b):
- Ollama is free, no API key needed
- It exposes an OpenAI-compatible endpoint (`http://localhost:11434/v1`), so code changes are minimal
- qwen3:8b has good Chinese quality, sufficient for data generation

**Lesson**: design fallback paths into the toolchain. Our multi-provider LLM Factory exists precisely so we can switch quickly when one provider is unavailable.

---

## 6. Ollama connection refused

**Stage**: data generation

**Error**:
```
httpx.ConnectError: [Errno 111] Connection refused
```

**Root cause**: under WSL2, Ollama doesn't auto-start as a background service — it must be started manually (or wasn't installed yet).

**Fix**:
```bash
# install (use the official script on WSL2, not snap)
curl -fsSL https://ollama.com/install.sh | sh

# start the service (restart needed after a WSL restart)
ollama serve

# verify
ollama list
```

**Lesson**: WSL2 has no systemd, so some services can't auto-start and need manual management; `snap install` is unreliable on WSL2 — use the official installer.

---

## 7. generate.py can't find .env

**Stage**: data generation

**Error**:
```
TypeError: Could not resolve authentication method. Expected one of api_key...
```

**Root cause**: `generate.py` is in the `data/` subdirectory; `load_dotenv()` looks for `.env` in the current directory, but `.env` is one level up in `backend/`.

**Fix**: specify the `.env` path explicitly:
```python
load_dotenv(Path(__file__).parent.parent / ".env")
```

**Lesson**: scripts run from subdirectories should read config via a path relative to the script's location, not the current working directory.

---

## 8. LLM JSON output truncated

**Stage**: data generation

**Error**:
```
json.decoder.JSONDecodeError: Expecting ',' delimiter: line 1 column 6870
```

**Root cause**: `max_tokens=4096` couldn't hold the full JSON for 42 restaurants (≈8400 tokens). The model was cut off mid-output, leaving an incomplete array.

**Fix**: generate in batches of ≤15, keeping each output under ~3000 tokens:
```python
def generate(prompt, label, total, batch_size=15):
    results = []
    batches = (total + batch_size - 1) // batch_size
    for i in range(batches):
        current = min(batch_size, total - len(results))
        batch = generate_batch(prompt, current)  # with retry
        results.extend(batch)
    return results
```
Each batch is independent and retries up to 3 times without affecting others.

**Lesson**: when generating large structured data, keep each generation under ~60% of the output token budget to leave room for stray explanatory text. Batching is the standard way to handle local-model output limits.

---

## 9. Evaluation summary inconsistent with actual results

**Stage**: data evaluation

**Problem**: the eval script printed "structure failures = 0" while one venue record actually failed validation. The final summary was hard-coded static text that didn't read the actual results.

**Fix**: each eval function returns a failure count; `main()` prints conclusions based on the real numbers:
```python
r_errors = evaluate_restaurants(restaurants)
v_errors = evaluate_venues(venues)
total_errors = r_errors + v_errors
print("✓ all passed" if total_errors == 0 else f"✗ found {total_errors} issues")
```

**Lesson**: an eval script's conclusions must be computed by code, not hard-coded — otherwise it isn't really evaluating anything.

---

## 10. Batched generation causing duplicate IDs

**Stage**: data generation

**Problem**: generating 15 restaurants per batch over 3 batches, each batch started numbering from `rg001`, producing many duplicate IDs after merging. Duplicate IDs overwrite entries when indexed, leaving fewer records than expected.

**Fix**: reassign IDs uniformly after merging all batches:
```python
def reassign_ids(data: list[dict], prefix: str) -> list[dict]:
    for i, item in enumerate(data):
        item["id"] = f"{prefix}{i + 1:03d}"
    return data
```

**Lesson**: don't trust LLM-generated IDs; any field that must be globally unique should be generated and managed in code.

---

## 11. SSE connection timing out during generate_plans

**Stage**: frontend/backend integration

**Symptom**: after the frontend showed "searching nearby venues and restaurants…", it waited several minutes then showed "connection error"; the agent never pushed subsequent node progress.

**Root cause**: `graph.astream()` only yields a chunk after a node finishes. `generate_plans` calling local Ollama (qwen3:8b) to produce structured JSON took 5–15 minutes. If the LLM's HTTP call blocked the asyncio event loop, sse-starlette's ping heartbeat couldn't fire, and the TCP connection was dropped by the browser as a timeout. The frontend `EventSource` fired `error`, and our code closed the connection and reported an error.

**Fix**: decouple graph execution from the SSE generator with an `asyncio.Queue`:
- the graph runs in a separate `asyncio.create_task`, pushing a chunk to the queue after each node
- the SSE generator polls the queue every 5s; on empty it emits a `heartbeat` event to keep the connection alive
- the frontend registers a `heartbeat` listener and ignores it

**Files**: `api/routes.py` (backend), `app/page.tsx` (frontend)

**Lesson**: in a long-lived SSE connection, if the server has a long-running operation the heartbeat must fire independently of business logic. Putting the slow task on an `asyncio.Queue` and consuming it asynchronously is the standard pattern.
