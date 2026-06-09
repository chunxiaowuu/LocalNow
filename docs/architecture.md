# LocalNow — Architecture

**English** | [中文](architecture.zh-CN.md)

## Positioning

A short-horizon local activity planning and execution agent.

**Core value**: "get it done for you" — not search-and-recommend, but take one natural-language goal, output an executable end-to-end plan, and after the user confirms, automatically complete all bookings / orders / notifications.

**Two scenarios**:
- Family: user + 5-year-old + dieting spouse, not far from home
- Friends: 4 people (2M/2F), an afternoon of 4–6 hours

---

## System nature

LocalNow is a planning **agent** implemented as a deterministic **workflow** (the LangGraph state graph fixes the step order), not an autonomous ReAct agent that picks its own tools — a deliberate reliability choice (see the TravelPlanner comparison below). The LLM handles semantic understanding, creative planning, and replanning trade-offs; code owns everything that needs precision (availability / distance / budget / control flow).

---

## Architecture diagram

```
┌─────────────────────────────────────────────────────┐
│              Next.js Frontend (App Router)           │
│                                                      │
│  ChatInput → PlanCards → ConfirmModal → ExecProgress │
│       ↑                                              │
│  EventSource (SSE) ←── live node-execution status    │
│  fetch / axios     ←── REST request/response         │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP / SSE
┌──────────────────────▼──────────────────────────────┐
│               FastAPI Backend                        │
│                                                      │
│  POST /session                 start a planning session
│  GET  /session/{id}/stream     SSE: push agent progress
│  POST /session/{id}/confirm    user confirms a plan
│  GET  /session/{id}/result     fetch the final result
└──────────────────────┬──────────────────────────────┘
                       │ in-process
┌──────────────────────▼──────────────────────────────┐
│            LangGraph Workflow Engine                 │
│                                                      │
│  parse_intent → build_constraints → generate_plans  │
│       ↑                                   ↓         │
│  replan ←(all unavailable)── check_availability     │
│                                           ↓         │
│                             ⏸ interrupt (HiL)       │
│                                           ↓         │
│                             execute_bookings (parallel)
│                                           ↓         │
│                                  send_notification  │
│                                                      │
│  + structured output                                 │
│  + asyncio parallel tool calls                       │
│  + MemorySaver checkpoint/resume                     │
└──────────┬───────────────────────────────────────────┘
      ┌────┴────┐
┌─────▼───┐  ┌──▼──────────────────────────────────┐
│  Tools  │  │           LLM Factory               │
│ search  │  │  Anthropic / OpenAI / DeepSeek       │
│ check   │  │  Google / Ollama / LongCat           │
│ book    │  │  role: main (plan/execute) fast (parse/notify)
│ notify  │  └─────────────────────────────────────┘
└─────┬───┘
┌─────▼───────────────────────────────────────────────┐
│  Maps REST API  +  local mock JSON (fallback)        │
│  keyword retrieval + haversine distance filter + scoring
└─────────────────────────────────────────────────────┘
```

---

## Planning strategy

### Two-stage Plan-and-Execute (Wang et al. 2023)

**Stage 1 — Planner LLM (main model)**
- Input: structured constraints (extracted from natural language)
- Output: 2 plan skeletons (experience type + venue type, no specific store)
- Technique: CoT prompt to guide constraint reasoning, structured-output enforcement

**Stage 2 — Tool Executor (parallel)**
- Input: plan skeletons
- Output: concrete stores + live availability
- Technique: `asyncio.gather` parallel queries, results written back to AgentState

**Why not pure ReAct**: ReAct re-reasons the next action at every step; on long chains it suffers from the "lost in the middle" problem (Liu et al. 2023). The planning task has finite, enumerable steps, where Plan-and-Execute's global view is more stable.

TravelPlanner (Xie et al. ICML 2024) provides direct counter-evidence: under ReAct, GPT-4's final pass rate on multi-constraint planning was only **0.6%**, mainly due to tool-call loops and lost context. We chose a Workflow with a fixed execution path and explicit intermediate state in LangGraph to avoid these failures.

**LangGraph State mirrors TravelPlanner's NotebookWrite tool**: TravelPlanner found that agents "forget" early-collected information after many tool-call rounds, so it designed a dedicated external notebook tool. We persist all intermediate results in `AgentState` fields (`availability_results`, `candidate_plans`, …) rather than relying on LLM context memory, solving the same problem.

### LLM vs. tool responsibility boundary

