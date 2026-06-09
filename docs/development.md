# LocalNow — Development

**English** | [中文](development.zh-CN.md)

Notes on each module's implementation, key decisions, and gotchas.

> **Note** — this is a chronological build log. The retrieval layer was rebuilt from RAG/ChromaDB to a direct maps API (see Step 9); the original RAG modules have since been **removed**. For the current data flow, see [architecture.md](architecture.md) and [design.md](design.md).

---

## Step 1: Project skeleton & environment

### Directory structure

```
LocalNow/
├── backend/
│   ├── agent/      # LangGraph state graph and nodes
│   ├── tools/      # tools (search / validate / execute / notify)
│   ├── llm/        # LLM factory (multi-provider switch)
│   ├── models/     # Pydantic data models
│   ├── data/       # mock data and generation scripts
│   ├── prompts/    # prompt templates
│   ├── api/        # FastAPI entry
│   └── config.py   # global config (reads .env)
├── frontend/       # Next.js frontend
└── docs/           # docs
```

### Package management: uv

Chose uv over pip/poetry: by Astral, 10–100× faster dependency resolution/install than pip, more reliable lockfile, and the de-facto new standard for the Python toolchain in 2024.

```bash
uv sync          # install all dependencies
uv run python x  # run inside the virtualenv
```

### Frontend: Next.js + shadcn/ui

```bash
npx create-next-app@latest frontend  # TypeScript + Tailwind + App Router
npx shadcn@latest init               # prebuilt UI component library
```

shadcn/ui provides ready-made Card, Dialog, Progress, etc., avoiding time spent on basic styling.

### Key config

Each subdirectory needs an `__init__.py` to be recognized as a Python package. `pyproject.toml` must declare package paths:

```toml
[tool.hatch.build.targets.wheel]
packages = ["agent", "api", "tools", "llm", "models", "prompts"]
```

---

## Step 2: Pydantic data models

### Three core files

| File | Contents |
|------|----------|
| `config.py` | reads .env, global singleton `config` object |
| `models/schemas.py` | all business data models |
| `agent/state.py` | LangGraph AgentState |

### Model design

**schemas.py** defines the system's data contract in layers:

```
Enum     Scenario / ActivityCategory / ToolErrorCode, etc.
Geo      Coordinates
Entity   Venue / Restaurant
Constraint  ConstraintSet (structured constraints extracted from NL)
Plan     Plan / TimelineItem (agent-generated plans)
Execution   BookingResult / ToolError
API      UserRequest / SessionResponse (for FastAPI)
```

**agent/state.py** — `Annotated` + reducer is LangGraph-specific:

```python
# operator.add = append semantics (new value appended, not overwritten)
candidate_plans: Annotated[list[Plan], operator.add]
booking_results: Annotated[list[BookingResult], operator.add]

# no Annotated = overwrite semantics (new value replaces old)
selected_plan: Plan | None
user_confirmed: bool
```

On replan the old plans aren't lost — full history is kept for debugging.

### constraint_coverage field

The `Plan` model includes `constraint_coverage: dict[str, bool]`, asking the LLM to self-declare whether each constraint is met:

```python
constraint_coverage = {
    "kids_friendly": True,
    "low_calorie": True,
    "max_distance_5km": True,
}
```

Lightweight self-verification, replacing a separate LLM-as-judge evaluator — appropriate at demo scale.

---

## Step 3: Mock data layer

### Data scale

Simulates "the candidate pool within 5 km of the user," not all of Shanghai:

- Restaurants: 50 (8 hand-written seeds + 42 LLM-generated)
- Venues: 30 (6 hand-written seeds + 24 LLM-generated)

After per-scenario filtering, ~15–20 valid candidates remain — enough for agent planning and ranking.

### Generation strategy

```
Options compared:
  open dataset → little legal open data for China local life, high cleaning cost
  Faker        → semantically poor tags
  LLM-generated → rich natural-language tags, close to real user phrasing  ← chosen
```

Generated with a local Ollama model (qwen3:8b): free, good Chinese quality, latest version.

### Role of hand-written seeds

