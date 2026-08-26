Product Requirements Document

The Lenny Growth Assistant

Version: 1.0
Status: Take-Home Assessment
Implementation status: The backend conversation path is complete --
transcript ingestion, embeddings, vector retrieval, grounded generation, and
persistent sessions/messages (POST /api/sessions/{id}/messages). There is no
authentication, by design (section 5.2): a client supplies its own identifier
in X-User-Id. The Ship 30 skill, artifact generation and the chat UI are not
yet built. Assistant messages persist their source provenance, so a reopened
conversation restores its citations. A retrieval evaluation set exists in
evals/; the relevance
metric in section 3 has not been measured yet. See README.md for the current
breakdown.
Target: Forward Deployed Engineer
Data Source: ChatPRD/lennys-podcast-transcripts

⸻

1. Product Overview

1.1 Product

The Lenny Growth Assistant is a full-stack, AI-powered conversational application that allows product and growth practitioners to ask questions grounded in Lenny’s Podcast transcripts.

The assistant will retrieve relevant transcript content, generate source-grounded answers, maintain conversation context, generate Ship 30 for 30–style essays, and create Markdown or HTML/CSS artifacts that render directly inside the application.

The product is designed as a small forward-deployment engagement: the goal is not only to build a technically functional system, but to provide a solution that an evaluator/client can quickly understand, run, trust, and extend.

1.2 Product Goal

Provide a reliable interface for extracting actionable product and growth knowledge from Lenny’s Podcast without requiring users to manually search transcripts or understand the underlying AI infrastructure.

1.3 Core Value Proposition

Ask a product or growth question in natural language and receive a useful answer grounded in Lenny’s Podcast, with clear source attribution and the ability to turn that knowledge into reusable content or rendered artifacts.

⸻

2. Discovery Brief

2.1 User

Primary user

Product managers, founders, growth practitioners, and product/growth teams who want to quickly apply ideas discussed across Lenny’s Podcast.

User characteristics

The primary user:

* Understands product/growth concepts.
* Does not want to manually search hundreds of transcripts.
* Does not need to understand RAG, embeddings, agents, or model infrastructure.
* Values actionable answers rather than generic AI responses.
* Needs confidence that recommendations are grounded in the source material.

⸻

2.2 User Problem

Lenny’s Podcast contains a large amount of product and growth knowledge distributed across many long-form transcripts.

Finding the relevant information manually is time-consuming. A generic LLM can also produce plausible but unsupported answers.

The assistant should solve both problems by:

1. Searching the transcript corpus semantically.
2. Retrieving relevant evidence.
3. Generating answers from that evidence.
4. Showing the user where the information came from.
5. Acknowledging when the available knowledge does not sufficiently support an answer.

⸻

3. Success Metrics

The following metrics will be used to evaluate the MVP.

Primary metric

Grounded Answer Rate

Percentage of supported user questions where the assistant provides an answer accompanied by at least one relevant transcript source.

Target for the MVP:

≥ 90% of evaluated supported questions.

Secondary metrics

Retrieval relevance

Percentage of retrieved chunks judged relevant to the user’s question.

Target:

≥ 80% on a manually created evaluation set.

Unsupported-question behavior

Percentage of questions outside the knowledge base where the assistant appropriately states that the available material does not support an answer.

Target:

≥ 90%.

Application reliability

The evaluator should be able to clone the repository and start the application using only the documented setup instructions.

⸻

4. Assumptions

The original brief intentionally leaves several implementation details open. The following assumptions will guide the MVP.

Data

* The primary knowledge source will be the public ChatPRD/lennys-podcast-transcripts repository.
* The transcript files are treated as the source of truth for the assistant’s knowledge.
* Transcript metadata such as episode title, guest, publication date, and source URL will be preserved.
* The knowledge base will be generated through an explicit ingestion process rather than at application startup.

Retrieval

* The application will use a RAG architecture.
* Transcript content will be split into retrieval-friendly chunks.
* Each chunk will have an embedding and source metadata.
* Neon PostgreSQL with pgvector will be used for vector search alongside application persistence.
* Initial chunking will target approximately 500–800 tokens with moderate overlap; this is an implementation choice and may be tuned after retrieval evaluation.
* Top-K retrieval will be used to provide relevant evidence to the agent.

Models

* A cloud LLM will be supported for normal/cloud execution.
* Ollama will be supported as the mandatory local LLM for the demo.
* Embeddings are generated locally by Ollama, so ingestion needs no API key and incurs no per-token cost. The embedding model is independent of the LLM provider, which may be local or cloud.
* Model provider selection will not require changes to application logic.

