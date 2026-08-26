/**
 * Single source of truth for every fixed value in the frontend.
 *
 * This module imports nothing from the rest of `src`, so it can be imported
 * anywhere without a cycle. The rule the codebase follows:
 *
 * - A value used in more than one module, or one a reader would have to guess
 *   the meaning of at its call site, is named here.
 * - Anything shared with the backend -- provider ids, error codes, route
 *   paths -- is defined here and mirrors `backend/app/constants.py`. Those are
 *   API contracts: changing one side alone breaks the pair.
 *
 * Declared with `as const` rather than `enum`, because `erasableSyntaxOnly` is
 * on in tsconfig and enums emit runtime code.
 */

// ---------------------------------------------------------------------------
// Backend connection
// ---------------------------------------------------------------------------

/** Used when VITE_API_BASE_URL is unset -- the local uvicorn default. */
export const DEFAULT_API_BASE_URL = 'http://localhost:8000';

/** Resolved once: a trailing slash would double up against every path. */
export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL
).replace(/\/$/, '');

/** Requests are abandoned after this long unless the caller says otherwise. */
export const DEFAULT_TIMEOUT_MS = 10_000;

/** Mirrors the routes registered in `backend/app/main.py`. */
export const ENDPOINTS = {
  health: '/health',
  providers: '/api/providers',
} as const;

// ---------------------------------------------------------------------------
// Model providers
//
// Mirrors PROVIDER_* in backend/app/constants.py. Order here is display order
// in the selector: local first, matching design.md section 10.
// ---------------------------------------------------------------------------

export const PROVIDER_IDS = ['ollama', 'anthropic'] as const;
export type ProviderId = (typeof PROVIDER_IDS)[number];

export const PROVIDER_KINDS = ['local', 'cloud'] as const;
export type ProviderKind = (typeof PROVIDER_KINDS)[number];

/** Badge text beside each option. */
export const PROVIDER_KIND_LABELS: Record<ProviderKind, string> = {
  local: 'Local',
  cloud: 'Cloud',
};

/** Narrows an untrusted string (e.g. from localStorage) to a provider id. */
export function isProviderId(value: unknown): value is ProviderId {
  return (
    typeof value === 'string' &&
    (PROVIDER_IDS as readonly string[]).includes(value)
  );
}

// ---------------------------------------------------------------------------
// Browser storage
// ---------------------------------------------------------------------------

export const STORAGE_KEYS = {
  /** The user's remembered model choice. */
  selectedProvider: 'lga.selected-provider',
} as const;

// ---------------------------------------------------------------------------
// Error codes
//
// Mirrors ERROR_* in backend/app/constants.py. The UI switches on these rather
// than pattern-matching message text, so they are treated as a contract.
// ---------------------------------------------------------------------------

export const ERROR_CODES = {
  internal: 'internal_error',
  configuration: 'configuration_error',
  validation: 'validation_error',
  notFound: 'not_found',
  /** Any other non-2xx raised by Starlette rather than an AppError. */
  http: 'http_error',
  databaseUnavailable: 'database_unavailable',
  embeddingFailed: 'embedding_failed',
  providerUnavailable: 'provider_unavailable',
  modelTimeout: 'model_timeout',
  modelError: 'model_error',
  insufficientEvidence: 'insufficient_evidence',
  artifactUnsafe: 'artifact_unsafe',
  /** Client-side only: the body was not the JSON envelope we expect. */
  invalidResponse: 'invalid_response',
  /** Client-side only: a non-2xx response with no recognisable envelope. */
  unexpected: 'unexpected_error',
} as const;

/** `Error.name` values, so callers can branch without importing the classes. */
export const ERROR_NAMES = {
  api: 'ApiError',
  network: 'NetworkError',
  timeout: 'TimeoutError',
} as const;

// ---------------------------------------------------------------------------
// DOM identifiers
// ---------------------------------------------------------------------------

/** Groups the provider radios; must be identical across the options. */
export const MODEL_RADIO_GROUP_NAME = 'model-provider';

/** Prefix for the id that `aria-describedby` points at. */
export const PROVIDER_REASON_ID_PREFIX = 'provider-reason';

// ---------------------------------------------------------------------------
// User-facing copy
//
// Fixed strings live here so wording is changed in one place and never drifts
// between two components that say the same thing.
// ---------------------------------------------------------------------------

export const COPY = {
  appTitle: 'Lenny Growth Assistant',
  tagline:
    "Ask questions about product and growth using knowledge from Lenny's Podcast.",

  connecting: 'Connecting to the assistant…',
  backendConnected: 'Backend connected',

  modelLegend: 'Model',
  loadingModels: 'Loading available models…',
  providersFailed: 'Could not load the available models.',
  noModelAvailable:
    'No model is available right now. Start Ollama locally, or configure a cloud provider, to ask a question.',

  unreachable:
    'Could not reach the assistant. Check that the backend is running.',
  timedOut: 'The assistant took too long to respond. Please try again.',
  unreadableResponse: 'The server returned an unreadable response.',
  genericFailure: 'Something went wrong. Please try again.',
} as const;
