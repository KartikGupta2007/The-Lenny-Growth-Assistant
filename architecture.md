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
                    │    React / Next.js   │
                    │                      │
                    │ Chat │ Sources       │
                    │ Model selector       │
                    │ Artifact Viewer      │
                    └──────────┬───────────┘
                               │
                         HTTP / Streaming
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

8.1 Repository synchronization

The ingestion service reads the transcript repository and identifies transcript files.

The application should not download and process the entire repository for every user query.

Instead, ingestion is an explicit operation:

python -m app.ingestion.sync

⸻

8.2 Metadata extraction

Each transcript is parsed into a document record containing metadata such as:

document_id
guest
episode_title
publish_date
youtube_url
description
source_url
content_hash

The original source metadata is preserved so retrieved content can be traced back to the episode.

⸻

8.3 Transcript cleaning

The raw Markdown is converted into normalized text while preserving useful structure.

The cleaning stage should remove unnecessary formatting noise without removing information that could be useful for retrieval.

⸻

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

Each transcript chunk is converted into a vector representation.

Transcript Chunk
       │
       ▼
Embedding Provider
       │
       ▼
Vector
       │
       ▼
PostgreSQL / pgvector

The embedding provider is independent of the LLM provider: generation may be
local or cloud, embeddings are always local.

Embeddings run on Ollama (`nomic-embed-text`, 768 dimensions). The model is
274 MB — two orders of magnitude smaller than the 4.9 GB generation model — so
running it locally costs little, while removing API keys, cloud egress and
per-token cost from the ingestion path entirely.

Consequence for deployment: query embedding happens on the request path, so a
deployed instance still needs an Ollama endpoint reachable at
OLLAMA_BASE_URL — one hosting only the embedding model. This is a much smaller
requirement than hosting the generation model, which is why the LLM provider
falls back to cloud in production while embeddings do not.

⸻

11. Vector Storage

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

The runtime system does not access GitHub.

For a user question:

User Question
      │
      ▼
FastAPI
      │
      ▼
Load Session Context
      │
      ▼
Agent
      │
      ▼
Query Embedding
      │
      ▼
pgvector Similarity Search
      │
      ▼
Top-K Relevant Chunks
      │
      ▼
Grounded Context
      │
      ▼
LLM
      │
      ▼
Answer + Sources

Only the user query needs a new embedding at runtime. The transcript embeddings are precomputed during ingestion.

⸻

15. Retrieval Strategy

The initial retrieval implementation will use semantic similarity against stored chunk embeddings.

The retrieval process:

1. Receive user question.
2. Generate query embedding.
3. Search pgvector.
4. Retrieve the highest-ranked chunks.
5. Apply optional relevance filtering/reranking.
6. Construct a compact context.
7. Pass the context and source metadata to the agent/LLM.

The exact Top-K value will be tuned using retrieval evaluation rather than treated as a fixed requirement.

⸻

16. Grounding Strategy

The LLM should treat retrieved transcript content as its primary evidence.

The system should:

* Prefer retrieved transcript evidence.
* Avoid unsupported claims.
* Include source information.
* State when the knowledge base does not provide sufficient evidence.

Example:

Question
   │
   ▼
Retrieved Evidence
   │
   ▼
Grounded Prompt
   │
   ▼
LLM
   │
   ▼
Answer
   │
   └── Sources

If retrieval produces insufficient evidence, the system should not fabricate an answer.

⸻

17. Session and Conversation Architecture

Each conversation has an independent session.

users
  │
  └── sessions
        │
        └── messages
              │
              └── artifacts

A session contains:

session_id
created_at
updated_at
user_id / metadata

A message contains:

message_id
session_id
role
content
created_at
metadata

This allows follow-up questions to use the current conversation context while keeping different chats isolated.

⸻
Authentication is intentionally out of MVP scope because the assignment does not require authenticated users. Anonymous users are assigned a persistent user identifier so that sessions and conversation history can still be stored independently.

18. Database Schema

Conceptual schema:

┌──────────────────┐
│      users       │
├──────────────────┤
│ id               │
│ metadata         │
│ created_at       │
└────────┬─────────┘
         │
         │ 1:N
         ▼
┌──────────────────┐
│     sessions     │
├──────────────────┤
│ id               │
│ user_id          │
│ created_at       │
│ updated_at       │
└────────┬─────────┘
         │
         │ 1:N
         ▼
┌──────────────────┐
│     messages     │
├──────────────────┤
│ id               │
│ session_id       │
│ role             │
│ content          │
│ created_at       │
└────────┬─────────┘
         │
         │ 1:N
         ▼
┌──────────────────┐
│    artifacts     │
├──────────────────┤
│ id               │
│ session_id       │
│ message_id       │
│ type             │
│ content          │
│ created_at       │
└──────────────────┘
┌──────────────────┐
│    documents     │
├──────────────────┤
│ id               │
│ guest            │
│ title            │
│ source_url       │
│ publish_date     │
│ content_hash     │
│ created_at       │
│ updated_at       │
└────────┬─────────┘
         │
         │ 1:N
         ▼
┌──────────────────┐
│      chunks      │
├──────────────────┤
│ id               │
│ document_id      │
│ chunk_index      │
│ content          │
│ embedding        │
│ metadata         │
│ created_at       │
└──────────────────┘

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

Artifact generation is separated from artifact rendering.

User Request
     │
     ▼
Agent
     │
     ▼
Artifact Generator
     │
     ▼
Generated Content
     │
     ▼
Security Layer
     │
     ▼
Artifact Viewer

⸻

24. Artifact Security

Generated HTML is considered untrusted.

The security boundary is:

Generated HTML
      │
      ▼
Sanitization
      │
      ▼
Restricted / Isolated Rendering
      │
      ▼
Artifact Viewer

The implementation should prevent generated artifacts from gaining unintended access to:

* Parent application state.
* Authentication information.
* Application cookies.
* Sensitive APIs.
* Other users’ data.

The exact isolation mechanism will be selected during implementation based on the frontend technology.

⸻

25. Ship 30 for 30 Skill Architecture

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

Cloud deployment

             Internet
                 │
                 ▼
          Frontend / Web App
                 │
                 ▼
             FastAPI
           ┌─────┼─────┐
           │     │     │
           ▼     ▼     ▼
       Postgres Embedding Cloud LLM
       +pgvector   API

Docker Compose or an equivalent reproducible workflow will be provided for local startup.

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