Sessions

* Each chat session has independent conversation context.
* Conversations are persisted in PostgreSQL.
* User metadata will be limited to what is necessary for the application.

Artifacts

* Generated HTML is considered untrusted content.
* HTML artifacts will be rendered in an isolated/sanitized environment.
* The artifact viewer will prioritize safe rendering over unrestricted browser functionality.

⸻

5. Scope

5.1 In Scope

Conversational assistant

* New chat sessions.
* Persistent conversation history.
* Follow-up questions.
* Grounded answers based on Lenny’s Podcast transcripts.
* Source attribution.
* Unsupported-question handling.

Knowledge base

* Transcript ingestion.
* Metadata extraction.
* Transcript cleaning.
* Chunking.
* Embedding generation.
* Vector indexing.
* Semantic retrieval.
* Source/provenance tracking.
* Incremental refresh.

Agent capabilities

* Knowledge retrieval.
* Grounded response generation.
* Ship 30 for 30 content generation.
* Markdown artifact generation.
* HTML/CSS artifact generation.

Model configuration

* Cloud LLM.
* Ollama local LLM.
* Configurable model provider.
* Provider availability displayed in the UI/configuration.

Artifact viewer

* Render generated Markdown.
* Render generated HTML/CSS.
* Display artifact beside the conversation.
* Apply HTML sanitization/isolation.

Operational readiness

* FastAPI backend.
* PostgreSQL persistence.
* Structured logging.
* Error handling.
* Health endpoint.
* Docker Compose or equivalent reproducible startup.
* .env.example.
* Automated tests.
* Documentation.

⸻

5.2 Out of Scope

The MVP will intentionally exclude:

* Real-time podcast ingestion.
* User-uploaded private knowledge bases.
* Multi-tenant enterprise permissions.
* Fine-tuning custom LLMs.
* Training custom embedding models.
* Full autonomous web research outside the transcript corpus.
* Production-scale distributed infrastructure.
* Advanced analytics dashboards.
* Native mobile applications.
* Arbitrary unrestricted JavaScript execution inside artifacts.

These are excluded to keep the submission focused on the required forward-deployment workflow and to reduce unnecessary complexity.

⸻

6. Product Flows

6.1 New Chat

User
 ↓
New Chat
 ↓
Create session
 ↓
Persist session
 ↓
Empty conversation
 ↓
User asks question

Acceptance criteria

* A user can start a new conversation.
* Each session receives a unique ID.
* Messages from different sessions do not share conversational context.

⸻

7. Grounded Question Flow

User question
      ↓
FastAPI
      ↓
Load session context
      ↓
Agent
      ↓
Create query embedding
      ↓
Vector search
      ↓
Retrieve relevant transcript chunks
      ↓
Construct grounded context
      ↓
LLM
      ↓
Answer + source metadata
      ↓
Persist response
      ↓
Display in UI

Acceptance criteria

* Questions are answered using retrieved transcript evidence.
* Relevant sources are displayed.
* Follow-up questions preserve session context.
* The assistant does not knowingly fabricate unsupported information.
* If retrieval does not produce sufficient evidence, the assistant communicates that limitation.

⸻

8. Knowledge Ingestion Flow

The transcript repository will be processed separately from normal user requests.

GitHub Repository
       ↓
Repository Sync
       ↓
Find transcript files
       ↓
Parse metadata
       ↓
Clean transcript
       ↓
Chunk transcript
       ↓
Generate embeddings
       ↓
Store documents/chunks/vectors
       ↓
Ready for retrieval

Runtime principle

The application will not re-download and re-embed the entire repository for every user question.

The corpus will be indexed ahead of runtime.

At query time, only the user’s query needs to be embedded before semantic search.

⸻

9. Knowledge Refresh Flow

The ingestion system will support incremental updates.

GitHub Repository
       ↓
Compare source/content hashes
       ↓
 ┌─────────────┬──────────────┐
 │             │              │
Unchanged      New         Modified
 │             │              │
Skip       Process       Re-process
             │              │
             └──────┬───────┘
                    ↓
              Chunk + Embed
                    ↓
               Update Index

Acceptance criteria

* Existing unchanged documents are not unnecessarily re-embedded.
* New episodes can be added.
* Modified episodes can be reprocessed.
* Each chunk remains traceable to its original transcript.

⸻

10. Retrieval & Source Attribution

Each chunk will retain provenance metadata.

Example:

chunk_id
document_id
episode_title
guest
publish_date
source_url
chunk_index
content
embedding

When a chunk is retrieved, its source metadata will be available to the response generator and frontend.

Example UI:

Answer
...
Sources
• Guest Name — Episode Title
  View source →

Acceptance criteria

* Every grounded response can identify the relevant source material.
* Sources correspond to retrieved transcript content.
* Users can distinguish generated content from source material.

⸻

11. Ship 30 for 30 Skill

The assistant will provide a dedicated content-generation skill for producing approximately 1,250-word essays in the requested Ship 30 for 30 style.

Flow

User asks for essay
        ↓
Retrieve relevant transcript evidence
        ↓
Ship 30 skill
        ↓
Apply writing principles
        ↓
Generate essay
        ↓
Validate grounding
        ↓
Return Markdown artifact

Requirements

Generated essays should include:

* Approximately 1,250 words.
* Strong hook.
* Clear narrative progression.
* Headings.
* Bullets where useful.
* Selective bold emphasis.
* Specific actionable takeaway.
* Claims grounded in retrieved transcript material.

Acceptance criteria

* The essay is generated through the dedicated skill/tool.
* The content is grounded in transcript evidence.
* The output follows the required structural/style characteristics.

⸻

12. Artifact Generation

The assistant will support two primary artifact types:

Markdown

Examples:

* Product strategy document.
* Growth plan.
* Essay.
* Research summary.

HTML/CSS

Examples:

* Landing page.
* Dashboard.
* Product concept.
* Interactive presentation.

Flow

User request
      ↓
Agent identifies artifact intent
      ↓
Retrieve relevant conversation/source context
      ↓
Generate artifact
      ↓
Validate/sanitize
      ↓
Artifact Viewer

⸻

13. Artifact Viewer

The frontend will use a split experience:

┌───────────────────────┬────────────────────────┐
│                       │                        │
│        CHAT           │    ARTIFACT VIEWER     │
│                       │                        │
│ User                  │   Rendered Markdown    │
│ Assistant             │          or            │
│                       │    Rendered HTML/CSS   │
│                       │                        │
└───────────────────────┴────────────────────────┘

The artifact should be rendered natively inside the application rather than displaying raw HTML/CSS code or redirecting the user elsewhere.

⸻

14. Artifact Security

Generated HTML will be treated as untrusted.

Security strategy

* Sanitize generated HTML.
* Prevent access to the parent application.
* Restrict dangerous browser capabilities.
* Render artifacts in an isolated context.
* Do not expose application credentials or sensitive data to generated content.

Acceptance criteria

* Malicious or unsafe HTML does not gain unrestricted access to the application.
* The security model is documented.
* The evaluator can understand what the artifact viewer permits and blocks.

⸻

15. Model Architecture

The application will use a provider abstraction.

                 Model Interface
                       │
              ┌────────┴────────┐
              │                 │
          Cloud LLM          Ollama
              │                 │
             Claude          Local LLM

Example configuration:

LLM_PROVIDER=anthropic

or:

LLM_PROVIDER=ollama

The UI will display available providers.

Local demo

The application will demonstrate Ollama locally.

Deployed environment

If Ollama is not available in the deployment environment, the UI will expose the available cloud provider instead of presenting a non-functional local option.

Acceptance criteria

* Switching providers does not require changing application logic.
* Ollama works for the local demo.
* Cloud LLM works when configured.
* Missing/unavailable providers produce a clear fallback/error state.

⸻

16. Database Requirements

PostgreSQL will be used for application persistence and vector retrieval.

Core entities

users
sessions
messages
documents
chunks
artifacts

Relationships

User
 └── Sessions
       └── Messages
             └── Artifacts
Document
 └── Chunks
       └── Embeddings

The exact schema will be documented separately in architecture.md.

⸻

17. API Requirements

The backend will use FastAPI.

Expected API surface:

POST   /api/sessions
GET    /api/sessions
GET    /api/sessions/{session_id}
POST   /api/sessions/{session_id}/messages
POST   /api/artifacts
GET    /api/artifacts/{artifact_id}
GET    /api/providers
GET    /health

The exact endpoints may be refined during implementation.

API requirements

* Request validation.
* Typed request/response contracts.
* Structured error responses.
* HTTP status codes appropriate to failure type.
* Health endpoint.
* Clear separation between API, agent, retrieval, and persistence layers.

⸻

18. Error & Resilience Requirements

The application must gracefully handle:

