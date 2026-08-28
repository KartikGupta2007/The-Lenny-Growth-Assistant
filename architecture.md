Architecture — The Lenny Growth Assistant

1. Architecture Overview

The Lenny Growth Assistant is a full-stack AI application designed around a RAG-based knowledge system, an agent layer, configurable LLM providers, PostgreSQL persistence, and an in-app artifact viewer.

The architecture separates the system into five major concerns:

1. Frontend — conversational UI, sources, model selection, and artifact viewer.
2. FastAPI backend — API layer, sessions, orchestration, validation, and error handling.
3. Agent layer — intent routing, retrieval, essay generation, and artifact generation.
4. Knowledge layer — transcript ingestion, chunking, embeddings, vector retrieval, and provenance.
5. Persistence/Infrastructure — PostgreSQL/pgvector, model providers, logging, and deployment.

The design prioritizes source grounding, clear component boundaries, operational simplicity, and the ability to switch between cloud and local LLM providers without changing application logic.

⸻

2. High-Level Architecture

                              USER
                                │
                                ▼
                    ┌──────────────────────┐
                    │      Frontend        │
                    │     React + Vite     │
                    │                      │
                    │ Chat │ Sources       │
                    │ Model selector       │
                    │ Artifact Viewer      │
                    └──────────┬───────────┘
                               │
                          HTTP (JSON)
                               │
                               ▼
                    ┌──────────────────────┐
                    │       FastAPI        │
                    │                      │
                    │ API / Validation     │
                    │ Session Management   │
                    │ Error Handling       │
                    └──────────┬───────────┘
                               │
                    ┌──────────┴──────────┐
                    │                     │
                    ▼                     ▼
             ┌─────────────┐       ┌─────────────┐
             │    Agent    │       │ PostgreSQL  │
             │    Layer    │       │ + pgvector  │
             └──────┬──────┘       └──────▲──────┘
                    │                     │
          ┌─────────┼─────────┐           │
          │         │         │           │
          ▼         ▼         ▼           │
        RAG      Essay      Artifact      │
        Tool      Skill       Skill       │
          │                               │
          └──────────────┬────────────────┘
                         │
                         ▼
                  Model Provider
                  ┌────────────┐
                  │            │
             Ollama         Cloud LLM
             Local          Claude

⸻

3. Component Boundaries

3.1 Frontend

Responsibilities

* Display conversations.
* Create and switch sessions.
* Send user messages.
* Display assistant responses.
* Display source citations.
* Display model/provider availability.
* Display loading and error states.
* Display generated artifacts beside the chat.
* Render Markdown.
* Render sanitized HTML/CSS artifacts.

Does not own

* LLM calls.
* Retrieval.
* Embedding generation.
* Database access.
* Agent logic.
* Security decisions.

The frontend communicates exclusively with the FastAPI backend.

⸻

4. FastAPI Backend

FastAPI is the primary application/API boundary.

Responsibilities

* HTTP API.
* Request validation.
* Response contracts.
* Session management.
* Message persistence.
* Agent invocation.
* Provider availability.
* Health checks.
* Structured error handling.
* Authentication/authorization boundaries if introduced later.

Example structure

backend/
└── app/
    ├── main.py
    ├── config.py
    ├── api/
    │   ├── sessions.py
    │   ├── chat.py
    │   ├── artifacts.py
    │   └── providers.py
    ├── agent/
    │   ├── router.py
    │   ├── tools/
    │   ├── skills/
    │   └── prompts/
    ├── retrieval/
    │   ├── embeddings.py
    │   ├── retriever.py
    │   └── reranker.py
    ├── models/
    │   ├── llm.py
    │   ├── ollama.py
    │   └── cloud.py
    ├── db/
    │   ├── models.py
    │   ├── session.py
    │   └── repositories/
    ├── artifacts/
    │   ├── generator.py
    │   └── sanitizer.py
    └── ingestion/
        ├── loader.py
        ├── parser.py
        ├── chunker.py
        └── sync.py

The exact implementation structure can change, but the separation of responsibilities should remain.

⸻

5. Agent Layer

The assignment requires the agent layer to use either the Anthropic Claude Agent SDK or Pi Coding Agent.

The agent is responsible for deciding which capability should handle a user request.

Agent routing

                       User Message
                            │
                            ▼
                       Agent Router
                            │
             ┌──────────────┼──────────────┐
             │              │              │
             ▼              ▼              ▼
        Knowledge Q     Essay Request   Artifact Request
             │              │              │
             ▼              ▼              ▼
           RAG Tool      Essay Skill   Artifact Skill

The router should avoid treating every request as a generic generation request.

⸻

6. Agent Capabilities

6.1 RAG Tool

Used for normal product/growth questions.

Responsibilities:

* Understand the user’s query.
* Generate a query embedding.
* Search the vector index.
* Select relevant chunks.
* Return transcript content and provenance.
* Provide grounded context to the LLM.

⸻

6.2 Ship 30 for 30 Skill

