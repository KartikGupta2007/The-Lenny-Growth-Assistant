# The Lenny Growth Assistant

A full-stack conversational AI application that answers product and growth
questions using knowledge from [Lenny's Podcast](https://www.lennyspodcast.com/),
grounded in the
[ChatPRD/lennys-podcast-transcripts](https://github.com/ChatPRD/lennys-podcast-transcripts)
corpus (303 episode transcripts).

Answers cite the episodes they came from, follow-up questions keep session
context, and the assistant can turn what it finds into a Ship 30 for 30-style
essay or a rendered Markdown / HTML artifact shown beside the chat.

> **Implementation status — foundation + model provider layer complete.**
> This README documents only what is actually built and verified. Sections
> marked *Not yet implemented* are planned but absent. See
> [Implementation status](#implementation-status) for the full breakdown.

---

## Documents

| Document | Purpose |
| --- | --- |
| [PRD.md](PRD.md) | Product requirements, scope, success metrics, acceptance criteria |
| [design.md](design.md) | UI/UX design, information architecture, interaction states |
| [architecture.md](architecture.md) | System architecture, data model, component boundaries, trade-offs |

---

## Architecture at a glance

```
Frontend (React + Vite)
      │  HTTP, JSON only — no model or database access
      ▼
FastAPI  ── api/ ── validation, sessions, structured errors
      │
      ▼
Agent layer  ── router → RAG tool | Ship 30 skill | artifact skill
      │
      ├──► Retrieval  ── query embedding → pgvector similarity search
      │
      └──► Model provider  ── OllamaProvider | CloudModelProvider
                 │
                 ▼
        PostgreSQL + pgvector
```

The frontend never calls an LLM, never queries the database and holds no
credentials — it speaks only to the FastAPI backend, which owns every
downstream call. This is enforced, not just documented: see
[The frontend boundary](#the-frontend-boundary). Ingestion is an explicit
offline command, never triggered by a chat request.

---

## Prerequisites

| Requirement | Version verified | Notes |
| --- | --- | --- |
| Python | 3.14.7 | 3.11+ expected to work; 3.14 is what this was built and tested on |
| Node.js | 26.7 | 20+ expected to work |
| PostgreSQL | 18.4 | Must have the `pgvector` extension available |
| pgvector | 0.8.6 | `brew install pgvector` |
| Ollama | 0.33.0 | Required — serves both the local LLM **and** embeddings by default |

No cloud API key is required. The default configuration runs entirely locally.

### macOS setup of the system dependencies

```bash
brew install postgresql@18 pgvector ollama
brew services start postgresql@18
brew services start ollama

# Local LLM (generation) and embedding model
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

`llama3.1:8b` is ~4.9 GB and `nomic-embed-text` ~274 MB. Ingesting the full
corpus needs roughly a further 300 MB of disk.

---

## Setup

### 1. Database

```bash
createdb lenny_growth_assistant
psql -d lenny_growth_assistant -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Test database, used by the automated tests
createdb lenny_growth_assistant_test
psql -d lenny_growth_assistant_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

A Homebrew PostgreSQL install has no `postgres` role — it creates a superuser
matching your macOS username. The default `DATABASE_URL` therefore omits the
username so psycopg falls back to your OS user. For a managed or Linux
instance, set the explicit form in `backend/.env`:

```
DATABASE_URL=postgresql+psycopg://user:password@host:5432/lenny_growth_assistant
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # defaults work as-is for a fully local run
```

### 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env
```

---

## Running

Two terminals:

```bash
# Terminal 1 — API on http://localhost:8000
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

```bash
# Terminal 2 — UI on http://localhost:5173
cd frontend
npm run dev
```

Verify the backend and its dependencies:

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "environment": "development",
  "dependencies": [{ "name": "database", "healthy": true, "detail": null }]
}
```

`/health` returns HTTP 503 with `"status": "degraded"` when a required
dependency is unreachable, so "up" and "up but unusable" are distinguishable.

Interactive API docs are served at <http://localhost:8000/docs>.

---

## The frontend boundary

The frontend talks to the FastAPI backend and to nothing else. No database, no
model provider, no third-party service, no CDN. Every credential and every
downstream call lives in the backend.

That rule is one careless line away from being broken — a `fetch` to a vendor
endpoint, a `VITE_API_KEY` that ships the secret to every browser that loads
the page — so it is checked rather than trusted:

```bash
cd frontend
npm run check:boundary
```

It also runs as part of `npm run lint` **and** `npm run build`, so a violation
cannot reach a bundle. [`scripts/check-boundary.mjs`](frontend/scripts/check-boundary.mjs)
has no dependencies and enforces six rules:

| Rule | Why |
| --- | --- |
| `fetch` / `XMLHttpRequest` / `WebSocket` / `EventSource` / `sendBeacon` / `new Worker` only in [`src/api/client.ts`](frontend/src/api/client.ts) | One chokepoint owns the base URL, timeout and error envelope |
| Absolute URLs only in [`src/constants.ts`](frontend/src/constants.ts) | The frontend has exactly one remote host: the backend |
| `import.meta.env` read only in `src/constants.ts` | Configuration is resolved once, so there is one place to audit |
| No `VITE_` name matching `KEY`/`SECRET`/`TOKEN`/`PASSWORD`/`DSN`/`DATABASE`/… | Every `VITE_` variable is compiled into the public bundle |
| No DB driver, ORM, model SDK or agent framework in `package.json` | An unused dependency is still an invitation |
| No external asset in `index.html` | Everything is bundled and self-hosted |

Comments are excluded by a character scanner rather than a regex, because a
regex cannot tell the `//` in `https://` from the start of a line comment —
and getting that wrong silently swallows the rest of the line.

The current tree passes with exactly **one** `fetch` (in the API client), one
absolute URL (the backend's default base URL), one env var
(`VITE_API_BASE_URL`), and two runtime dependencies (`react`, `react-dom`).

---

## Constants

Every fixed value lives in one module per half of the stack:

| File | Holds |
| --- | --- |
| [`backend/app/constants.py`](backend/app/constants.py) | Every literal the backend uses: defaults, routes, error codes, provider ids and labels, security headers, SQL, log keys |
| [`frontend/src/constants.ts`](frontend/src/constants.ts) | The frontend equivalent, plus all fixed UI copy |

Neither imports from the rest of its package, so they can be imported anywhere
without a cycle. Shared containers are tuples/frozensets, so a caller cannot
mutate shared state by accident.

The rule: a value used in more than one module — or one a reader would have to
guess the meaning of at its call site — is named there. User-facing *error*
prose stays on the exception class in `app/errors.py`, because the message is
part of that class's contract; only the machine-readable `code` is shared.

Provider ids, error codes and route paths appear on **both** sides. Those are
API contracts, and changing one alone breaks the pair silently — the UI stops
matching a code, or requests a route that no longer exists. `tests/test_constants.py`
parses `constants.ts` and asserts the two agree, so drift fails the test suite
instead of the browser. It also asserts that no module outside `config.py`
reads the environment.

---

## Configuration

All configuration is environment-driven; no module reads `os.environ`
directly. See [`backend/.env.example`](backend/.env.example) for the annotated
list and [`frontend/.env.example`](frontend/.env.example) for the frontend.

Real `.env` files are gitignored. No secrets are committed.

### Model providers

Generation and embeddings are configured independently: the LLM may be local
or cloud, the embedding model is always local.

```bash
LLM_PROVIDER=ollama          # or: anthropic
EMBEDDING_PROVIDER=ollama    # Ollama only
```

Generation is switchable; **embeddings always run on Ollama**. Keeping them
local means the corpus can be ingested with no API key, no cloud egress and no
per-token cost, and the vector width never changes underneath an existing
index because of a vendor default. Setting `EMBEDDING_PROVIDER` to anything
else is rejected at startup rather than silently ignored.

The default is fully local and needs no API key.

`GET /api/providers` reports **every** provider with an `available` flag and,
when unavailable, a user-facing `reason`. The UI renders all of them and
disables the ones that are not available, so an option is never silently
dropped between environments — the user can see that a local model exists and
read why it is not offered here.

```jsonc
// APP_ENV=production
{
  "providers": [
    { "id": "ollama",    "label": "Ollama", "kind": "local", "model": "llama3.1:8b",
      "available": false,
      "reason": "Ollama runs on the machine hosting the API and is not available in this environment. Use a cloud model instead." },
    { "id": "anthropic", "label": "Claude", "kind": "cloud", "model": "claude-sonnet-5",
      "available": true, "reason": null }
  ],
  "default": "anthropic"
}
```

**What `APP_ENV` changes**

| | `development` / `test` | `production` |
| --- | --- | --- |
| Ollama (local) | selectable when reachable | **shown, disabled**, with reason |
| Claude (cloud) | selectable when a key is set | selectable when a key is set |
| `/docs`, `/openapi.json` | served | not served |
| `CORS_ORIGINS=*` | allowed | rejected at startup |

A local provider is disabled in production because the hosted API has no
Ollama daemon (architecture.md section 22). Set `ENABLE_LOCAL_PROVIDERS=true`
only for a self-hosted deployment that really does run one.

Two further behaviours matter operationally:

- **Server-side enforcement.** Disabling the option in the UI is a courtesy,
  not a control. `ProviderRegistry.require()` re-checks on every generation
  request, so a hand-crafted call asking for `ollama` in production is refused
  with `provider_unavailable`.
- **Safe default.** If `LLM_PROVIDER` names an unavailable provider, the API
  falls back to the first available one, so shipping `LLM_PROVIDER=ollama` to
  production does not open the app on a dead model.

### Embedding model and vector width

The embedding model fixes the width of the pgvector column, so it cannot be
changed without re-ingesting:

| Model | Dimensions | Size |
| --- | --- | --- |
| `nomic-embed-text` (default) | 768 | 274 MB |
| `mxbai-embed-large` | 1024 | 670 MB |

An unmapped model name fails loudly at startup rather than defaulting to a
wrong width.

---

## Tests

```bash
cd backend
source .venv/bin/activate
python -m pytest
```

Current state — **63 tests, all passing**:

| File | Covers |
| --- | --- |
| `tests/test_api.py` | Health (ok + degraded), request-id correlation, security headers, docs disabled in production, structured error envelope, no internal detail leaked on unhandled errors |
| `tests/test_config.py` | Embedding-dimension derivation, unmapped-model failure, list parsing (CSV + JSON), env policy switches, production CORS guard, secret redaction in `repr` |
| `tests/test_providers.py` | Provider availability in each environment, Ollama disabled but still reported in production, default fallback, server-side rejection, missing/blank API key, Ollama tag matching, `GET /api/providers` payload |
| `tests/test_constants.py` | Backend/frontend constant drift (provider ids, kinds, error codes, routes), immutable shared containers, no `os.environ` read outside `config.py` |

The frontend has its own gate, run by `npm run lint` and `npm run build`:
`scripts/check-boundary.mjs` — see [The frontend boundary](#the-frontend-boundary).

The tests use a separate `lenny_growth_assistant_test` database, stub the
Ollama probe, and contact no cloud provider — so they pass on a machine with
no daemon running. Settings are built with `_env_file=None`, so a local
`backend/.env` cannot change what the suite asserts.

---

## Implementation status

Phases follow the plan in [PRD.md](PRD.md) section 23.

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Repo structure, FastAPI app, config, DB connection, logging, error contract, health endpoint, frontend scaffold, first tests | **Complete** |
| 1b | Model provider abstraction, availability probing, environment policy, `GET /api/providers`, frontend model selector | **Complete** |
| 2 | Database schema; anonymous user / session / message persistence | Not yet implemented |
| 3 | Transcript ingestion: repo sync, parsing, cleaning, chunking, embeddings, incremental refresh | Not yet implemented |
| 4 | Retrieval: query embedding, pgvector search, provenance, grounded context | Not yet implemented |
| 5 | Agent layer, RAG tool, generation on the existing provider abstraction | Not yet implemented |
| 6 | Chat API, conversational UI, source display, provider selection | Not yet implemented |
| 7 | Ship 30 for 30 skill, artifact generation, artifact viewer, HTML sanitisation | Not yet implemented |
| 8 | Error handling hardening, observability, full test suite | Not yet implemented |
| 9 | Documentation sync, clean-environment verification, manual UI test plan | Not yet implemented |

### What Phase 1 delivered

- `backend/app/config.py` — pydantic-settings configuration, no direct
  `os.environ` reads, embedding width derived from the model name
- `backend/app/main.py` — application factory, CORS, per-request `request_id`
  binding, exception handlers for `AppError` / validation / HTTP / unhandled
- `backend/app/errors.py` — typed error hierarchy and the
  `{"error": {"code", "message"}}` contract
- `backend/app/logging_config.py` — structlog with a secret-redaction
  processor; console rendering in development, JSON elsewhere
- `backend/app/db/session.py` — async engine for requests, sync engine for
  batch ingestion, connectivity + pgvector probe
- `backend/app/api/health.py` — dependency-aware health endpoint
- `frontend/src/api/client.ts` — the single frontend/backend boundary,
  translating the error envelope into typed errors, with per-request timeouts
- `frontend/src/index.css` — design tokens per design.md section 24

### What the provider layer delivered

- `backend/app/models/base.py` — `ModelProvider` abstraction separating
  *policy* (`is_enabled`) from *reachability* (`check_availability`)
- `backend/app/models/ollama.py` — probes the daemon **and** confirms the
  configured model is pulled, so a running daemon missing `llama3.1:8b` is
  reported as unavailable rather than failing on the first question
- `backend/app/models/cloud.py` — Anthropic provider; availability is
  credential presence, with no per-request round-trip to the vendor
- `backend/app/models/registry.py` — environment policy, TTL-cached probes,
  safe default resolution, and `require()` as the server-side control
- `backend/app/api/providers.py` — `GET /api/providers`
- `backend/app/http.py` — one pooled `httpx.AsyncClient`, closed on shutdown
- `frontend/src/hooks/useProviders.ts` — validates a remembered choice against
  the live list, so a stale `localStorage` value cannot pin the UI to a
  provider that is no longer available
- `frontend/src/components/ModelSelector.tsx` — accessible radio group that
  renders disabled providers with their reason

---

## Project structure

```
the-lenny-growth-assistant/
├── README.md, PRD.md, design.md, architecture.md
├── backend/
│   ├── .env.example, requirements.txt, pytest.ini
│   ├── app/
│   │   ├── main.py           # app factory, middleware, exception handlers
│   │   ├── config.py         # the only module that reads the environment
│   │   ├── constants.py      # every fixed value
│   │   ├── errors.py         # typed errors + the response envelope
│   │   ├── logging_config.py # structlog, secret redaction
│   │   ├── http.py           # one pooled outbound HTTP client
│   │   ├── api/              # HTTP routes only — health, providers
│   │   ├── models/           # provider abstraction: base, ollama, cloud, registry
│   │   └── db/               # session, engines, connectivity probe
│   └── tests/
└── frontend/
    ├── .env.example, package.json
    ├── scripts/              # check-boundary.mjs — enforces the API-only rule
    └── src/
        ├── constants.ts      # every fixed value + UI copy
        ├── api/              # the single backend boundary
        ├── components/       # ModelSelector
        └── hooks/            # useProviders
```

Only what is built is present. The packages for the remaining phases
(`retrieval/`, `ingestion/`, `agent/`, `artifacts/`, `db/repositories/`) are
created when the code that fills them is written, rather than sitting empty.

---

## Design and security notes

- **Grounding.** Retrieved transcript chunks are treated as data, never as
  instructions. When too little relevant material is found, the assistant says
  so instead of answering unsupported. *(Enforced from Phase 4.)*
- **Artifacts.** Generated HTML is untrusted: it is sanitised server-side and
  rendered inside a sandboxed boundary with no access to application state,
  cookies or credentials. *(Phase 7.)*
- **No authentication.** Out of MVP scope by design. Anonymous users get a
  persistent client-side identifier so sessions and history still persist
  independently. *(Phase 2.)*
- **Environment policy is server-side.** The frontend holds no environment
  switch: one bundle behaves correctly everywhere because selectability is
  decided by the API. Client-side disabling is presentation; the registry is
  the control.
- **The frontend has one dependency: the backend.** No database driver, model
  SDK or vendor endpoint, and no credential in the bundle. Enforced by
  `npm run check:boundary` on every lint and build.
- **Secrets.** Never logged — the logging pipeline redacts known-sensitive keys
  — and never committed.
- **Local setup uses a Python virtualenv and npm.** There is no Docker or
  Docker Compose in this implementation.