Failure	Expected behavior
Missing cloud API key	Clear configuration error
Ollama unavailable	Inform user / fallback if configured
LLM timeout	Retry or return clear failure
Empty retrieval	Explain insufficient knowledge
Database unavailable	Return structured service error
Invalid request	Validation error
Artifact sanitization failure	Refuse unsafe artifact
Model provider unavailable	Use documented fallback

The application should fail gracefully rather than exposing stack traces or internal implementation details to users.

⸻

19. Observability

Structured logs should cover major system operations.

Example events:

request_started
session_loaded
retrieval_started
retrieval_completed
model_started
model_completed
artifact_generated
artifact_sanitized
response_persisted

Failures should include enough information to diagnose:

* Retrieval problems.
* Model failures.
* Database failures.
* Artifact rendering failures.

Secrets must never be logged.

⸻

20. UI/UX Requirements

The application should provide a polished conversational experience.

Required states

* Empty chat.
* Loading/generating.
* Successful response.
* Retrieval with sources.
* No relevant information.
* Model unavailable.
* Error.
* Artifact generated.
* Artifact loading/error.

Main UI

Sidebar
 ├── New Chat
 ├── Previous sessions
 └── Session list
Main Chat
 ├── Messages
 ├── Sources
 └── Input
Artifact Panel
 ├── Preview
 └── Artifact state

The UI should be responsive and accessible.

⸻

21. Acceptance Criteria

The MVP is considered complete when:

Core assistant

* User can create a new chat.
* User can send messages.
* Sessions preserve independent context.
* Conversations persist in Neon PostgreSQL.
* Assistant answers using Lenny transcript knowledge.
* Responses identify relevant sources.
* Unsupported questions are handled honestly.

Knowledge base

* Complete selected transcript corpus is ingestible.
* Transcripts are chunked.
* Chunks receive embeddings.
* Embeddings are stored in the vector index.
* Semantic retrieval returns relevant chunks.
* Chunk provenance is preserved.
* Ingestion can refresh new/modified transcripts.

Models

* Cloud LLM works.
* Ollama works locally.
* Provider selection is configurable.
* Provider availability is visible.

Content skill

* Dedicated Ship 30 for 30 skill exists.
* Generated content is approximately 1,250 words.
* Generated content follows the required structure.
* Claims are grounded.

Artifacts

* Markdown artifacts can be generated.
* HTML/CSS artifacts can be generated.
* Artifacts render inside the product.
* Generated HTML is sanitized/isolated.

Operations

* .env.example exists.
* No secrets are committed.
* One-command/equivalent startup is documented.
* Health endpoint works.
* Structured logging exists.
* Failure scenarios are handled.

Documentation

* README complete.
* PRD complete.
* design.md complete.
* architecture.md complete.
* Agent transcripts included.
* Automated tests included.
* Manual UI test plan included.
* 2–3 minute demo video prepared.

⸻

22. Risks & Trade-offs

22.1 Hallucination

Risk: The LLM generates information not supported by Lenny’s transcripts.

Mitigation:

* Retrieve relevant evidence.
* Instruct the agent to stay grounded.
* Require source attribution.
* Explicitly handle insufficient retrieval.

⸻

22.2 Retrieval Quality

Risk: Poor chunking or embeddings result in irrelevant context.

Mitigation:

* Preserve transcript structure and metadata.
* Evaluate chunk size.
* Use semantic retrieval.
* Create a small retrieval evaluation set.
* Tune Top-K based on evaluation results.

⸻

22.3 Local Model Quality

Risk: Small Ollama models may provide lower-quality answers than cloud models.

Mitigation:

* Use Ollama primarily to satisfy and demonstrate local execution.
* Keep the model provider abstraction.
* Document quality/latency trade-offs.
* Use a cloud model when higher generation quality is required.

⸻

22.4 Latency

Risk: Retrieval + model generation may feel slow, especially with a local model.

Mitigation:

* Keep retrieved context focused.
* Limit unnecessary retrieval.
* Stream responses where practical.
* Use an appropriately sized local model.

⸻

22.5 Cost

Risk: Cloud LLM APIs incur usage costs. (Embeddings are local, so the corpus ingest is free.)

Mitigation:

* Precompute corpus embeddings.
* Incrementally refresh only changed/new documents.
* Retrieve only the necessary chunks.
* Support Ollama for local generation.

⸻

22.6 Unsafe HTML

Risk: Generated HTML could execute unwanted code or access application resources.

Mitigation:

* Treat generated HTML as untrusted.
* Sanitize output.
* Isolate rendering.
* Restrict browser capabilities.
* Document the security boundary.

⸻

