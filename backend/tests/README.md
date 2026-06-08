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
uv run pytest tests/ -k "no_seat"

# quiet mode
uv run pytest tests/ -q
```

## Coverage (131 tests)

| Layer | Files | Covers |
|-------|-------|--------|
| Data / tools | `test_amap_http.py`, `test_geo.py`, `test_travel.py` | maps client (geocode + nearby search + field mapping + fallback), haversine distance, geo-clustering, travel-time estimates |
| Availability / booking / notify | `test_availability.py`, `test_booking.py`, `test_notification.py` | slot availability + fallback slots, booking execution + final-check, notification sending |
| Agent | `test_graph_routing.py`, `test_timeline_validation.py` | conditional-edge routing (no LLM calls), programmatic timeline/budget validation |
| Models / E2E | `test_phase1_models.py`, `test_e2e.py` | Pydantic schema contracts, end-to-end flow |

## Testing strategy

### What to test

| Module | Method | Why |
|--------|--------|-----|
| Deterministic tools (geo / travel / availability / booking / validation) | pytest unit tests | fixed I/O, pure logic |
| Maps client (`amap_http`) | unit tests with the HTTP call mocked | assert request building + response→model mapping + fallback, without hitting the network |
| Graph conditional edges (routing) | pytest unit tests | pure functions; control-flow correctness is critical |
| LLM nodes (parse_intent / generate_plans / send_notification) | no assertion tests | non-deterministic output; assertions would be brittle |
| LLM node behavior | LangSmith trace observation | verify I/O at runtime via traces |

### Mock only at the external boundary

Tests run the **real tool logic** and only mock the outermost dependency (the maps HTTP call). Mocking out internal logic would mean a test only verifies "the right mock was called" rather than "the logic is correct" — a primary source of test drift.

### Key test cases

`test_availability.py::TestCheckRestaurantAvailability::test_r001_no_17_30_slot` — verifies the core fallback logic: restaurant `r001` has no 17:30 slot, returns `NO_SEAT` with `next_available_slot=18:30`.

`test_graph_routing.py::TestRouteAfterAvailability::test_all_unavailable_at_limit_routes_to_error` — verifies that exceeding the replan cap routes into the `handle_error` node, with no infinite loop.

`test_amap_http.py` — verifies that the maps client maps POIs to `Venue`/`Restaurant` correctly and falls back to local mock data when there's no API key or the call fails.