| Task | Who | Why |
|------|-----|-----|
| "dieting spouse" → low_calorie constraint | LLM | semantic understanding |
| generate "activity + restaurant" combos | LLM | creativity + common sense |
| which restaurant has a low-cal menu | tool (structured filter) | precision; the LLM doesn't know live data |
| does that 17:30 restaurant have a table | tool | live state |
| is a 40-min wait worth switching plans | LLM | trade-off judgment |

---

## Key technical choices

### 1. LangGraph (orchestration)

Three needs LCEL can't meet drove this choice:
- **Persistent state**: TypedDict + Annotated reducers control per-field merge semantics
- **Human-in-the-loop**: `interrupt()` + MemorySaver checkpoint/resume — continue from the breakpoint after the user confirms
- **Conditional fallback**: conditional edges handle "all plans unavailable → replan"

### 2. Structured output + Pydantic v2

Industry-standard validation-retry loop:
- When LLM output doesn't match the schema, the ValidationError is fed back into the prompt for self-correction
- Up to 3 retries
- The Plan output includes a `constraint_coverage` field where the LLM self-declares whether each constraint is met (lightweight self-verification)

### 3. Maps API + programmatic scoring (retrieval)

> **Architecture evolution**: the initial version used in-memory ChromaDB for vector semantic retrieval (RAG), later switched to calling a maps REST API directly. Real data covers nationwide POIs and reflects real-world availability better than 80 mock records; real API integration also demonstrates more engineering depth than local vector retrieval. the old RAG modules (`tools/store.py`, `tools/search.py`) have since been removed.

The retrieval layer uses the maps keyword-search endpoint:

```
preference tags → keyword mapping
  museum/exhibition → "museum / exhibition hall"
  park             → "park"
  kids_center      → "kids' playground"

→ maps API returns up to 25 real POIs
→ haversine distance filter (within radius of city center)
→ duration filter (typical_visit_minutes ≤ total outing duration)
```

#### Cold-start retrieval ladder (retrieval-side semantic degradation)

When a user makes a specific, long-tail request ("a specific ramen shop", "a Monet exhibition"), exact keywords often return nothing. The fix does semantic degradation on the **retrieval side**, not by filtering candidates:

```
parse_intent (fast LLM, world knowledge)
  → produces a "specific → broad" retrieval ladder
     ramen → [a specific ramen shop, ramen restaurant, noodle restaurant]
     Monet exhibition    → [Monet exhibition, art exhibition, art museum, museum/exhibition hall]

_laddered_fetch (generic helper, shared by dining/venues)
  → calls the maps API level by level; a level counts as a hit only if candidates survive filtering (the keep predicate is built into the ladder)
  → when a narrow term is emptied by distance/duration filters, it auto-degrades to the next level
  → if all empty, a safety net relaxes distance and re-retrieves, so the planner never gets an empty pool

generate_plans
  → tells the LLM the original request + whether it was an exact hit; on degradation it picks the closest popular candidate and explains transparently in notes
  → the prompt forbids fabrication: the name must be taken verbatim from the candidate list
```

- "Similar" is done by the LLM on the retrieval side; "popular" is done by post-retrieval rating sort — no vector-similarity filtering.
- `fetch_venues` / `fetch_restaurants` expose `keywords` (injected level by level) and `allow_mock_fallback` (suppress the mock fallback during the ladder) to support this.

### 4. Explicit constraint scoring (ranking)

Replaces LLM ranking — more transparent and debuggable (cf. MT-Bench interpretability):

```python
score = (0.35 * rating_score
       + 0.20 * budget_fit
       + 0.45 * preference_match)   # preference weights driven directly by UI tags
```

### 5. Structured error codes + replanning

```python
class ToolErrorCode(str, Enum):
    NO_SEAT            = "NO_SEAT"
    TOO_FAR            = "TOO_FAR"
    OVER_BUDGET        = "OVER_BUDGET"
    DELIVERY_UNAVAIL   = "DELIVERY_UNAVAILABLE"
    CLOSED             = "CLOSED"
```

Each error code maps to a precise replanning strategy; the LLM doesn't decide how to fix it.

### 6. LLM Factory (multi-provider)

LangChain's `BaseChatModel` unified interface; nodes switch providers transparently:

| Provider | main | fast |
|----------|------|------|
| Anthropic | claude-sonnet-4-6 | claude-haiku-4-5-20251001 |
| OpenAI | gpt-4o | gpt-4o-mini |
| DeepSeek | deepseek-chat | deepseek-chat |
| Gemini | gemini-2.5-flash | gemini-2.5-flash |
| Ollama | qwen3:8b | qwen3:8b |