The 8 hand-written restaurants and 6 venues have two deliberate designs:
- `r001` has no 17:30 slot → guarantees the fallback path triggers in the demo
- `v004/v005/v006` have `kids_friendly=false` → auto-excluded by family-scenario filtering

Seeds are placed first in the merged array so key-scenario records surface first in retrieval.

### Batched generation

Generating 42 restaurants at once needs ~8400 output tokens, exceeding `max_tokens=4096` and truncating JSON. Fix: generate ≤15 per batch, then merge.

```python
def generate(prompt, label, total, batch_size=15):
    # batched calls; each batch retries independently
```

### ID management

Don't trust LLM-generated IDs; reassign uniformly after merging:

```python
def reassign_ids(data, prefix):
    for i, item in enumerate(data):
        item["id"] = f"{prefix}{i+1:03d}"  # r001, r002 ...
```

### Data evaluation

`data/evaluate.py` validates generated data in three layers:
1. **Structure**: load into Pydantic models; missing fields / type errors surface immediately
2. **Distribution**: family/friends scenario coverage each > 40%, reasonable price ranges
3. **LLM semantic spot-check**: use qwen3:8b to check name/tags/fields for logical consistency

Conclusions are computed by code, not hard-coded, to avoid mismatches with reality.

---

## Step 4: Tool layer

Small, focused modules with separated concerns:

| File | Responsibility |
|------|----------------|
| `tools/amap_http.py` | maps client: `geocode_city`, nearby POI search, mapping to `Venue`/`Restaurant`; falls back to local mock JSON when there's no API key or the call fails |
| `tools/geo.py` | haversine distance, greedy geo-clustering (pure functions) |
| `tools/travel.py` | visit-duration constants, travel-time estimates, cluster radius (pure functions) |
| `tools/links.py` | build map / booking deep links from a name + coordinates (never LLM-fabricated) |
| `tools/notification.py` | render the itinerary summary for sharing |

These are pure/deterministic functions or thin HTTP wrappers, so they're easy to unit-test (mocking only the outermost HTTP call). Availability is checked inline in the graph against the candidate data; booking is handled inline in the `execute_bookings` node, which builds `BookingResult` objects directly (demo mode — swap in a real ordering API without touching the graph).

See [architecture.md](architecture.md) for the full tool catalog. Test coverage: 131 passing tests (see [tests/README.md](../backend/tests/README.md)).

---

## Step 5: LangGraph state graph

### File structure

| File | Responsibility |
|------|----------------|
| `llm/factory.py` | LLM factory; `get_llm(role)` returns the provider's ChatModel |
| `prompts/intent_parser/system.txt` | system prompt for parse_intent |
| `prompts/planner/system.txt` | system prompt for generate_plans (incl. time-estimation instructions) |
| `prompts/notifier/system.txt` | system prompt for send_notification |
| `agent/nodes.py` | all node functions |
| `agent/graph.py` | graph assembly, conditional edges, compile |

### LLM factory

`get_llm(role)` caches instances via `@lru_cache`:

```python
# main → planning node (strong reasoning), fast → parse/notify (speed)
_MODEL_MAP = {
    "anthropic": ("claude-sonnet-4-6", "claude-haiku-4-5-20251001"),
    "openai":    ("gpt-4o",            "gpt-4o-mini"),
    "deepseek":  ("deepseek-chat",     "deepseek-chat"),
    "ollama":    ("qwen3:8b",          "qwen3:8b"),
}
```

Switching providers only requires changing `LLM_PROVIDER` in `.env`; node code is untouched.

### Structured output: with_structured_output

All nodes needing structured LLM output use LangChain's `with_structured_output(Schema)` uniformly, without introducing Instructor, to avoid interface clashes with the LangChain ChatModel:

```python
# parse_intent
llm = get_llm("fast").with_structured_output(ConstraintSet)
constraints = llm.invoke([SystemMessage(...), HumanMessage(...)])

# generate_plans (current: one Plan per call, the N plans fired concurrently via asyncio)
llm = get_llm("main").with_structured_output(Plan)
plan = llm.invoke([...])
```

`with_structured_output` uses tool_use on Anthropic and function calling on OpenAI, handled automatically — node code is provider-agnostic.

### Graph structure & execution path