Used when the user requests an essay.

Responsibilities:

* Retrieve relevant transcript evidence.
* Apply the defined Ship 30 for 30 writing principles.
* Generate approximately 1,250 words.
* Maintain grounding in retrieved transcript material.
* Produce structured Markdown content.

⸻

6.3 Artifact Skill

Used when the user asks for Markdown or HTML/CSS artifacts.

Responsibilities:

* Understand the requested artifact.
* Use current conversation context.
* Retrieve relevant knowledge when necessary.
* Generate the artifact.
* Pass generated HTML through the security layer.
* Return the artifact to the frontend.

⸻

7. Knowledge Base Architecture

The primary source is:

ChatPRD/lennys-podcast-transcripts

The repository contains Lenny’s Podcast transcript content organized into episode files.

The knowledge base is processed separately from normal chat requests.

GitHub Repository
       │
       ▼
Repository Sync
       │
       ▼
Transcript Parser
       │
       ├──────────────┐
       ▼              ▼
   Metadata        Transcript
                       │
                       ▼
                    Cleaner
                       │
                       ▼
                    Chunker
                       │
                       ▼
                Embedding Provider
                       │
                       ▼
              PostgreSQL + pgvector

⸻

8. Ingestion Pipeline

Implemented. backend/app/ingestion/ -- loader.py, parser.py, chunker.py, sync.py.

Ingestion is an explicit offline command, never part of a user request:

    python -m app.ingestion.sync --limit 10
    python -m app.ingestion.sync

GitHub tarball
       |
       v
.transcript-cache/          (reused across runs; gitignored)
       |
       v
discover episodes/*/transcript.md
       |
       v
parse frontmatter -> title, guest, youtube_url, publish_date
       |
       v
clean body -> drop header block, drop timestamps, normalise whitespace
       |
       v
chunk -> paragraph packing with overlap
       |
       v
documents + chunks in PostgreSQL      (embedding stays NULL)

The repository is fetched as a tarball rather than cloned: one HTTP request, no
git dependency, and nothing to keep in sync. It is extracted with tarfile's
"data" filter, which rejects absolute paths and traversal entries.

Discovery is deliberately narrow. Only episodes/*/transcript.md is a
transcript; the repository also holds index/ (91 topic files), scripts/ and two
root README files. A file that cannot be parsed is logged as
transcript_unreadable, counted as failed, and skipped -- one bad transcript
does not abandon the other 302.

Metadata comes from the frontmatter and nothing is invented. Where the corpus
has genuine gaps -- 4 episodes without youtube_url, 3 without publish_date, 1
without title, 1 with a Spotify link instead -- the columns are nullable and
stay null. Title falls back to the body heading, then the episode directory
name.

Each transcript is committed in its own transaction, so an interrupted run
keeps what it finished and a rerun resumes from there.

Embeddings are not generated here. That is the next phase; chunks are written
with a NULL embedding and the column is populated separately.


9. Chunking Strategy

Long transcripts are divided into smaller retrieval units.

Conceptually:

Episode
   │
   ├── Chunk 1
   ├── Chunk 2
   ├── Chunk 3
   ├── ...
   └── Chunk N

The initial implementation will target approximately:

* 500–800 tokens per chunk
* 50–100 token overlap

These are implementation parameters rather than assignment requirements and should be evaluated against retrieval quality.

Where practical, chunk boundaries should preserve coherent conversational ideas instead of splitting purely by character count.

⸻

10. Embedding Architecture

Implemented. backend/app/embeddings.py and backend/app/ingestion/embed.py.

    chunks WHERE embedding IS NULL
              |
              v
    batches of EMBEDDING_BATCH_SIZE
              |
              v
    Ollama /api/embed  (nomic-embed-text)
              |
              v
    validate width == Settings.embedding_dimensions
              |
              v
    UPDATE chunks SET embedding = ...

Provider boundary:

    EmbeddingProvider (abstract)
              |
              v
    OllamaEmbeddingProvider

One provider today. The abstraction exists because the architecture keeps the
embedding provider replaceable, not because there is a second one -- so it is
an abstract class with one method, embed(texts) -> list[list[float]], and no
registry or factory around it.

Embeddings run locally on Ollama. The model is 274 MB against 4.9 GB for
generation, so the memory argument that pushes generation to the cloud does not
apply, and indexing the corpus costs nothing and needs no API key.

Batching: the provider sends one HTTP request per embed() call, and the command
splits the backlog into EMBEDDING_BATCH_SIZE batches. Never one request per
chunk. The final short batch is handled by the slicing.

Validation before storage: every returned vector must be exactly
Settings.embedding_dimensions wide, which is derived from EMBEDDING_MODEL rather
than hard-coded. A provider returning a different width raises EmbeddingError
and nothing is written -- a wrong-width vector would corrupt retrieval silently
rather than failing.

Idempotence: only chunks where embedding IS NULL are read. Rerunning the
command does no work; a later ingest that adds chunks embeds only those.

