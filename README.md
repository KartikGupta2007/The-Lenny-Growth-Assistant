# The Lenny Growth Assistant

A full-stack conversational AI application that answers product and growth
questions using knowledge from [Lenny's Podcast](https://www.lennyspodcast.com/),
grounded in the
[ChatPRD/lennys-podcast-transcripts](https://github.com/ChatPRD/lennys-podcast-transcripts)
corpus (303 episode transcripts).

Answers cite the episodes they came from, follow-up questions keep session
context, and the assistant can turn what it finds into a Ship 30 for 30-style
essay or a rendered Markdown / HTML artifact shown beside the chat.

> **Implementation status — the whole backend conversation path works:
> ingestion, embeddings, retrieval, grounded generation, and persistent
> sessions.** The Ship 30 skill, artifacts and the chat UI are not yet built.
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
| [evals/](evals/) | Retrieval evaluation set — the foundation for measuring relevance |

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

`DATABASE_PROBE_TIMEOUT_SECONDS` bounds that check and defaults to 10s, which
is calibrated for a *remote* database: establishing a pooled TLS connection to
a managed PostgreSQL in another region measures ~6.5s from a developer machine,
and a pooled follow-up query ~1.6s. So the first `/health` after startup is
slow and every one after it is fast. If an orchestrator's health-check timeout
is tighter than that first connection, warm the pool at startup rather than
lowering this value — a ceiling below the real connection cost cancels the
attempt before it can enter the pool, which makes *every* probe fail.

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

### Conversations

No authentication, by design (PRD section 5.2). A client sends its own
identifier in `X-User-Id` and keeps it in browser storage; requests without one
share a single anonymous user. **The header identifies, it does not
authenticate** — it is not a security boundary, and one user's conversation is
reported as `not_found` to another rather than `forbidden`, because without
authentication there is no identity to deny.

| | |
| --- | --- |
| `POST /api/sessions` | start a conversation → 201 |
| `GET /api/sessions` | this user's conversations, most recently active first |
| `GET /api/sessions/{id}` | the conversation and its messages, oldest first |
| `POST /api/sessions/{id}/messages` | ask a question, get a grounded answer |

```bash
SID=$(curl -sX POST localhost:8000/api/sessions -H "X-User-Id: $UID" | jq -r .id)

curl -X POST localhost:8000/api/sessions/$SID/messages \
  -H "X-User-Id: $UID" -H 'Content-Type: application/json' \
  -d '{"message": "What does Lenny say about product-market fit?", "provider": "anthropic"}'
```

```jsonc
{
  "message": { "id": "…", "role": "assistant", "content": "Based on the evidence…",
               "created_at": "…" },
  "sources": [ { "number": 1, "document_id": "…", "chunk_id": "…",
                 "title": "…", "guest": "Christopher Lochhead",
                 "source_url": "https://www.youtube.com/watch?v=…",
                 "chunk_index": 22 } ],
  "grounded": true,
  "provider": "anthropic"
}
```

`message` is 1–2000 characters after trimming. `provider` is optional. Unknown
session → `not_found`; unknown provider → `validation_error`; unavailable
provider → `provider_unavailable`; timeout → `model_timeout`.

There is no stateless `POST /api/chat` any more. Nothing consumed it, and one
conversation path is easier to reason about than two.

### Grounded answers

```
question → retrieval → evidence check → grounded context → selected LLM → answer + sources
```

**Insufficient evidence stops generation.** When retrieval reports
`sufficient: False`, the model is **never called** and a fixed response is
stored and returned with `grounded: false` and no sources:

```
"I don't have enough information in Lenny's Podcast transcripts to answer that confidently."
```

A model that is not asked cannot invent an answer. This is the application's
main anti-hallucination control, and it costs a few seconds instead of a
generation.

**The backend owns the sources.** They are built from the retrieval result, not
parsed out of the model's text. The evidence block shows the model numbered
passages with episode and guest only — **no URLs and no database ids** — so the
model has no URL to echo and nothing to fabricate a citation from. It may write
`[2]`; the metadata behind `[2]` is the backend's.

**Only the evidence is sent.** The model receives the system prompt, the
retrieved chunks, the question, and at most the last 6 turns. Never the corpus,
never the database, never any credential.

The grounding prompt is ~10 lines in
[`app/agent/prompts.py`](backend/app/agent/prompts.py): answer from the
evidence only, do not invent facts or URLs, cite what you use, say what the
evidence does not cover.

### Follow-up questions

Earlier turns are loaded and passed to the model, capped at 6 so a long thread
cannot crowd out the evidence. **Retrieval always runs on the current question
alone** — a follow-up is searched for what it asks, not for the whole
conversation. There is no query rewriting.

### Transactions

Generation takes 15–80 seconds. A database transaction is never held across it:

```
load history + save the question  → commit
retrieve                          → close
generate                          (no database connection held)
save the answer                   → commit
```

Each step gets its own short-lived session. If generation fails, the question
stays persisted and there is no assistant message — a gap the user can retry,
rather than a fabricated success. There is a test for exactly that.

### Persisted provenance

Assistant messages store the sources they were grounded in, so reopening a
conversation restores its citations. `GET /api/sessions/{id}` returns each
message with `sources`, `grounded` and `provider` already populated — the
frontend renders source chips without reconstructing anything.

```jsonc
// messages.metadata (JSONB, nullable)
{
  "sources": [
    { "number": 1, "chunk_id": "…", "document_id": "…",
      "title": "Pricing your AI product… | Madhavan Ramanujam",
      "guest": "Madhavan Ramanujam",
      "source_url": "https://www.youtube.com/watch?v=…",
      "chunk_index": 20 }
  ],
  "grounded": true,
  "provider": "anthropic"
}
```

**Metadata only.** The passages stay in `chunks` rather than being copied into
every message that cited them — stored provenance averages ~640 bytes per
assistant turn. A declined turn stores `{"sources": [], "grounded": false,
"provider": null}`.

The column is nullable: user turns and messages written before revision `0002`
have none, and both come back as `sources: []`, `grounded: null`,
`provider: null`.

---

## Ingestion

Ingestion is an **explicit offline command**. It is never triggered by a user
request: the corpus is indexed ahead of time, and a chat request only ever
embeds the user's own question.

```bash
cd backend
source .venv/bin/activate

python -m app.ingestion.sync --limit 10   # first 10 transcripts, for development
python -m app.ingestion.sync              # the whole corpus (303 episodes)
python -m app.ingestion.sync --force-sync # re-download the repository
```

```
GitHub tarball -> .transcript-cache/ -> parse -> clean -> chunk -> documents + chunks
```

`chunks.embedding` is left **NULL** — filling it is a separate command, below.

### Pipeline

| Module | Job |
| --- | --- |
| [`loader.py`](backend/app/ingestion/loader.py) | Downloads the repo tarball into `TRANSCRIPT_CACHE_DIR`, finds `episodes/*/transcript.md` |
| [`parser.py`](backend/app/ingestion/parser.py) | YAML frontmatter → metadata, body → cleaned text, file → sha256 |
| [`chunker.py`](backend/app/ingestion/chunker.py) | Paragraph packing with overlap |
| [`sync.py`](backend/app/ingestion/sync.py) | CLI, incremental logic, progress logging |

The cache exists so a rerun does not re-download 8 MB. It is an implementation
detail of ingestion — gitignored, and never exposed through the API.

**Discovery is specific, not greedy.** Only `episodes/*/transcript.md` counts.
The repository also contains `index/` (91 topic files), `scripts/` and two
root READMEs, none of which are transcripts.

### Metadata

Taken from each transcript's frontmatter — nothing is invented:

| Column | Source |
| --- | --- |
| `title` | `title`, else the `# ` heading, else the episode directory name |
| `guest` | `guest` |
| `source_url` | `youtube_url`, else `spotify_url` |
| `publish_date` | `publish_date` |
| `source_path` | `episodes/<slug>/transcript.md` |
| `content_hash` | sha256 of the raw file |

Real gaps in the corpus, handled rather than faked: 4 episodes have no
`youtube_url`, 3 have no `publish_date`, 1 has no `title`, and 1 uses Spotify
instead of YouTube. Those columns are nullable and stay null.

### Cleaning

Formatting only — the wording is left alone:

- the `# title` / `## Transcript` header block is dropped
- `Casey Winters (00:12):` becomes `Casey Winters:` — the timestamp is noise
  for retrieval, but *who said it* is part of the answer
- bare `(02:22):` continuation markers are removed
- non-breaking spaces, trailing whitespace and runs of blank lines are normalised

### Chunking

`CHUNK_TARGET_TOKENS=600`, `CHUNK_OVERLAP_TOKENS=80`.

Whole paragraphs are packed into a chunk until it reaches the target, then the
tail of that chunk is carried into the next one so a passage split across a
boundary is retrievable from either side. A paragraph longer than the target is
split into overlapping windows — one transcript in the corpus is a single
16,914-word paragraph with no breaks at all, which is why that branch exists.

Words stand in for tokens. A real tokeniser would be more precise, but it is
another dependency for a bound that only needs to be roughly right: chunks sit
well inside the embedding model's context either way. In practice this produces
~28 chunks per episode.

### Incremental refresh

`content_hash` decides the work, per PRD section 9:

| Source state | Action |
| --- | --- |
| New transcript | create document, create chunks |
| Hash unchanged | **skip** — no re-chunking |
| Hash changed | update document, **replace** its chunks |
| File gone from the repo | delete document; chunks cascade |

Chunks are replaced rather than updated because boundaries move when the text
changes, so old chunk indexes cannot be reused.

Each transcript commits in its own transaction, so an interrupted run keeps the
work it finished and a rerun resumes from there.

**Pruning is skipped under `--limit`.** A limited run only sees the first N
transcripts, so every transcript past the limit would otherwise look as though
it had been deleted from the repository.

### Embeddings

A second explicit offline command turns stored chunks into vectors. Ingestion
creates chunks; this fills in the column it left NULL.

```bash
python -m app.ingestion.embed --limit 32   # only the corpus's first 32 chunks
python -m app.ingestion.embed              # every chunk without an embedding
```

```
chunks WHERE embedding IS NULL → Ollama nomic-embed-text → vector(768) → chunks.embedding
```

- **Ollama provides embeddings locally.** No API key, no cloud egress, no
  per-token cost for indexing the corpus.
- **`nomic-embed-text` produces 768-dimensional vectors**, stored in Neon
  PostgreSQL via pgvector.
- **Only chunks where `embedding IS NULL` are read.** A normal user query never
  regenerates the corpus — that would be the query's own embedding, which is
  the retrieval phase.
- **Batched.** `EMBEDDING_BATCH_SIZE=32` chunks go to Ollama in one request via
  `/api/embed`, never one request per chunk. The final short batch is handled.
- **Validated before storage.** Every returned vector must be exactly
  `Settings.embedding_dimensions` wide — derived from `EMBEDDING_MODEL`, not
  hard-coded. A wrong width raises rather than writing a corrupt vector.

**What `--limit N` means:** the run is scoped to the **first N chunks in corpus
order**, and of those, only the ones still missing an embedding are sent. It is
not "N units of work". That distinction matters: rerunning the same limit is a
no-op rather than a step through the backlog, so the command is idempotent at
every limit and not only on a full run.

```
first run   --limit 3  → embedded 3
rerun       --limit 3  → embedded 0   (nothing left in that window)
widen       --limit 10 → embedded 7   (the first 3 are not redone)
```

**Failure is explicit.** Each batch commits on its own, so an interrupted run
keeps what succeeded and leaves the rest NULL for a rerun to finish. A failure
prints the reason and exits non-zero — it never reports success:

```
Embedding failed: Ollama is not reachable. Start it with `brew services start ollama`.
Embedding failed: Ollama rejected the request: model X is not installed. Pull it with `ollama pull X`.
```

### Retrieval

```
query → query embedding → pgvector cosine search → relevance threshold → top-k chunks + provenance
```

Retrieval finds evidence. It does **not** generate an answer — that is the next
phase.

```bash
cd backend
python -m app.retrieval.search "how should a startup think about product-market fit?"
```

That CLI is a debug tool, not API surface. Retrieval is a callable service
([`app/retrieval/retriever.py`](backend/app/retrieval/retriever.py)) which the
agent layer will use:

```python
result = await retrieve(session, "how do I improve retention?")
result.sufficient   # False when there is too little relevant material
result.chunks        # ordered nearest-first, each with full provenance
```

**Document embeddings are generated offline; query embeddings at query time.**
A question embeds only itself — one small Ollama call — and the corpus is never
re-embedded to answer it.

**pgvector performs the search.** The `ORDER BY embedding <=> :query LIMIT k` is
served by the HNSW index; no embeddings are loaded into Python and no cosine
similarity is computed there. Confirmed with `EXPLAIN`:

```
Limit
  ->  Index Scan using ix_chunks_embedding_hnsw on chunks
        Order By: (embedding <=> '[...]'::vector)
```

The `RETRIEVAL_MAX_DISTANCE` filter rides along as a filter over that ordered
scan — also verified with `EXPLAIN` to keep using the index. It is safe in SQL
because rows arrive in distance order, so nothing past the threshold could have
matched.

**Each result carries what a citation needs:** `chunk_id`, `document_id`,
`content`, `chunk_index`, `distance`, `title`, `guest`, `source_url`,
`source_path`.

### Insufficient evidence

Two settings decide whether the evidence is good enough:

| Setting | Effect |
| --- | --- |
| `RETRIEVAL_TOP_K=8` | at most 8 chunks |
| `RETRIEVAL_MAX_DISTANCE=0.45` | chunks farther than this cosine distance are dropped |
| `RETRIEVAL_MIN_CHUNKS=2` | fewer than this many survivors ⇒ `sufficient: False` |

**Insufficient evidence is preferred over unsupported retrieval.** An
off-corpus question returns `sufficient: False` rather than the nearest vector
dressed up as an answer. The result still carries whatever was found so the
caller can log the near-miss — it just must not answer from it.

The threshold was **measured, not guessed.** Against [`evals/`](evals/) on the
full 9,842-chunk corpus, the best match for a question the corpus answers sits
at 0.18–0.37; for an off-corpus question it sits at 0.49–0.52. `0.45` falls in
the empty band between the two:

| threshold | on-corpus hits | off-corpus refused |
| --- | --- | --- |
| 0.62 *(original)* | 11/20 | **0/3** |
| 0.50 | 11/20 | 2/3 |
| **0.45** | **11/20** | **3/3** |
| 0.40 | 10/20 | 3/3 |

At 0.62 nothing was ever refused — with ~10k chunks, *something* is always
within 0.62, which made insufficient-evidence unreachable in practice.

---

## Database

PostgreSQL with pgvector holds two groups of data that are deliberately
unrelated: a conversation does not own transcript rows, and re-ingesting the
corpus does not touch anybody's conversation.

```
APPLICATION                          KNOWLEDGE BASE

users                                documents
  └── sessions                         └── chunks
        ├── messages                         └── embedding vector(768)
        └── artifacts ──┐
                        │
        messages ───────┘  (nullable: which turn produced the artifact)
```

| Table | Holds | Key constraints |
| --- | --- | --- |
| `users` | Anonymous user + JSONB `metadata` | — |
| `sessions` | One conversation | `user_id` → users, **CASCADE** |
| `messages` | One turn: `role`, `content` | `session_id` → sessions **CASCADE**; `role` CHECK-constrained to user/assistant/system |
| `artifacts` | Generated Markdown or HTML | `session_id` **CASCADE**; `message_id` **SET NULL**; `type` CHECK-constrained to markdown/html |
| `documents` | One episode transcript + provenance | `source_path` **UNIQUE** (stable identity); `content_hash` indexed |
| `chunks` | A retrievable slice + its embedding | `document_id` **CASCADE**; `(document_id, chunk_index)` **UNIQUE**; HNSW index on `embedding` |

Decisions worth knowing:

- **UUID primary keys.** An anonymous user's id is minted by the client and
  kept in its own browser, so an id must be generatable without a database
  round-trip.
- **`documents.source_path` is the identity, not `content_hash`.** The path is
  what survives a re-ingest. `content_hash` is indexed but *not* unique: two
  episodes with identical text would be surprising, not a constraint violation,
  and failing an ingest over it would be wrong. `DocumentRepository.upsert`
  returns `(document, changed)` — `changed` is the signal that makes refresh
  incremental.
- **`messages.created_at` defaults to `clock_timestamp()`, not `now()`.**
  `now()` returns the *transaction* start time, so a user turn and the
  assistant reply written in one request would share a timestamp and the
  conversation could come back reversed. Reads order by `(created_at, id)` so
  the ordering is total.
- **`artifacts.message_id` is SET NULL, not CASCADE.** Deleting a message
  should not destroy a document the user may still have open beside the chat.
- **HNSW, not IVFFlat, for the vector index.** IVFFlat derives its lists from
  the rows present when the index is built, and the table is empty at migration
  time, so it would build a useless index. Cosine distance, matching
  `RETRIEVAL_MAX_DISTANCE`.
- **The vector width comes from `Settings.embedding_dimensions`**, in both the
  model and the migration — never a literal. A database built from the
  migration therefore always matches the configured `EMBEDDING_MODEL`. The
  consequence is deliberate: changing `EMBEDDING_MODEL` against an *existing*
  database needs its own migration plus a re-ingest, because the stored vectors
  are the wrong width.
- **Timestamps are all `TIMESTAMP WITH TIME ZONE`**, asserted by a test that
  fails on any timezone-naive column.

### Migrations

Alembic is the source of truth. `create_all()` is never called — not in the
app, not in tests — so the schema a developer has is the schema the migrations
produce.

```bash
cd backend
python -m alembic upgrade head      # apply
python -m alembic current           # what is applied
python -m alembic downgrade base    # back out (reversible)
python -m alembic upgrade head --sql  # review the SQL without running it
```

The DSN is **not** in `alembic.ini`. `alembic/env.py` reads it from application
settings, so one place knows it and no credential is committed.

`tests/test_migrations.py` compares the migrated database against the models
and fails on any difference. Without that test, editing a model without writing
its migration would pass every other test in the suite — because those tests
run on a schema built by the same missing migration — and then fail on deploy.

### Repositories

No route handler builds a query. `app/db/repositories/` owns all SQL:

| Repository | Operations |
| --- | --- |
| `UserRepository` | `create`, `get`, `get_or_create` |
| `SessionRepository` | `create`, `get`, `list_by_user`, `touch` |
| `MessageRepository` | `create`, `list_by_session` |
| `ArtifactRepository` | `create`, `get`, `list_by_session` |
| `DocumentRepository` | `create`, `upsert`, `get`, `get_by_source_path`, `list_by_content_hash`, `mark_ingested` |
| `ChunkRepository` | `bulk_insert`, `list_by_document`, `count_by_document`, `delete_by_document` |

Repositories do not own transactions. `app.db.session.get_session` commits on a
successful request and rolls back on failure, so a handler can call several
repositories and get one atomic unit of work. Repositories only `flush`, and
only when they need the database to assign something before returning.

`SessionRepository.touch` issues an explicit `UPDATE` rather than mutating a
loaded row: the ORM's `onupdate` fires only when some other column changed, so
adding a message to a conversation would otherwise leave `updated_at` stale and
break the sidebar's ordering.

---

## Constants

| File | Holds |
| --- | --- |
| [`backend/app/constants.py`](backend/app/constants.py) | Provider ids, error codes, routes, message roles, artifact types, and configuration defaults |
| [`frontend/src/constants.ts`](frontend/src/constants.ts) | The frontend half of those contracts |

The rule is *shared or contractual*, not *every literal*. A value used once and
obvious from its call site stays where it is used — a one-off HTTP path, an SQL
string, a column length. Table names live on the model's `__tablename__`, UI
copy lives in the component that renders it, and error messages stay on the
exception class in `app/errors.py` because the message is part of that class's
contract. Environment-driven configuration lives in
[`config.py`](backend/app/config.py); `constants.py` holds only its defaults.

Provider ids, error codes and route paths appear on **both** sides. Those are
API contracts, and changing one alone breaks the pair silently — the UI stops
matching a code, or requests a route that no longer exists.
`tests/test_constants.py` parses `constants.ts` and asserts the two agree, so
drift fails the test suite instead of the browser. It also asserts that no
module outside `config.py` reads the environment.

--- | --- |
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

Current state — **127 tests, all passing**:

| File | Covers |
| --- | --- |
| `tests/test_api.py` | Health (ok + degraded), request-id correlation, security headers, docs disabled in production, structured error envelope, no internal detail leaked on unhandled errors |
| `tests/test_config.py` | Embedding-dimension derivation, unmapped-model failure, list parsing (CSV + JSON), env policy switches, production CORS guard, secret redaction in `repr` |
| `tests/test_providers.py` | Provider availability in each environment, Ollama disabled but still reported in production, default fallback, server-side rejection, missing/blank API key, Ollama tag matching, `GET /api/providers` payload |
| `tests/test_constants.py` | Backend/frontend constant drift (provider ids, kinds, error codes, routes), immutable shared containers, no `os.environ` read outside `config.py` |
| `tests/test_persistence.py` | Every repository against real PostgreSQL: users, sessions, messages and their ordering, artifacts, documents, content-hash lookup and upsert semantics, chunks, provenance join, the vector column, cascades and foreign keys |
| `tests/test_migrations.py` | Zero drift between migrations and models, single head, tables, foreign-key delete actions, indexes, HNSW method and operator class, pgvector extension, timezone-aware timestamps |
| `tests/test_ingestion.py` | Discovery (and what it ignores), frontmatter parsing, metadata gaps, cleaning, chunk order/overlap/determinism, oversized paragraphs, invalid transcripts, content hashing, skip-unchanged, reprocess-changed, removal cleanup, `--limit` behaviour, NULL embeddings |
| `tests/test_embeddings.py` | Provider batching and dimension validation, unreachable/timeout/missing-model errors, no credentials in errors, NULL-only selection, persistence, idempotence, `--limit` window semantics, per-batch failure safety |
| `tests/test_retrieval.py` | Query embedded (and only the query), exact cosine distances, ordering, `top_k`, threshold filtering, minimum-chunk rule, insufficient evidence, provenance, HNSW index used, corpus unmodified, provider failure propagation |
| `tests/test_agent.py` | Retrieval before generation, evidence reaches the model, no ids or URLs sent to it, sources come from retrieval not the model, LLM never called on insufficient evidence, deterministic decline, history passed and capped, Ollama + Claude generation via mock transports, timeout/empty/auth failures |
| `tests/test_sessions.py` | Session create/list/get, user isolation, unknown session, both turns persisted, message ordering, follow-up history, retrieval uses the current question, decline persisted, failed generation leaves no assistant message and can be retried, validation, no credential in a response |

The frontend has its own gate, run by `npm run lint` and `npm run build`:
`scripts/check-boundary.mjs` — see [The frontend boundary](#the-frontend-boundary).

Model-provider tests stub the Ollama probe and contact no cloud provider, so
they pass on a machine with no daemon running. Settings are built with
`_env_file=None`, so a local `backend/.env` cannot change what the suite
asserts.

**Database tests run against real PostgreSQL and are never skipped.** The point
of the schema is its constraints, cascades and vector column, and none of those
exist in a stand-in — while a skipped constraint test is indistinguishable from
a passing one in CI output. An unreachable database fails the run with the
command needed to fix it.

The suite picks its database in this order:

```bash
# 1. An explicit test database — point this at a Neon test branch to run
#    against the same engine production uses.
TEST_DATABASE_URL=postgresql+psycopg://user:pw@host/db python -m pytest

# 2. Otherwise a local lenny_growth_assistant_test
python -m pytest
```

`DATABASE_URL` is *overwritten* in the test environment rather than defaulted,
so the suite can never reach the application database in `backend/.env` — these
fixtures create and drop schema. Each test runs inside a transaction that is
rolled back, so the schema is migrated once per session rather than per test.

---

## Implementation status

Phases follow the plan in [PRD.md](PRD.md) section 23.

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Repo structure, FastAPI app, config, DB connection, logging, error contract, health endpoint, frontend scaffold, first tests | **Complete** |
| 1b | Model provider abstraction, availability probing, environment policy, `GET /api/providers`, frontend model selector | **Complete** |
| 2 | Database schema, Alembic migrations, repository layer, persistence tests | **Complete** |
| 3 | Transcript ingestion: repo sync, parsing, cleaning, chunking, incremental refresh | **Complete** |
| 3b | Embedding generation: local Ollama, batched, validated, incremental | **Complete** |
| 4 | Retrieval: query embedding, pgvector similarity search, relevance threshold, provenance | **Complete** |
| 5 | Grounded generation: agent, prompt, `POST /api/chat`, source attribution | **Complete** |
| 6 | Session + message persistence, session API | **Complete** |
| 6b | Conversational UI, source display, provider selection in chat | Not yet implemented |
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
│   │   └── db/               # base, models, session, repositories/
│   ├── alembic/              # migration environment + versions/
│   ├── alembic.ini
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
(`retrieval/`, `ingestion/`, `agent/`, `artifacts/`) are created when the code
that fills them is written, rather than sitting empty.

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