```
START → parse_intent → search_candidates → generate_plans → check_availability
                                                                    │
                              ┌─────────────────────────────────────┤
                              │ plans available                      │ none available
                              ▼                                      ▼
                         human_review ◄──────────────── increment_replan → generate_plans
                         (interrupt)       user rejects      (count +1)
                              │
                              │ user confirms
                              ▼
                      execute_bookings → send_notification → END
                                                                │
                         handle_error → END ◄── replan over limit ┘
```

### AgentState fields

| Field | Type | Notes |
|-------|------|-------|
| `candidate_venues` | `list[dict]` | filled by search_candidates, read-only after |
| `candidate_restaurants` | `list[dict]` | same |
| `candidate_plans` | `Annotated[list[Plan], operator.add]` | append semantics; replan keeps history |
| `availability_results` | `dict[str, AvailabilityResult]` | key = venue/restaurant id |
| `replan_count` | `int` | replans done; over `max_replan_count` → handle_error |

### HiL (Human-in-the-Loop) implementation

The pause point is controlled by `interrupt(payload)` inside the `human_review` node; the payload carries candidate plans for the frontend to render:

```python
def human_review(state: AgentState) -> dict:
    plans = state["candidate_plans"][-config.max_candidate_plans:]
    payload = interrupt({"plans": [p.model_dump() for p in plans]})
    # resumes here after the frontend POSTs /confirm; payload is the user's confirmation
    confirmed = payload.get("confirmed", False)
    selected_id = payload.get("selected_plan_id", "")
    ...
```

`MemorySaver` persists the full state at interrupt time; on resume it continues from the breakpoint without re-running earlier nodes.

---

## Step 6: FastAPI + SSE

### File structure

| File | Responsibility |
|------|----------------|
| `api/main.py` | FastAPI entry, CORS middleware, mount router |
| `api/session_store.py` | in-memory session store, state-machine management |
| `api/routes.py` | the API endpoints |

### Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /session` | create a session, returns session_id |
| `GET /session/{id}/stream` | SSE long connection, pushes agent node progress |
| `POST /session/{id}/confirm` | user confirms/rejects, stores the resume payload |
| `GET /session/{id}/result` | fetch the final result (after `done`) |

### Session state machine

```
created → running → interrupted → resuming → running → done
                                                    └→ error
```

### Two-segment SSE

The HiL interrupt splits the SSE stream into two segments:

```
Segment 1: POST /session → GET /stream → run to interrupt → SSE emits interrupt → connection closes
Segment 2: POST /confirm (store choice) → GET /stream → Command(resume=payload) → run to completion → done
```

Each `/stream` decides what to pass to `graph.astream` based on `session.status`:
- `created` → pass the initial state
- `resuming` → pass `Command(resume=payload)`

### SSE event format

| Event | Data | When |
|-------|------|------|
| `node_update` | `{node, message}` | after each node finishes |
| `heartbeat` | `{}` | every 5s when there's no node event, to keep alive |
| `interrupt` | `{plans: Plan[]}` | HiL pause, show plans to the user |
| `done` | `{summary, booking_results}` | graph finished |
| `error` | `{message}` | on exception |

### asyncio.Queue decoupling (SSE keep-alive)

**Problem**: `graph.astream()` only yields a chunk after a node finishes. `generate_plans` with local Ollama takes minutes; if the LLM call blocks the asyncio event loop, sse-starlette's ping can't fire and the browser drops the TCP connection as a timeout.

**Fix**: decouple graph execution from the SSE generator with an `asyncio.Queue`:

```python
queue = asyncio.Queue()

async def run_graph():
    async for chunk in graph.astream(graph_input, config, stream_mode="updates"):
        await queue.put(("chunk", chunk))
    await queue.put(("done", None))

asyncio.create_task(run_graph())  # graph runs in its own task

while True:
    try:
        kind, payload = await asyncio.wait_for(queue.get(), timeout=5.0)
    except asyncio.TimeoutError:
        yield {"event": "heartbeat", "data": "{}"}  # keep-alive
        continue
    # handle chunk / done / error ...
```

The frontend registers a `heartbeat` listener and ignores it, so the UI state is unaffected.