Failure safety: each batch is committed on its own transaction after its
vectors validate. A failure keeps the batches that succeeded, leaves the rest
NULL, prints the reason and exits non-zero. The command never reports success
after a failed batch.

Errors reuse the existing typed hierarchy -- EmbeddingError, code
embedding_failed -- rather than introducing a second error system. Messages are
actionable (Ollama not running, model not pulled, timeout, wrong dimension) and
carry no credentials.


11. Vector Storage

Implemented. chunks.embedding is vector(768) with an HNSW index over
vector_cosine_ops, created by Alembic revision 0001. Vectors are written by
python -m app.ingestion.embed and are not yet read -- similarity search is the
retrieval phase.


PostgreSQL with pgvector will be used for semantic retrieval.

A conceptual chunk record:

chunks
────────────────────────────
id
document_id
chunk_index
content
embedding
guest
episode_title
source_url
publish_date
content_hash
created_at
updated_at

The exact database schema may normalize some metadata into a separate documents table.

⸻

12. Provenance

Every retrieved chunk must remain traceable to its original transcript.

Retrieved Chunk
      │
      ▼
document_id
      │
      ▼
Episode
      │
      ├── Guest
      ├── Title
      ├── Publish Date
      └── Source URL

This allows the response to display:

Sources
• Guest Name — Episode Title
  Source: YouTube / transcript

This is important because the assignment requires answers to cite or clearly identify the relevant transcript/source.

⸻

13. Incremental Refresh

Implemented. content_hash on documents is the sha256 of the raw transcript
file, and it decides the work:

    new file        -> create document, create chunks
    hash unchanged  -> skip, no re-chunking
    hash changed    -> update document, replace its chunks
    file removed    -> delete document, chunks cascade

Chunks are replaced rather than updated because chunk boundaries move when the
text changes, so old chunk indexes cannot be reused.

Pruning is skipped when --limit is in effect: a limited run only sees the first
N transcripts, so everything past the limit would otherwise look as though it
had been removed from the repository.


The knowledge base should support refreshing the transcript repository without reprocessing unchanged content.

A content hash will be stored for each source document.

                 GitHub
                   │
                   ▼
             Compare hashes
                   │
          ┌────────┼─────────┐
          │        │         │
       Same      New      Changed
          │        │         │
         Skip    Process   Reprocess
                   │         │
                   └────┬────┘
                        ▼
                    Chunk
                        ▼
                    Embed
                        ▼
                 Update Index

Benefits

* Lower embedding cost.
* Faster synchronization.
* Avoids unnecessary database writes.
* Keeps the knowledge base current.

⸻

14. Runtime Retrieval Flow

Implemented. backend/app/retrieval/retriever.py.

    query
      |
      v
    query embedding            (Ollama nomic-embed-text, one call)
      |
      v
    pgvector cosine search     (ORDER BY embedding <=> query LIMIT k, HNSW)
      |
      v
    RETRIEVAL_MAX_DISTANCE     (drop chunks that are not close enough)
      |
      v
    RETRIEVAL_MIN_CHUNKS       (too few survivors -> sufficient = False)
      |
      v
    top-k chunks + provenance

Document embeddings are generated offline by python -m app.ingestion.embed.
Only the query is embedded at request time, so answering a question costs one
small embedding call and never re-embeds the corpus.

The database does the search. No embeddings are loaded into Python and no
cosine similarity is computed there. EXPLAIN confirms the plan:

    Limit
      ->  Index Scan using ix_chunks_embedding_hnsw on chunks
            Order By: (embedding <=> '[...]'::vector)

The distance threshold is applied in SQL as a filter over that ordered index
scan -- also confirmed by EXPLAIN to keep using the index. It is safe there
because rows arrive in distance order, so nothing beyond the threshold could
have matched.

15. Retrieval Strategy

1. Receive the user question.
2. Embed it with the same model the chunks were embedded with.
3. Search chunks.embedding by cosine distance in PostgreSQL.
4. Take the RETRIEVAL_TOP_K nearest.
5. Drop anything farther than RETRIEVAL_MAX_DISTANCE.
6. If fewer than RETRIEVAL_MIN_CHUNKS survive, report insufficient evidence.
7. Return the chunks with provenance for the agent layer to cite.

Result shape (RetrievedChunk): chunk_id, document_id, content, chunk_index,
distance, title, guest, source_url, source_path. Episode-level provenance comes
from the joined document row, so it cannot drift between chunks of the same
transcript.

Reranking is deliberately absent. Distance ordering plus a relevance threshold
is the whole strategy for now; a reranker is a later decision to be justified by
measurement, not assumed.

Evaluation: evals/retrieval.json holds 23 hand-curated cases -- 20 questions
with a known expected episode and 3 off-corpus questions that must return
insufficient evidence. It is the foundation for PRD section 3's retrieval
relevance target. The metric has not been measured; no scoring harness exists
yet.


16. Grounding Strategy

