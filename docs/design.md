# LocalNow — Design

**English** | [中文](design.zh-CN.md)

> A short-horizon local activity planning & execution agent.
> One natural-language goal → (a full play → eat → activity plan) → user confirms → one-click booking & sharing.

## 0. In one line
Turn a casual goal like *"this afternoon I want to take my wife and kid / friends out for a few hours, nothing too far, plan it for me"* into **comparable, executable** multi-step itineraries, then **complete the key bookings** after confirmation and **share the plan in one click** — not search-and-recommend, but "get it done for you."

Supports scenario-aware constraints: **family** (5-year-old → kid-friendly venues + children's menu; dieting → low-calorie restaurants); **friends** (group of 4 → party size / portions / lively atmosphere).

---

## 1. Planning strategy

Uses a **deterministic workflow rather than ReAct**: fixed step order, single responsibility per step — easy to validate, debug, and reproduce. The LLM is used only where semantic judgment is needed; everything else is program logic for reliability.

1. **Intent parsing `parse_intent` (hybrid)**
   The structured form (date / party size / city / preferences / duration / distance) maps directly with zero LLM; free-text ("want to see the Monet exhibition, wife is dieting") goes through one fast-LLM extraction: low-calorie, kid-friendly, start time, budget, and specific "want to eat / want to visit" requests. Preferences → activity categories + weights; family → kid-friendly / children's menu.
2. **Candidate retrieval `search_candidates`**
   `geocode place → coordinates` + **nearby search** retrieves real venues/restaurants (works for any city / district / scenic area nationwide); **hard-filters** on haversine distance + visit duration + per-person budget; ranks by rating (popularity proxy); geo-clusters by day.
   *Cold-start semantic degradation*: for long-tail requests ("extra-spicy rabbit-head noodles") the LLM produces a "specific → broad" keyword ladder, retrieving level by level until results appear, falling back to the closest popular candidates and telling the user.
3. **Plan generation `generate_plans`**
   Step count scales with per-day duration (half day = 1 activity + 1 meal; full day = 2–3 activities + 2 meals); multi-day plans are arranged per `day`. Generates 2 stylistically distinct, comparable plans **concurrently** (one independent call per plan — faster and non-blocking).
4. **Programmatic validation (don't just trust the LLM's self-report)**
   `validate_timeline`: time continuity / no overlap, per-day total duration ≤ limit, **per-day** per-person cost ≤ budget, full day coverage; no repeated venue across days, no near-duplicate plans. On failure, the error is **fed back into the prompt for a retry** (hard constraints always retry; soft constraints ≤ 1).
5. **Human-in-the-loop `human_review` (interrupt/resume)**
   Only fully-available plans are shown to the user; the user **confirms** → execute; or **replans with feedback** (tweak one plan / start over), which drives re-retrieval.

---

## 2. Tool-call chain

LangGraph state graph (nodes = agent steps, conditional edges = decisions):

```
parse_intent → search_candidates → generate_plans → check_availability
   ├─ plans available → [interrupt] human_review
   │      ├─ confirm → execute_bookings → send_notification → END
   │      └─ reject  → increment_replan → parse_replan_feedback → search_candidates …
   └─ none available → increment_replan → (over limit) handle_error → END
```

**Tool implementations (all include mock — auto-fall back to local JSON on no key / failure):**

| Tool | Input | Output | Mock |
|---|---|---|---|
| `geocode_city` | place name | coordinates (+ cache) | 15-city local cache fallback |
| `_search_pois` (nearby search) | keywords + coordinates | real POIs | — |
| `fetch_venues` / `fetch_restaurants` | city / preferences / budget / party size | `Venue[]` / `Restaurant[]` | no key → `data/*_full.json` |
| `check_availability` (inline) | plan + time + party size | opening hours (regex) / restaurant slots + capacity → need reschedule / queue? | from candidate fields |
| `execute_bookings` | selected plan | `BookingResult[]` (order / reservation) | **demo mode**: builds success results marked "complete via official channel"; swap in a real booking API directly |
| `amap_marker_uri` / `amap_search_uri` | venue name + coordinates | map / booking deep links | string-built (never LLM-fabricated) |
| `send_notification` / checklist | plan | copy text / PDF / email share | mailto / print / Blob |

**Frontend delivery**: after confirmation, an **itinerary checklist** — per-day view, each item toggleable "done / booked" (localStorage-persisted), **open all booking pages in one click**, copy / export PDF / email share.

---

## 3. Error handling

- **Data source**: no API key / network failure / empty result → fall back to local mock; if candidates are entirely removed by hard filters → return empty (**don't mask** "no match within budget"), then a safety net relaxes distance and re-retrieves — no out-of-region data, no fabrication.
- **Obscure places** (e.g. Hailing Island): text search's `city` only accepts administrative cities and silently returns a default (Beijing) → switched to `geocode → nearby search`, works nationwide.
- **Long-tail requests**: exact-keyword retrieval empty → semantic-degradation ladder broadens level by level, and on degradation transparently tells the user "X not found, here's a close match."
- **Unreliable LLM**: structured-output schema validation failure → feed-back-and-retry; **per-request timeout + retry cap** (saw a ~930s hung outlier → capped at 240s); empty response → retry instead of crash.
- **Availability**: venue outside opening hours / restaurant full → annotate the reason and trigger a replan/replacement; over the replan cap → `handle_error` graceful fallback, no infinite loop.
- **Booking**: demo mode is clearly labeled to avoid misleading; swap in real ordering and replace the return value.
- **Frontend**: invalid links (non-http) not rendered, avoiding 404s; in-memory session storage (known item; use Redis in production).

---

**Tech stack**: Python · FastAPI · LangGraph · maps REST API · Next.js · Docker + GitHub Actions CI; multi-provider LLM abstraction (Gemini / LongCat / OpenAI / DeepSeek / Ollama, switch via `.env`).
