# Testing

**English** | [中文](README.zh-CN.md)

## Running tests

```bash
# from the backend/ directory

# run all tests
uv run pytest tests/ -v

# run a single module
uv run pytest tests/test_availability.py -v
uv run pytest tests/test_booking.py -v
uv run pytest tests/test_notification.py -v
uv run pytest tests/test_graph_routing.py -v

# filter by keyword
uv run pytest tests/ -k "fallback"
uv run pytest tests/ -k "no_seat"

# quiet mode (don't print each case name)
uv run pytest tests/ -q
```

## Coverage

### Tool layer (36 cases)

| File | Cases | Covers |
|------|-------|--------|
| `test_availability.py` | 19 | restaurant/venue availability queries, fallback slots, edge cases |
| `test_booking.py` | 10 | booking execution, final-check interception, fallback flags |
| `test_notification.py` | 7 | single/batch notification sending, error handling for unsupported channels |

### Agent layer (9 cases)

| File | Cases | Covers |
|------|-------|--------|
| `test_graph_routing.py` | 9 | conditional-edge routing logic (no LLM calls) |

## Testing strategy

### What to test

| Module | Method | Why |
|--------|--------|-----|
| Tool layer (availability/booking/notification) | pytest unit tests | pure deterministic logic, fixed I/O |
| Graph conditional edges (routing functions) | pytest unit tests | pure functions; control-flow correctness is critical |
| LLM nodes (parse_intent/generate_plans/send_notification) | no assertion tests | non-deterministic output; assertions would be brittle |
| LLM node behavior | LangSmith trace observation | verify I/O at runtime via traces |

### Why we don't mock the data layer

Tool-layer tests use **real data** rather than mocks.

Reason: mocking out the data layer means the test only verifies "the right mock was called," not "the logic is correct." Mocking out key dependencies is a primary source of test drift.

### Key test cases

`test_availability.py::TestCheckRestaurantAvailability::test_r001_no_17_30_slot` — verifies the core fallback logic: restaurant `r001` has no 17:30 slot, returns `NO_SEAT` with `next_available_slot=18:30`.

`test_graph_routing.py::TestRouteAfterAvailability::test_all_unavailable_at_limit_routes_to_error` — verifies that exceeding the replan cap routes correctly into the `handle_error` node, with no infinite loop.

## Shared fixtures

`conftest.py` provides a session-scoped `store` fixture so the data store is initialized once per test session, avoiding repeated loading across test files.