Implemented. backend/app/agent/.

    question
      |
      v
    retrieval                  (query embedded at request time)
      |
      v
    evidence check             sufficient == False -> STOP, no model call
      |
      v
    grounded context           numbered evidence, episode + guest, no URLs, no ids
      |
      v
    selected LLM               Ollama llama3.1:8b or Claude
      |
      v
    answer + sources           sources built from retrieval, never from the text

Retrieval happens before generation, always. The model is chosen only after the
evidence check passes, so an unavailable provider cannot turn an
insufficient-evidence question into an error.

The evidence check is the primary anti-hallucination control. When retrieval
reports insufficient evidence the model is never invoked and a fixed string is
returned. A model that is not asked cannot answer unsupported. This also makes
the behaviour deterministic and cheap -- roughly a second, versus a generation.

What the model receives:

* the system prompt (~10 lines: answer from the evidence only, do not invent
  facts or URLs, cite what you use, say what the evidence does not cover)
* the retrieved chunks, numbered [1]..[n], each with episode title and guest
* the user's question
* at most the last 6 conversation turns

What the model never receives: the corpus, the database, any credential, any
row id, and any source URL. Withholding URLs is deliberate -- a model cannot
echo a link it never saw, so a fabricated citation has nothing to attach to.

Source attribution is owned by the backend. Answer.sources is built from the
RetrievalResult, in evidence order, so the [2] in the model's prose maps to a
source whose title, guest and URL came from PostgreSQL. LLM-generated URLs are
never trusted, parsed or surfaced.

Conversation history is accepted by the agent (agent.answer_question(...,
history=[...])) and capped, so a long thread cannot crowd out the evidence.
Retrieval always runs on the current question alone: a follow-up is searched
for what it asks rather than for the whole conversation. There is no query
rewriting.

Provider errors map onto the existing typed hierarchy -- ModelTimeoutError,
ModelError, ProviderUnavailableError -- so a timeout is distinguishable from
"pick another model". Messages never include a credential; a rejected Anthropic
key reports that it was rejected without echoing it.


17. Session and Conversation Architecture

Implemented. backend/app/api/sessions.py and answer_in_conversation in
backend/app/agent/agent.py.

    POST /api/sessions                  start a conversation
    GET  /api/sessions                  this user's conversations
    GET  /api/sessions/{id}             the conversation and its messages
    POST /api/sessions/{id}/messages    ask a question, get a grounded answer

No authentication, by design (PRD section 5.2). A client sends its own
identifier in the X-User-Id header and keeps it in browser storage; requests
without one share a single anonymous user row. The header identifies, it does
not authenticate, and it is not a security boundary. Another user's
conversation is reported as not_found rather than forbidden -- without
authentication there is no identity to deny.

Turn flow:

    load recent history + persist the user message   -> commit
    retrieve on the current question                 -> close
    evidence check                                   (insufficient -> no model call)
    generate                                         (no database connection held)
    persist the assistant message                    -> commit

Transaction strategy: generation takes 15-80 seconds, so each step gets its own
short-lived session and no transaction spans the model call. A connection
sitting idle inside a transaction for a minute is a connection the rest of the
application cannot use.

Failure semantics: if generation fails, the user message stays persisted and no
assistant message is written. The request returns the existing typed error. A
gap the user can retry is better than a fabricated assistant success.

An insufficient-evidence decline IS persisted as an assistant message, because
it is part of the conversation the user sees and a reload should show it.

History is capped (MAX_HISTORY_MESSAGES = 6) so a long thread cannot crowd out
the evidence. Retrieval always runs on the current question alone: a follow-up
is searched for what it asks rather than for the whole conversation. There is no
query rewriting.

Source provenance is persisted. Revision 0002 adds a nullable metadata JSONB
column to messages; an assistant turn stores {sources, grounded, provider} so
reopening a conversation restores its citations. GET /api/sessions/{id} returns
each message with those fields already populated.

Metadata only: the retrieved passages stay in chunks rather than being copied
into every message that cited them (~640 bytes per assistant turn). The column
is nullable, so user turns and rows written before 0002 keep working and read
back as no sources.

The column uses JSONB(none_as_null=True). Without it SQLAlchemy stores Python
None as JSON 'null', which would leave two representations of "no provenance"
in one column and make `WHERE metadata IS NULL` blind to half of them.

The stateless POST /api/chat from the previous phase was removed. Nothing
consumed it, and one conversation path is easier to reason about than two.


18. Database Schema

Implemented. Alembic revision 0001 creates the whole schema; SQLAlchemy models
live in backend/app/db/models.py.

Two groups of data, deliberately unrelated to each other. A conversation does
not own transcript rows, and re-ingesting the corpus does not touch anybody's
conversation.

APPLICATION DATA

┌──────────────────────┐
│        users         │
├──────────────────────┤
│ id            uuid PK│
│ metadata      jsonb  │
│ created_at    tstz   │
│ updated_at    tstz   │
└──────────┬───────────┘
           │ 1:N  ON DELETE CASCADE
           ▼