---

## Step 7: Next.js frontend

### File structure

```
app/
  page.tsx                       # main page (Client Component, holds the state machine)
  layout.tsx                     # root layout
components/
  planner/
    ChatInput.tsx                # input box + example buttons
    AgentProgress.tsx            # agent execution progress list
    PlanCards.tsx                # candidate plan cards (timeline, cost, constraint coverage)
    ExecSummary.tsx              # execution result + itinerary notification
lib/
  types.ts                       # TypeScript types (mirror the backend Pydantic schema)
  api.ts                         # API client (createSession / openStream / confirmPlan)
```

### Frontend state machine

```typescript
type Phase =
  | { kind: "input" }
  | { kind: "running"; events: ProgressEvent[] }
  | { kind: "interrupted"; events: ProgressEvent[]; plans: Plan[]; sessionId: string }
  | { kind: "executing"; events: ProgressEvent[] }
  | { kind: "done"; summary: string; bookingResults: BookingResult[] }
  | { kind: "error"; message: string }
```

Each `phase` maps to one UI screen; transitions are driven entirely by SSE events:

```
input ──submit──→ running ──interrupt──→ interrupted ──confirm──→ executing ──done──→ done
                                              └──reject──→ running (replan)
```

### SSE handling on the frontend

```typescript
const es = openStream(sessionId);

es.addEventListener("node_update", (e) => {
  // append a progress item, spin the current step
  setPhase(prev => ({ kind: "running", events: [...prev.events, newEvent] }));
});

es.addEventListener("interrupt", (e) => {
  es.close();  // close segment 1
  setPhase({ kind: "interrupted", plans: data.plans, sessionId });
});

// reopen SSE after confirmation (segment 2)
await confirmPlan(sessionId, true, planId);
startStream(sessionId);  // passes Command(resume=...) to the backend
```

---

## Step 8: Data-model extension + Gemini + availability fixes

### Data-model extension (schemas.py / state.py)

To prepare for a real maps API and structured UI input, these models were extended:

**New enum `ActivityPreference`**: maps to frontend UI preference tags (nature / cultural / museum / social / food / family), decoupled from the backend `ActivityCategory` — frontend tags are the user's language, backend categories are the system's, with `parse_intent` mapping between them.

**New `ConstraintSet` fields**:

| Field | Notes |
|-------|-------|
| `city: str = "Shanghai"` | used for maps API queries |
| `start_time: str = "10:00"` | plan start time |
| `duration_days: int = 1` | multi-day support |
| `food_focused: bool = False` | when the food tag is active, pull more restaurant candidates |

**`Venue` gains `typical_visit_minutes: int = 90`**: default visit duration per `ActivityCategory`, for time-budget constraints in `generate_plans`.

**`TimelineItem` gains `day: int = 1`**: marks which day each activity belongs to, for per-day duration validation.

**New `PlanRequest`**: structured UI request model (with `start_date / end_date / preferences / max_distance_km`, etc.), coexisting with the existing `UserRequest(message: str)`.

**New `FreeTextConstraints`**: supplemental constraints the LLM extracts from `free_text`; all fields optional (`None` = not mentioned) to avoid overwriting structured defaults.

**New `AgentState` fields**: `user_request`, `preference_weights`, `day_clusters`, `available_activity_minutes_per_day` — see the AgentState design in the architecture doc.

---

### Gemini LLM integration (llm/factory.py / config.py)

**`config.py` `.env` path fix**: changed `env_file=".env"` to `Path(__file__).parent / ".env"` (absolute). The original relative path depended on uvicorn's working directory; launched from the project root it couldn't find `backend/.env`, so `llm_provider` fell back to `"anthropic"` and failed with an auth error.

**New `gemini` provider**: uses `langchain_openai.ChatOpenAI` + Google AI Studio's OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`), no extra SDK. Both main/fast use `gemini-2.5-flash`.

```python
if provider == "gemini":
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model_name,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key=config.google_api_key,
        temperature=0,
    )
```

---

### Availability & booking consistency fixes

Three inconsistencies found and fixed together:

