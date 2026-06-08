# LocalNow

**English** | [中文](README.zh-CN.md)

A short-horizon local activity **planning and execution** agent.

Give it one casual goal — *"This afternoon I want to take my wife and kid (or some friends) out for a few hours, nothing too far, plan it for me"* — and it returns **comparable, executable** multi-step itineraries (play → eat → activity), then **completes the key bookings in one click** after you confirm and lets you **share the plan** with your companions.

Not search-and-recommend, but "get it done for you."

📄 **Design doc (planning strategy / tool-call chain / error handling)**: [docs/design.md](docs/design.md)

## What it does

- 🗣️ **Casual goal + scenario-aware constraints**: structured form + free-text; family (5-year-old → kid-friendly venues + children's menu, dieting → low-calorie restaurants) vs. friends (group outing) automatically apply different constraints.
- 🗺️ **Real map data**: `geocode place → coordinates → nearby search`, works for **any city / district / scenic area / island** nationwide (auto-falls back to local mock when no API key is set).
- 🧠 **LLM + LangGraph workflow**: retrieve → generate → **programmatic time/budget validation + feedback-retry** (don't just trust the LLM's self-report) → human-in-the-loop confirm / feedback-driven replan.
- ❄️ **Semantic degradation for long-tail requests**: when an exact match (e.g. "extra-spicy rabbit-head noodles" / "Monet exhibition") isn't found, the LLM produces a "specific → broad" retrieval ladder that gracefully falls back to the closest popular candidates, and tells the user.
- ⚡ **Concurrent per-plan generation**: roughly 2× faster wall-clock for multi-day itineraries; per-request timeout + retry cap prevent a single call from hanging.
- ✅ **Post-confirmation itinerary checklist**: per-day "done / booked" checkboxes (persisted in localStorage), **open all booking pages in one click**, copy / export PDF / share by email.
- 🔌 **Multi-provider LLM abstraction** (Gemini / LongCat / OpenAI / DeepSeek / Ollama, switch via `.env`); **Docker + GitHub Actions CI**.

## Workflow (LangGraph: deterministic orchestration + human-in-the-loop)

```
parse_intent → search_candidates → generate_plans → check_availability
   ├─ plans available → [interrupt] human_review
   │      ├─ confirm → execute_bookings → send_notification → END
   │      └─ reject  → parse_replan_feedback → search_candidates … (replan)
   └─ none available → replan → (over limit) handle_error → END
```

## Project structure

```
LocalNow/
├── backend/          # Python backend (FastAPI + LangGraph)
│   ├── agent/        # State graph & nodes (parse / retrieve / generate / validate / book / notify)
│   ├── tools/        # Tools: amap_http (geocode + nearby search), geo, travel, links, notification
│   ├── llm/          # LLM factory (multi-provider switch)
│   ├── models/       # Pydantic data models
│   ├── data/         # Local mock data (fallback when no API key)
│   ├── prompts/      # Prompt templates
│   ├── api/          # FastAPI entry (SSE streaming progress)
│   └── tests/        # Unit tests (131)
├── frontend/         # Next.js 16 frontend (form / live progress / plan comparison / checklist)
├── docs/             # design.md / architecture.md / development.md / deployment.md
└── docker-compose.yml + .github/workflows/ci.yml
```

## Quick start

### Requirements

- Python 3.11+ ·  Node.js 20+ ·  [uv](https://github.com/astral-sh/uv)

### Backend

```bash
cd backend
cp .env.example .env      # fill in API keys
uv sync
uv run uvicorn api.main:app --reload
```

Key `.env` settings:

```env
# LLM provider: anthropic | openai | deepseek | gemini | ollama | longcat
LLM_PROVIDER=gemini
GOOGLE_API_KEY=...         # or the key for your chosen provider
AMAP_API_KEY=...           # maps (real venue/restaurant retrieval; falls back to mock if unset)
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000
```

## Docker (one command)

```bash
cp .env.example .env      # fill LLM_PROVIDER / its API key / AMAP_API_KEY
docker compose up --build
```

Frontend http://localhost:3000 ·  Backend http://localhost:8000
(`NEXT_PUBLIC_API_URL` is inlined into the frontend at build time and the browser talks to the backend directly; for deployment, set it to the backend's public URL and rebuild the frontend image.)

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on push to main and every PR:

- **backend**: `ruff check` + `pytest`
- **frontend**: `tsc --noEmit` + `eslint` + `next build`
- **docker**: build backend & frontend images (validate Dockerfiles)

## Docs

- [Design — design.md](docs/design.md): planning strategy / tool-call chain (with tool + mock table) / error handling
- [Architecture — architecture.md](docs/architecture.md): tech choices & design decisions
- [Development — development.md](docs/development.md) · [Troubleshooting — troubleshooting.md](docs/troubleshooting.md)
- [Deployment — deployment.md](docs/deployment.md) · Tests: [backend/tests/README.md](backend/tests/README.md)