┌──────────────────────┐
│       sessions       │
├──────────────────────┤
│ id            uuid PK│
│ user_id       uuid FK│
│ created_at    tstz   │
│ updated_at    tstz   │
└──────────┬───────────┘
           │ 1:N  ON DELETE CASCADE
           ├──────────────────────────────┐
           ▼                              ▼
┌──────────────────────┐      ┌──────────────────────┐
│      messages        │      │      artifacts       │
├──────────────────────┤      ├──────────────────────┤
│ id            uuid PK│      │ id            uuid PK│
│ session_id    uuid FK│      │ session_id    uuid FK│
│ role          check  │      │ message_id    uuid FK│ ← nullable, SET NULL
│ content       text   │◄─────┤ type          check  │
│ created_at    tstz   │      │ title         varchar│
└──────────────────────┘      │ content       text   │
                              │ created_at    tstz   │
                              │ updated_at    tstz   │
                              └──────────────────────┘

KNOWLEDGE BASE

┌──────────────────────┐
│      documents       │
├──────────────────────┤
│ id            uuid PK│
│ source_path   UNIQUE │  ← stable identity across re-ingests
│ source_url    varchar│
│ title         varchar│  ┐
│ guest         varchar│  ├ provenance shown under an answer
│ publish_date  date   │  ┘
│ content_hash  indexed│  ← drives incremental refresh
│ last_ingested_at tstz│
│ created_at    tstz   │
│ updated_at    tstz   │
└──────────┬───────────┘
           │ 1:N  ON DELETE CASCADE
           ▼
┌──────────────────────────────┐
│            chunks            │
├──────────────────────────────┤
│ id                    uuid PK│
│ document_id           uuid FK│
│ chunk_index           int    │  ┐ UNIQUE together
│ content               text   │  ┘
│ content_hash          indexed│
│ embedding      vector(768)   │  ← HNSW, vector_cosine_ops
│ metadata              jsonb  │
│ created_at            tstz   │
│ updated_at            tstz   │
└──────────────────────────────┘

Constraints and the reasoning behind them:

* Primary keys are UUIDs generated by the application. An anonymous user's id
  is minted by the client and kept in its own browser, so an id must be
  generatable without a database round-trip.
* documents.source_path is UNIQUE and is the document's identity.
  content_hash is indexed but NOT unique: two episodes with identical text
  would be surprising, not a constraint violation, and failing an ingest over
  it would be wrong.
* (document_id, chunk_index) is UNIQUE. A chunk's position in its transcript is
  part of its identity; two chunks claiming position 4 of one episode would
  make provenance ambiguous.
* messages.role and artifacts.type are constrained by CHECK rather than a
  native ENUM, so adding a value stays an ordinary migration instead of an
  ALTER TYPE. The allowed sets are defined once, in app/constants.py.
* messages.created_at defaults to clock_timestamp(), not now(). now() returns
  the transaction start time, so a user turn and the assistant reply written in
  one request would share a timestamp and their order would be undefined.
  Reads order by (created_at, id) so the ordering is total.
* artifacts.message_id is ON DELETE SET NULL, not CASCADE. Deleting a message
  should not destroy a document the user may still have open beside the chat.
* Every timestamp is TIMESTAMP WITH TIME ZONE.

The embedding column's width comes from Settings.embedding_dimensions, in the
model and in the migration alike — never a literal. A database built from the
migration therefore always matches the configured EMBEDDING_MODEL. Changing
EMBEDDING_MODEL against an existing database needs its own migration plus a
re-ingest, because the stored vectors are the wrong width.

Vector index: HNSW with vector_cosine_ops. IVFFlat derives its lists from the
rows present when the index is built, and the table is empty at migration time,
so IVFFlat would build a useless index. Cosine matches
RETRIEVAL_MAX_DISTANCE, which is expressed as a cosine distance.

Migrations

Alembic is the source of truth for the schema. create_all() is never called —
not by the application, not by the tests — so the schema a developer has is the
schema the migrations produce. The DSN is not stored in alembic.ini;
alembic/env.py reads it from application settings, so one place knows it and no
credential is committed.

tests/test_migrations.py compares the migrated database against the models with
alembic.autogenerate.compare_metadata and fails on any difference. Without that
test, editing a model without writing its migration would pass every other test
in the suite — because those tests run on a schema built by the same missing
migration — and only fail on deployment.

Repository layer

Database access is confined to backend/app/db/repositories/. No route handler
builds a query, so how data is stored stays changeable without touching the API
layer.

Repositories do not own transactions. app.db.session.get_session commits on a
successful request and rolls back on failure, so a handler may call several
repositories and get one atomic unit of work. Repositories only flush, and only
when they need the database to assign something before returning.

DocumentRepository.upsert returns (document, changed). That boolean is the
signal that makes refresh incremental: unchanged means skip, changed means
re-chunk and re-embed.

⸻


19. API Endpoints

The API will expose clear resource boundaries.

Health

GET /health

Returns application health and basic dependency status.

⸻

Sessions