22.7 Data Freshness

Risk: The GitHub repository may change after initial ingestion.

Mitigation:

* Store source hashes.
* Implement incremental synchronization.
* Reprocess only new/modified transcripts.

⸻

23. Implementation Plan

Phase 1 — Foundation

* Set up repository.
* Create frontend/backend structure.
* Configure FastAPI.
* Configure Neon PostgreSQL.
* Define database schema.
* Establish environment configuration.
* Add health endpoint.

Phase 2 — Knowledge Pipeline

* Connect to transcript repository.
* Parse transcript Markdown.
* Extract metadata.
* Implement chunking.
* Generate embeddings.
* Store vectors in PostgreSQL/pgvector.
* Implement source provenance.
* Implement incremental ingestion.

Phase 3 — RAG

* Implement query embedding.
* Implement vector retrieval.
* Implement Top-K selection.
* Build grounded context.
* Add source attribution.
* Implement unsupported-question handling.

Phase 4 — Agent

* Integrate Claude Agent SDK or Pi Coding Agent.
* Implement agent routing.
* Implement retrieval tool.
* Implement model provider abstraction.
* Integrate cloud LLM.
* Integrate Ollama.

Phase 5 — Product Features

* Build conversational UI.
* Add session persistence.
* Add follow-up context.
* Implement Ship 30 for 30 skill.
* Implement Markdown generation.
* Implement HTML/CSS generation.

Phase 6 — Artifact Viewer & Security

* Build split chat/artifact interface.
* Implement Markdown renderer.
* Implement HTML renderer.
* Add sanitization/isolation.
* Test unsafe artifact scenarios.

Phase 7 — Reliability & Testing

* API tests.
* Retrieval tests.
* Agent routing tests.
* Persistence tests.
* Provider failure tests.
* Artifact security tests.
* Manual UI test plan.
* Structured logging.

Phase 8 — Documentation & Submission

* Complete README.
* Complete PRD.
* Complete design.md.
* Complete architecture.md.
* Add agent transcripts.
* Verify fresh-clone setup.
* Record 2–3 minute demo.
* Submit repository and form.

⸻

24. MVP Definition

The MVP is successful when a fresh evaluator can:

1. Clone the repository.
2. Follow the README.
3. Start the application.
4. Create a new chat.
5. Ask a product/growth question.
6. Receive a grounded answer.
7. Inspect the source used.
8. Ask a follow-up question.
9. Generate a Ship 30 for 30–style essay.
10. Generate an HTML/Markdown artifact.
11. View the artifact inside the application.
12. Run the local Ollama model.
13. Understand the architecture and trade-offs from the documentation.
14. Run the automated tests.

⸻

25. Key Product Principle

The product should optimize for:

Grounded usefulness over generic intelligence.

The assistant is not intended to be a general-purpose chatbot.

Its value comes from reliably transforming the knowledge contained in Lenny’s Podcast into useful, traceable product and growth answers and reusable artifacts.

The technical architecture should therefore prioritize:

Source grounding → Retrieval quality → Clear provenance → Reliable generation → Usable product experience → Operational simplicity.

⸻

26. Final Architecture Summary

                     LENNY GROWTH ASSISTANT
                         User
                           │
                           ▼
                  React / Next.js
                           │
                           ▼
                       FastAPI
                           │
                    ┌──────┴──────┐
                    │             │
                    ▼             ▼
                 Agent       Neon PostgreSQL
                    │          + pgvector
             ┌──────┼──────┐      ▲
             │      │      │      │
             ▼      ▼      ▼      │
            RAG   Essay  Artifact │
             │     Skill   Skill  │
             │                   │
             ▼                   │
        Query Embedding ─────────┘
             │
             ▼
        Vector Search
             │
             ▼
       Relevant Chunks
             │
             ▼
       Grounded Context
             │
       ┌─────┴─────┐
       ▼           ▼
    Ollama       Cloud LLM
       │           │
       └─────┬─────┘
             ▼
       Final Response
             │
       ┌─────┴─────────┐
       ▼               ▼
    Chat + Sources   Artifact Viewer
DATA INGESTION
Lenny Podcast GitHub Repository
              │
              ▼
        Parse transcripts
              │
              ▼
           Chunking
              │
              ▼
       Local Embeddings
              │
              ▼
       Neon PostgreSQL/pgvector
              │
              ▼
        Runtime Retrieval

This PRD covers the user, problem, success metrics, assumptions, scope, flows, acceptance criteria, risks/trade-offs, and implementation plan requested in the assignment.