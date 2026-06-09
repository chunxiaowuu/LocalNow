# Testing

**English** | [中文](README.zh-CN.md)

## Running tests

```bash
# from the backend/ directory

# run all tests
uv run pytest tests/ -v

# run a single module
uv run pytest tests/test_amap_http.py -v
uv run pytest tests/test_timeline_validation.py -v
uv run pytest tests/test_graph_routing.py -v

# filter by keyword
uv run pytest tests/ -k "fallback"
uv run pytest tests/ -k "replan"

# quiet mode
uv run pytest tests/ -q
```

## Coverage (102 tests)

| Layer | Files | Covers |
|-------|-------|--------|
| Data / tools | `test_amap_http.py`, `test_geo.py`, `test_travel.py` | maps client (geocode + nearby search + field mapping + fallback), haversine distance, geo-clustering, travel-time estimates |
| Agent | `test_graph_routing.py`, `test_timeline_validation.py` | conditional-edge routing (no LLM calls), programmatic timeline/budget validation |
| Models / E2E | `test_phase1_models.py`, `test_notification.py`, `test_e2e.py` | Pydantic schema contracts, notification rendering, end-to-end flow |

## Testing strategy

### What to test

| Module | Method | Why |
|--------|--------|-----|
| Deterministic tools (geo / travel / validation) | pytest unit tests | fixed I/O, pure logic |
| Maps client (`amap_http`) | unit tests with the HTTP call mocked | assert request building + response→model mapping + fallback, without hitting the network |
| Graph conditional edges (routing) | pytest unit tests | pure functions; control-flow correctness is critical |
| LLM nodes (parse_intent / generate_plans / send_notification) | no assertion tests | non-deterministic output; assertions would be brittle |
| LLM node behavior | LangSmith trace observation (enable via `LANGCHAIN_TRACING_V2`) | verify I/O at runtime via traces |

### Mock only at the external boundary

Tests run the **real tool logic** and only mock the outermost dependency (the maps HTTP call). Mocking out internal logic would mean a test only verifies "the right mock was called" rather than "the logic is correct" — a primary source of test drift.

### Key test cases

- `test_graph_routing.py::TestRouteAfterAvailability::test_all_unavailable_at_limit_routes_to_error` — exceeding the replan cap routes into `handle_error`, with no infinite loop.
- `test_amap_http.py::TestFetchVenuesFallbackOnError` — the maps client falls back to local mock data when the API errors (or there's no key).
- `test_timeline_validation.py::test_overlap_detected` — programmatic validation rejects overlapping timeline items rather than trusting the model.