POST /api/sessions

Creates a new chat session.

GET /api/sessions

Returns available sessions.

GET /api/sessions/{session_id}

Returns session details and conversation history.

⸻

Messages

POST /api/sessions/{session_id}/messages

Processes a new user message.

Conceptual request:

{
  "content": "How can I improve product retention?"
}

Conceptual response:

{
  "message_id": "...",
  "content": "...",
  "sources": [
    {
      "document_id": "...",
      "title": "...",
      "guest": "...",
      "source_url": "..."
    }
  ]
}

⸻

Providers

GET /api/providers

Returns currently available model providers.

Example:

{
  "providers": [
    {
      "id": "anthropic",
      "available": true
    },
    {
      "id": "ollama",
      "available": true
    }
  ]
}

⸻

Artifacts

POST /api/artifacts

Creates an artifact.

GET /api/artifacts/{artifact_id}

Retrieves a previously generated artifact.

The exact API surface can be refined during implementation.

⸻

20. Model Provider Architecture

The application will use a provider abstraction.

                    ModelProvider
                         │
              ┌──────────┴──────────┐
              │                     │
              ▼                     ▼
       CloudModelProvider      OllamaProvider
              │                     │
              ▼                     ▼
          Claude                Local LLM

Application code interacts with the abstraction rather than directly depending on one provider.

Conceptually:

model.generate(...)

rather than calling a specific vendor throughout the application.

⸻

21. Local Ollama Strategy

Ollama is mandatory for the submitted local demo.

Local environment:

┌──────────────────────────────┐
│          Local Machine       │
│                              │
│ FastAPI                      │
│    │                         │
│    └──────► Ollama           │
│               │              │
│               └─ Local LLM   │
│                              │
│ PostgreSQL / pgvector        │
└──────────────────────────────┘

The application should detect whether Ollama is available.

If Ollama is unavailable, the UI should not display it as an available provider.

⸻

22. Cloud Deployment Strategy

The deployed environment can use:

Frontend
   │
   ▼
FastAPI
   │
   ├────────► PostgreSQL + pgvector
   │
   ├────────► Ollama (embedding model only)
   │
   └────────► Cloud LLM

Ollama does not need to be deployed if the production environment does not have sufficient resources.

The local demo continues to demonstrate Ollama.

This keeps the deployment lightweight while satisfying the local LLM requirement.

⸻

23. Artifact Architecture

Implemented. backend/app/skills/, backend/app/artifacts/, backend/app/api/artifacts.py.

    question
      |
      v
    detect_artifact_request      keyword match, not an LLM classifier
      |
      v
    retrieval + evidence check   insufficient -> refuse, store nothing
      |
      v
    skill                        ship30.py (Markdown) | html_page.py (HTML)
      |
      v
    sanitise                     HTML only
      |
      v
    artifacts table              linked to the assistant message
      |
      v
    artifact panel

Generation is separate from normal grounded chat but reuses the same
ModelProvider; there is no second provider abstraction and no skill registry --
two skills, two functions.

The assistant message stores a short note, not the artifact body, so a
1,250-word essay is not duplicated into the conversation. The artifact carries
its own content and links back by message_id.

If the model refuses to produce the artifact -- which happens when enough
chunks clear the distance threshold but the evidence does not really cover the
topic -- the turn degrades to the grounded refusal and stores nothing, rather
than returning an error.

24. Artifact Security

Generated HTML is untrusted. Three independent layers:

1. Script-bearing elements (script, noscript, template, object, embed, applet)
   are removed with their contents. Stripping only the tag would leave the
   script body as visible text.
2. bleach allows a fixed layout/text tag set and removes every unknown tag,
   every on* handler, and every URL scheme except http, https and mailto.
   data: is refused because it can carry markup that some renderers execute.
   Inline CSS is filtered to a property allow-list; position is excluded so an
   artifact cannot escape its frame.
3. The frontend renders it in <iframe sandbox="" srcdoc=...>. No
   allow-scripts, no allow-same-origin: no JavaScript, no access to the parent
   document, its storage or its cookies.

Layer 3 means a miss in layers 1 and 2 still cannot execute. Sanitisation runs
on the way in, so stored content is already safe -- POST /api/artifacts
sanitises too, rather than trusting the caller.

Artifacts are static by design. There is no JavaScript in an artifact.


25. Ship 30 for 30 Skill Architecture

Implemented. backend/app/skills/ship30.py -- one prompt and one function.

Targets ~1,250 words: a hook, ## headings marking the turns of the argument,
selective bullets and bold, and a closing section with one specific action.
Every claim must come from the supplied evidence and be attributed to the guest
who said it. An essay that returns too short to be usable is rejected rather
than stored.


The essay feature is implemented as a dedicated skill rather than an ad-hoc prompt.

User asks for essay
        │
        ▼
Agent Router
        │
        ▼
Retrieve relevant sources
        │
        ▼
Ship 30 Skill
        │
        ▼
Generate ~1,250 words
        │
        ▼
