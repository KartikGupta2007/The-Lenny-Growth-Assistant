/**
 * Shared frontend constants.
 *
 * Provider ids, error codes and route paths mirror backend/app/constants.py --
 * those are API contracts, and tests/test_constants.py asserts the two agree.
 * UI copy lives in the component that renders it.
 *
 * `as const` rather than `enum`, because tsconfig sets erasableSyntaxOnly.
 */

/** Trailing slash would double up against every path. */
export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
).replace(/\/$/, '');

/** Requests are abandoned after this long unless the caller says otherwise. */
export const DEFAULT_TIMEOUT_MS = 10_000;

export const ENDPOINTS = {
  health: '/health',
  providers: '/api/providers',
  sessions: '/api/sessions',
  artifacts: '/api/artifacts',
} as const;

/**
 * The backend has no authentication. It identifies a caller by this header and
 * the client keeps its own id in browser storage, so conversations persist per
 * browser. It identifies; it does not authenticate.
 */
export const USER_ID_HEADER = 'X-User-Id';

export const STORAGE_KEYS = {
  userId: 'lga.user-id',
  provider: 'lga.selected-provider',
  theme: 'lga.theme',
  sidebar: 'lga.sidebar-collapsed',
} as const;

/**
 * Starter questions on the landing screen. Chosen because the corpus answers
 * them well -- each maps to episodes that retrieval reliably finds.
 */
export const SUGGESTED_QUESTIONS = [
  'How should a startup think about finding product-market fit?',
  'How should I price a new product?',
  'How do I improve new user onboarding?',
  'What makes a good product roadmap?',
] as const;

/** Matches the backend's own limit on POST .../messages. */
export const MAX_MESSAGE_LENGTH = 2000;

// Order is display order in the selector: local first.
export const PROVIDER_IDS = ['ollama', 'anthropic'] as const;
export type ProviderId = (typeof PROVIDER_IDS)[number];

export const ARTIFACT_TYPES = ['markdown', 'html'] as const;
export type ArtifactType = (typeof ARTIFACT_TYPES)[number];

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

/**
 * Mirrors ERROR_* in backend/app/constants.py. The UI switches on these
 * rather than pattern-matching message text.
 */
export const ERROR_CODES = {
  internal: 'internal_error',
  configuration: 'configuration_error',
  validation: 'validation_error',
  notFound: 'not_found',
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