**Problem**: `check_availability` and `execute_bookings` ignored `booking_required`, but `_plan_is_available` honored it — so a restaurant with `booking_required=False` skipped the availability check, the plan was wrongly considered available and shown to the user, and only failed at booking time.

**Fix principles**:

| Function | `booking_required=True` | `booking_required=False` |
|----------|-------------------------|--------------------------|
| `check_availability` | check slot availability | check opening hours only |
| `_plan_is_available` | check all restaurants/venues (ignores this field) | same |
| `execute_bookings` | make reservation | skip (walk-in) |

**`human_review` only shows fully-available plans**: extracted `plan_is_available` into a module-level `_plan_is_available`; `human_review` filters before `interrupt()` so only plans where every item is confirmed available are shown.

---

### generate_plans replan improvement (nodes.py)

**Problem**: on replan the LLM didn't know which slots failed last time, kept generating the same times, repeatedly hit `max_replan_count`, then reported "no suitable plan found."

**Fix**, two improvements:
1. Format restaurant candidates' `available_slots`: "bookable slots: 17:30, 18:00, 18:30, 19:00" so the LLM picks from valid slots
2. On replan, inject failure reasons: "last plan failed, avoid these slots/venues: - Restaurant X 15:55 no seats"

---

## Step 9: Maps API integration + RAG → direct API retrieval

### Architecture evolution: RAG → maps API + programmatic scoring

**Original design**: `search_candidates` called `tools/search.py`, doing in-memory ChromaDB vector retrieval over 80 mock JSON records plus hard-constraint field filtering.

**Problem**: mock IDs (`v001`, `r001`...) relate to no external system, availability is also mock — no real data flows through the chain.

**New design**:
1. `tools/travel.py` — visit-duration constants, travel-time estimates (pure functions)
2. `tools/geo.py` — haversine distance, greedy geo-clustering (pure functions)
3. `tools/amap_http.py` — maps keyword-search client with layered fallback (empty key → mock, API error → mock, API empty → mock, empty after filtering → return empty to respect constraints)
4. `search_candidates` becomes `async def`, with `asyncio.gather + asyncio.to_thread` retrieving the two data sources in parallel

**Removed with this migration**: the RAG data layer (`tools/store.py` ChromaDB index, `tools/search.py` two-stage retrieval, `tools/availability.py` store-ID-based checks, and the standalone `tools/booking.py`) became dead code and was deleted. Availability is now checked inline against the candidate data, and `execute_bookings` builds `BookingResult` objects directly.

### parse_intent hybrid mode (Step 4)

`parse_intent` has two paths:

| Path | Trigger | LLM call |
|------|---------|----------|
| PlanRequest path | `state["user_request"]` non-empty (new UI) | fast-LLM only when `free_text` is non-empty, to extract `FreeTextConstraints` |
| Legacy UserRequest path | `user_request` empty (free text) | full LLM extraction of `ConstraintSet` |

Preference tags map directly (zero LLM):
```python
cultural → [museum, exhibition, citywalk]
nature   → [park, citywalk]
family   → [aquarium, kids_center, park]
food     → []  (food_focused=True, affects restaurant search weight)
```

### New frontend PlannerInput (Step 8)

Replaces the plain text box with structured fields:
- date-range picker (linked validation)
- party-size stepper (± buttons)
- city input
- preference tags (multi-select pills: museum / nature park / culture & history / leisure & social / family / food)
- travel mode (multi-select pills: walk / metro / taxi / cycling)
- supplemental free-text box (optional, triggers LLM parsing)

`POST /session` supports both PlanRequest (new UI) and the legacy `{message: str}`, auto-routing by JSON fields.

### Key design decisions

**Why not MCP**: the maps API's call timing and caller are determined by the program (the `search_candidates` node always calls it); no dynamic LLM decision is needed. MCP suits ReAct; for a deterministic Workflow it only adds complexity.

**Distance calculation**: the maps API's `distance_km` is relative to the user's GPS, which the backend lacks; we use haversine between the venue's coordinates and the city center (e.g. Shanghai People's Square) as an approximation.

**`available_slots` fixed values**: the maps provider gives no live reservation data, so `available_slots` is a fixed slot list (`11:30/12:00/.../19:30`). A real scenario would integrate a reservation API.