Grounding / format validation
        │
        ▼
Markdown Artifact

The skill encapsulates the relevant writing principles and formatting requirements.

⸻

26. Error Handling

Each infrastructure boundary should expose controlled failures.

                  Request
                     │
                     ▼
                  FastAPI
                     │
             ┌───────┴────────┐
             │                │
        Database           Agent
             │                │
             ▼                ▼
          Failure          Retrieval
                              │
                              ▼
                            Model
                              │
                              ▼
                           Artifact

Expected failure cases include:

* Missing API key.
* Ollama unavailable.
* Model timeout.
* Empty retrieval.
* Database unavailable.
* Invalid request.
* Artifact sanitization failure.

The API should return structured errors rather than raw stack traces.

⸻

27. Observability

Structured logs will be emitted for important operations.

Example:

request_started
session_loaded
retrieval_started
retrieval_completed
model_request_started
model_request_completed
artifact_generation_started
artifact_sanitization_completed
message_persisted
request_completed

Failure events:

database_error
embedding_error
retrieval_error
model_timeout
ollama_unavailable
artifact_security_failure

Logs must not contain secrets or sensitive user data unnecessarily.

⸻

28. Deployment Topology

Local development/demo

┌──────────────────────────────────────────┐
│              Developer Machine           │
│                                          │
│  Frontend ──► FastAPI                    │
│                  │                       │
│          ┌───────┴────────┐              │
│          │                │              │
│       Postgres          Ollama           │
│       + pgvector        + LLM            │
│                                          │
└──────────────────────────────────────────┘

Cloud deployment — as actually deployed

                        Browser
                           │
                           ▼
              ┌────────────────────────┐
              │  Vercel (static SPA)   │  built with VITE_API_BASE_URL
              └───────────┬────────────┘
                          │  HTTPS, CORS-checked
                          ▼
              ┌────────────────────────┐
              │  Render — FastAPI      │  ALLOWED_HOSTS, structured logs
              └───┬────────┬───────────┘
                  │        │
       TLS,       │        │  private network, same region
       public     │        │  (paid instances only)
                  ▼        ▼
        ┌──────────────┐  ┌──────────────────────────┐
        │ Neon         │  │ Render — Ollama          │
        │ Postgres     │  │ (private service)        │
        │ + pgvector   │  │ nomic-embed-text only    │
        └──────────────┘  └──────────────────────────┘
                  │
                  ▼
           Anthropic API  (generation)

Three deliberate properties of this topology:

* **Ollama is private.** It has no authentication, so it is a private service
  reachable only from the API over Render's internal network — never from the
  internet.
* **Ollama serves embeddings, not generation.** Query embedding must happen on
  every question, and the corpus is embedded with `nomic-embed-text` at 768
  dimensions, so the query has to use the same model. Generation in production
  is Claude: `llama3.1:8b` needs ~6GB resident and CPU-only inference would
  exceed the request timeout.
* **The Ollama *provider* stays disabled in production.** `EMBEDDING_PROVIDER`
  and the LLM provider registry are independent, so the model picker still
  shows Ollama greyed out with its reason while embeddings quietly work.

Local startup is a Python virtualenv plus npm, wrapped by `./scripts/dev.sh`.
There is no Docker in this implementation: the only service that would need a
container is Postgres, and that is Neon.

⸻

29. Configuration

Configuration will be environment-driven.

Example:

APP_ENV=development
DATABASE_URL=
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=
CLOUD_LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=
EMBEDDING_PROVIDER=
EMBEDDING_API_KEY=
LOG_LEVEL=INFO

A .env.example will contain safe placeholders and documentation for required/optional values.

No secrets will be committed.

⸻

30. Security Boundaries

The primary security boundaries are:

API

* Validate incoming requests.
* Return controlled errors.
* Avoid exposing internal exceptions.

Database

* Use parameterized queries/ORM.
* Keep credentials in environment configuration.
* Restrict database access to the backend.

LLM

* Never send secrets in prompts.
* Avoid unnecessary user metadata.
* Clearly separate system instructions from retrieved content.

Retrieval

* Treat retrieved documents as data, not executable instructions.
* Preserve provenance.

Artifacts

* Treat generated HTML as untrusted.
* Sanitize/isolate before rendering.

⸻


Frontend boundary enforcement

The rule that the frontend speaks only to the backend is checked mechanically,
not left to review. frontend/scripts/check-boundary.mjs runs as part of both
`npm run lint` and `npm run build`, and fails the build on:

* a network primitive (fetch, XMLHttpRequest, WebSocket, EventSource,
  sendBeacon, Worker) outside src/api/client.ts
* an absolute URL outside src/constants.ts
* an import.meta.env read outside src/constants.ts
* a VITE_ variable whose name looks like a credential, since every VITE_
  variable is compiled into the publicly served bundle
* a database driver, ORM, model SDK or agent framework in package.json
* an external asset referenced from index.html

The check has no dependencies and reports file, line and reason.

31. Testing Strategy