Gemini is reached via Google AI Studio's OpenAI-compatible endpoint using `ChatOpenAI` + a custom `base_url`, with no extra SDK.

Node-to-role mapping:
- `parse_intent` → fast
- `generate_plans` → main (core reasoning node)
- `rank_and_select` → fast
- `execute_bookings` → main (highest fault-tolerance requirement)
- `send_notification` → fast

### 7. Concurrent plan generation + timeouts

The two comparable plans are generated **concurrently** — one independent structured call per plan via `asyncio` — roughly halving wall-clock latency for multi-day itineraries versus sequential generation. Each call carries a request timeout and a retry cap, so a single slow or stuck provider call can't hang the whole run.

### 8. FastAPI + SSE (frontend/backend)

LangGraph supports `stream_mode="updates"` for per-node streaming output; FastAPI forwards it to the frontend over SSE:
- SSE (one-way push) is better than WebSocket (two-way) — agent execution is one-way
- implemented with `sse-starlette`

### 9. Next.js + shadcn/ui (frontend)

shadcn/ui prebuilt components (Card/Dialog/Progress/Badge) used directly for fast, high-quality UI.

---

## AgentState design

```python
class AgentState(TypedDict):
    # input
    user_message: str
    user_request: dict                        # structured UI request
    scenario: Literal["family", "friends"]

    # constraints (LLM-extracted from NL / mapped directly from structured UI)
    constraints: ConstraintSet
    preference_weights: dict[str, float]      # ranking weights driven by preference tags

    # candidate pools
    candidate_venues: list[dict]
    candidate_restaurants: list[dict]
    day_clusters: list[list[dict]]            # per-day clustered venue candidates for multi-day trips
    available_activity_minutes_per_day: int

    # planning (Annotated = append semantics, accumulates across replans)
    candidate_plans: Annotated[list[Plan], operator.add]
    availability_results: dict[str, AvailabilityResult]
    selected_plan: Plan | None

    # execution
    user_confirmed: bool
    booking_results: Annotated[list[BookingResult], operator.add]

    # control
    replan_count: int          # prevents infinite fallback, max 2
    error: str | None

    # output
    summary_message: str
```

---

## Tool catalog

### Query (called automatically by the agent)
- `fetch_venues(city, categories, ...)` → maps API retrieval + filter, returns `Venue[]`
- `fetch_restaurants(city, ...)` → maps API retrieval + filter, returns `Restaurant[]`
- `haversine_km(a, b)` → great-circle distance (for distance filtering)
- `greedy_cluster(venues, k, radius)` → greedy geo-clustering (group multi-day trips by day)
- `neighborhood_radius_km(hours, modes)` → cluster radius from duration and travel mode
- `estimate_travel(distance, modes)` → empirical travel-time estimate (no API needed)

### Validation (called automatically)
- `check_availability(state)` → validates opening hours + reservation slots for each venue/restaurant in a plan (uses candidate data directly, no store lookup)

### Execution (called after user confirmation)
- `execute_bookings(state)` → builds a `BookingResult` for each plan item (demo mode; swap in a real ordering/reservation API)
- `send_trip_summary(...)` (`tools/notification.py`) → renders the shareable itinerary summary

---

## Constraint structure (two scenarios)

```python
SCENARIO_CONSTRAINTS = {
    "family": {
        "activity":  {"kids_friendly": True, "min_age_limit": 5, "prefer_indoor": True},
        "restaurant":{"has_kids_menu": True, "has_low_calorie_options": True,
                      "noise_level": ["quiet", "moderate"]},
        "logistics": {"max_distance_km": 5, "travel_mode": ["walk", "taxi"]},
    },
    "friends": {
        "activity":  {"types": ["exhibition", "citywalk", "escape_room"]},
        "restaurant":{"group_friendly": True, "party_size": 4, "price_range": "mid"},
        "logistics": {"max_distance_km": 10, "travel_mode": ["taxi", "metro"]},
    },
}
```

---

## FastAPI endpoints

```
POST /session                   create a planning session, returns session_id
GET  /session/{id}/stream       SSE: agent node-execution progress
POST /session/{id}/confirm      user confirms a plan, triggers execution
GET  /session/{id}/result       fetch the full result and message text
GET  /quota                     remaining daily plan quota (per IP / user)
GET  /auth/github/login         GitHub OAuth login (redirect)
GET  /auth/github/callback      OAuth callback → issues a session token
GET  /auth/me                   current login state
```

