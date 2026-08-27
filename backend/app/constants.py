"""Application and domain constants.

What belongs here: values that are shared across modules, or that are part of a
contract (provider ids, error codes, routes the frontend calls), or that are
configuration defaults. One-off implementation values stay where they are used.

Runtime configuration lives in config.py; this module holds its defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

APP_NAME = "lenny-growth-assistant"
APP_VERSION = "0.1.0"

# backend/ -- owns .env, requirements.txt and alembic.ini.
BACKEND_DIR = Path(__file__).resolve().parent.parent

Environment = Literal["development", "test", "production"]

# ---------------------------------------------------------------------------
# Routes
#
# Part of the API contract: frontend/src/constants.ts mirrors these, and
# tests/test_constants.py asserts the two agree.
# ---------------------------------------------------------------------------

API_PREFIX = "/api"
ROUTE_HEALTH = "/health"
ROUTE_PROVIDERS = "/providers"
ROUTE_SESSIONS = "/sessions"
ROUTE_ARTIFACTS = "/artifacts"

# ---------------------------------------------------------------------------
# Model providers
#
# The ids appear in GET /api/providers and in LLM_PROVIDER, and the frontend
# switches on them.
# ---------------------------------------------------------------------------

LLMProviderId = Literal["ollama", "anthropic"]
ProviderKind = Literal["local", "cloud"]

PROVIDER_OLLAMA = "ollama"
PROVIDER_ANTHROPIC = "anthropic"

DEFAULT_LLM_PROVIDER: LLMProviderId = PROVIDER_OLLAMA

# ---- Ollama ----
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 180.0

# ---- Anthropic ----
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
DEFAULT_ANTHROPIC_TIMEOUT_SECONDS = 120.0

# Availability probes run on the request path, so they are short and cached.
DEFAULT_PROVIDER_PROBE_TIMEOUT_SECONDS = 3.0
DEFAULT_PROVIDER_STATUS_TTL_SECONDS = 15.0

# ---------------------------------------------------------------------------
# Error codes
#
# Stable identifiers the frontend matches on. Treated as an API contract.
# ---------------------------------------------------------------------------

ERROR_INTERNAL = "internal_error"
ERROR_CONFIGURATION = "configuration_error"
ERROR_DATABASE_UNAVAILABLE = "database_unavailable"
ERROR_NOT_FOUND = "not_found"
ERROR_VALIDATION = "validation_error"
ERROR_HTTP = "http_error"
ERROR_EMBEDDING_FAILED = "embedding_failed"
ERROR_PROVIDER_UNAVAILABLE = "provider_unavailable"
ERROR_MODEL_TIMEOUT = "model_timeout"
ERROR_MODEL_FAILED = "model_error"
ERROR_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
ERROR_ARTIFACT_UNSAFE = "artifact_unsafe"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DEFAULT_DATABASE_URL = "postgresql+psycopg://localhost:5432/lenny_growth_assistant"

# Establishing a TLS connection to a managed PostgreSQL in another region takes
# several seconds. A ceiling below that cancels the attempt before it can be
# pooled, so every later probe fails too.
DEFAULT_DATABASE_PROBE_TIMEOUT_SECONDS = 10.0

# ---------------------------------------------------------------------------
# Message roles and artifact types
#
# Enforced in the database by CHECK constraints built from these tuples, so
# adding a value stays an ordinary migration rather than an ALTER TYPE.
# ---------------------------------------------------------------------------

MessageRole = Literal["user", "assistant", "system"]

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
MESSAGE_ROLES = (ROLE_USER, ROLE_ASSISTANT, ROLE_SYSTEM)

ArtifactType = Literal["markdown", "html"]

ARTIFACT_MARKDOWN = "markdown"
ARTIFACT_HTML = "html"
ARTIFACT_TYPES = (ARTIFACT_MARKDOWN, ARTIFACT_HTML)

# ---------------------------------------------------------------------------
# Embeddings
#
# Always local (Ollama), so ingesting the corpus needs no API key. The model
# fixes the pgvector column width, so an unmapped model must fail loudly
# rather than default to a wrong one.
# ---------------------------------------------------------------------------

EmbeddingProviderId = Literal["ollama"]

DEFAULT_EMBEDDING_PROVIDER: EmbeddingProviderId = "ollama"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_EMBEDDING_BATCH_SIZE = 32
DEFAULT_EMBEDDING_TIMEOUT_SECONDS = 120.0

EMBEDDING_DIMENSIONS = {
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
}

# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

DEFAULT_TRANSCRIPT_REPO = "ChatPRD/lennys-podcast-transcripts"
DEFAULT_TRANSCRIPT_REPO_REF = "main"
DEFAULT_TRANSCRIPT_CACHE_DIR = ".transcript-cache"
DEFAULT_CHUNK_TARGET_TOKENS = 600
DEFAULT_CHUNK_OVERLAP_TOKENS = 80

# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

DEFAULT_RETRIEVAL_TOP_K = 8
# Cosine distance above which a chunk counts as irrelevant. Chunks that do not
# clear this bar are dropped, which is what produces "insufficient evidence"
# instead of a fabricated answer.
#
# Measured against evals/retrieval.json on the full 9,842-chunk corpus: the
# best match sits at 0.18-0.37 for questions the corpus answers and 0.49-0.52
# for off-corpus questions. 0.45 sits in the empty band between them -- it
# keeps every on-corpus hit and refuses every off-corpus query. The previous
# 0.62 refused none of them, which made insufficient-evidence unreachable.
DEFAULT_RETRIEVAL_MAX_DISTANCE = 0.45
DEFAULT_RETRIEVAL_MIN_CHUNKS = 2

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

# The Vite dev server.
DEFAULT_CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
DEFAULT_HTTP_MAX_CONNECTIONS = 20