Database tests run against a real PostgreSQL with pgvector and are never
skipped. The value of the schema is in its constraints, its cascades and its
vector column, none of which exist in a stand-in — and a skipped constraint
test is indistinguishable from a passing one in CI output. An unreachable
database therefore fails the run rather than being quietly stepped over.

The suite resolves its database from TEST_DATABASE_URL if set (point it at a
Neon test branch to run against the same engine production uses), otherwise a
local lenny_growth_assistant_test. DATABASE_URL is overwritten in the test
environment rather than defaulted, so the suite cannot reach the application
database in backend/.env — the fixtures create and drop schema.

Schema is built once per session by running Alembic (downgrade base, then
upgrade head, which exercises the downgrade path on every run). Each test then
runs inside a transaction that is rolled back, so tests are isolated without
re-creating the schema between them.

⸻


Tests will be organized around critical system boundaries.

API tests

* Session creation.
* Message submission.
* Validation.
* Error responses.
* Health endpoint.

Retrieval tests

* Query embedding.
* Relevant chunk retrieval.
* Source provenance.
* Empty retrieval behavior.

Agent tests

* Intent routing.
* RAG tool invocation.
* Essay skill invocation.
* Artifact skill invocation.
* Provider selection.

Persistence tests

* Session persistence.
* Message persistence.
* Artifact persistence.
* Document/chunk persistence.

Security tests

* Unsafe HTML.
* Script injection attempts.
* Artifact isolation behavior.

⸻

32. Key Architectural Trade-offs

PostgreSQL + pgvector

Decision: Use PostgreSQL for both application persistence and vector search.

Reasoning:

* Reduces infrastructure complexity.
* Keeps sessions, messages, documents, chunks, and embeddings together.
* Easier for a fresh evaluator to run locally.
* Avoids introducing a separate vector database for the MVP.

⸻

Precomputed embeddings

Decision: Embed transcript chunks during ingestion rather than during user requests.

Reasoning:

* Lower query latency.
* Avoids repeatedly processing the entire corpus.
* Reduces embedding cost.
* Makes the runtime retrieval path simple.

⸻

Incremental ingestion

Decision: Use content hashes to identify unchanged/new/modified transcripts.

Reasoning:

* Avoid unnecessary embedding calls.
* Keeps the knowledge base refreshable.
* Demonstrates operational readiness.

⸻

Local embeddings

Decision: Keep the embedding provider independent from the LLM provider, and
always run embeddings locally on Ollama.

Reasoning:

* The embedding model is 274 MB against 4.9 GB for generation, so the memory
  argument that pushes generation to the cloud does not apply to it.
* Ingestion embeds the whole corpus; doing that locally removes per-token cost
  and cloud egress from the pipeline entirely.
* One embedding provider means one vector width, so an index cannot be
  invalidated by a vendor changing a default.

Trade-off: a deployed instance must still reach an Ollama endpoint to embed
the user's query at request time.

⸻

Ollama only where available

Decision: Expose Ollama only when it is actually available.

Reasoning:

* Prevents a broken model option in the deployed UI.
* Keeps local demo and cloud deployment behavior explicit.
* Maintains one model abstraction across environments.

⸻

33. End-to-End Runtime Flow

                         USER
                           │
                           ▼
                      Chat UI
                           │
                           ▼
                        FastAPI
                           │
                           ▼
                  Load Session History
                           │
                           ▼
                    Agent Router
                           │
               ┌───────────┼───────────┐
               │           │           │
               ▼           ▼           ▼
             RAG         Essay      Artifact
             Tool        Skill        Skill
               │           │           │
               └───────────┼───────────┘
                           │
                           ▼
                    Query Embedding
                           │
                           ▼
                   PostgreSQL/pgvector
                           │
                           ▼
                    Relevant Chunks
                           │
                           ▼
                  Grounded Context
                           │
                    ┌──────┴──────┐
                    ▼             ▼
                 Ollama       Cloud LLM
                    │             │
                    └──────┬──────┘
                           ▼
                    Generated Output
                           │
                ┌──────────┴──────────┐
                ▼                     ▼
             Sources              Artifact
                │                     │
                │              Sanitization
                │                     │
                │                     ▼
                │              Artifact Viewer
                │                     │
                └──────────┬──────────┘
                           ▼
                         USER

⸻

34. Architectural Goal

The final architecture should allow a fresh evaluator to understand the system quickly:

Lenny transcripts
       ↓
Ingestion
       ↓
Chunks + embeddings
       ↓
PostgreSQL/pgvector
       ↓
RAG retrieval
       ↓
Agent
       ↓
Ollama / Cloud LLM
       ↓
Grounded response
       ↓
Sources + Artifacts

The architecture intentionally keeps the system modular so that another engineer can:

* Replace the LLM provider.
* Replace the embedding provider.
* Adjust chunking.
* Change retrieval strategy.
* Add new agent skills.
* Add additional artifact types.
* Refresh the transcript corpus.
* Extend the API.

without rewriting the entire application.