## Deployment & security

- **Frontend** on GitHub Pages (Next.js static export), **backend** on Render (Docker); API keys live only in backend env vars, never in the browser.
- **Auth**: GitHub OAuth — the backend issues a signed token, the frontend sends it as `Authorization: Bearer` (robust across origins, avoids third-party cookies).
- **Rate limiting** (per IP when anonymous, per user when logged in): anonymous 1 plan/day + ≤3 replans per plan; logged-in 3 plans/day + ≤9 replans — returns `429` over the limit.
- **CORS** locked to the frontend origin in production; **Docker** images + **GitHub Actions CI** (backend `ruff`+`pytest`, frontend `tsc`+`eslint`+`build`, image build).

See [deployment.md](deployment.md) for the full setup.

---

## Full tech stack

| Layer | Tech | Role |
|-------|------|------|
| Frontend framework | Next.js (App Router) | routing |
| UI components | Tailwind CSS + shadcn/ui | fast, high-quality UI |
| Real-time | SSE (EventSource) | push agent progress |
| Backend framework | FastAPI + uvicorn | async API |
| SSE library | sse-starlette | FastAPI SSE wrapper |
| Agent orchestration | LangGraph | state graph + interrupt |
| Structured output | Pydantic v2 + validation-retry | LLM output validation |
| POI data | maps REST API | real venue/restaurant retrieval |
| Fallback data | JSON fixtures | when the API is unavailable |
| LLM access | LangChain multi-provider | main/fast tiers |
| Observability | LangSmith (via LangChain) | enable with `LANGCHAIN_TRACING_V2` |

---

## References

| Design decision | Source |
|-----------------|--------|
| Workflow vs. Agent | Anthropic *Building Effective Agents* (2024.12) |
| Plan-and-Execute | Wang et al. 2023 + LangGraph tutorials |
| Lost-in-the-middle | Liu et al. 2023 |
| Structured output | instructor-ai (Jason Liu) |
| Human-in-the-loop | LangGraph docs, `interrupt()` |
| Explicit scoring over LLM ranking | MT-Bench interpretability (Zheng et al. 2023) |
| ReAct failure rate in multi-constraint planning (counter-evidence) | Xie et al. *TravelPlanner* ICML 2024 |

---

## Comparison with TravelPlanner

> Ref: Xie et al. "TravelPlanner: A Benchmark for Real-World Planning with Language Agents", ICML 2024 Spotlight. [ArXiv 2402.01622](https://arxiv.org/abs/2402.01622)

### Positioning difference

| Dimension | TravelPlanner | LocalNow |
|-----------|---------------|----------|
| Goal | academic benchmark for LLM planning limits | product demo showcasing agent-orchestration engineering |
| Agent mode | ReAct (autonomous tool-call ordering) | Workflow (fixed, enumerable path) |
| Data scale | 3.8M real records | 80 mock records (+ live maps API) |
| Time span | multi-day cross-city travel | half-day local activity |
| Constraint evaluation | Micro/Macro Pass Rate metrics | LLM-declared constraint_coverage |

### Why our choices are right

TravelPlanner's key finding: under ReAct, GPT-4's final pass rate was only 0.6%, with failures concentrated in two areas:
1. **Tool calls out of control**: stuck in loops, failing to finish within 30 steps
2. **Lost context**: early results pushed out of the context window after many tool-call rounds

LocalNow's design addresses both:
- Workflow's fixed path → eliminates tool-call loops
- LangGraph's explicit state persistence → eliminates information loss

### Inspiration from the three-tier constraint taxonomy

TravelPlanner splits constraints into three tiers: hard constraints (explicitly specified), commonsense constraints (implicit, e.g. "same-day activities in the same city"), and environmental constraints (dynamic state, e.g. "restaurant has no seats").

LocalNow's mapping:
- Hard constraints → modeled explicitly in `ConstraintSet`
- Commonsense constraints → handled in the LLM prompt (an accepted simplification at demo scale)
- Environmental constraints → `AvailabilityResult` + replan mechanism

### Possible future direction

The `constraint_coverage: dict[str, bool]` field is already reserved (in the `Plan` model); a future `evaluate.py` could add plan-quality scoring that computes a constraint-satisfaction rate, mirroring TravelPlanner's Micro Pass Rate.
