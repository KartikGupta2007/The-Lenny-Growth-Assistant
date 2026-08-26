/**
 * The single boundary between the frontend and the FastAPI backend.
 *
 * Every network call in the app goes through `request` below. The frontend
 * never talks to a model provider, the database, or the retrieval layer
 * directly -- those are backend concerns.
 */

import {
  API_BASE_URL,
  COPY,
  DEFAULT_TIMEOUT_MS,
  ENDPOINTS,
  ERROR_CODES,
  ERROR_NAMES,
  type ProviderId,
  type ProviderKind,
} from '../constants';

/** Shape of the backend's structured error envelope. */
interface ErrorEnvelope {
  error: { code: string; message: string };
}

/**
 * An error carrying the backend's machine-readable code, so the UI can react
 * to a specific failure (for example `provider_unavailable`) rather than
 * pattern-matching on message text.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = ERROR_NAMES.api;
    this.code = code;
    this.status = status;
  }
}

/** Raised when the backend did not answer within the request timeout. */
export class TimeoutError extends Error {
  constructor() {
    super(COPY.timedOut);
    this.name = ERROR_NAMES.timeout;
  }
}

/** Raised when the backend cannot be reached at all. */
export class NetworkError extends Error {
  constructor() {
    super(COPY.unreachable);
    this.name = ERROR_NAMES.network;
  }
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== 'object' || value === null || !('error' in value)) {
    return false;
  }
  const { error } = value as { error: unknown };
  return (
    typeof error === 'object' &&
    error !== null &&
    'code' in error &&
    'message' in error
  );
}

/**
 * Perform a JSON request against the backend.
 *
 * Translates the backend error envelope into `ApiError` and transport
 * failures into `NetworkError`, so callers never handle raw fetch semantics.
 */
export async function request<T>(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal, ...rest } = init;

  // A hung backend must not leave the UI spinning forever. The caller's own
  // signal (used for unmount cancellation) is combined with the timeout so
  // whichever fires first aborts the request.
  const timeout = AbortSignal.timeout(timeoutMs);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      signal: combined,
      headers: {
        'Content-Type': 'application/json',
        ...(init.headers ?? {}),
      },
    });
  } catch (error) {
    // An abort the caller asked for is not a failure to report.
    if (signal?.aborted) throw error;
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      throw new TimeoutError();
    }
    throw new NetworkError();
  }

  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? (JSON.parse(text) as unknown) : null;
  } catch {
    // A proxy or gateway can return HTML on an error; do not let a parse
    // failure surface as an unhandled exception.
    throw new ApiError(
      ERROR_CODES.invalidResponse,
      COPY.unreadableResponse,
      response.status,
    );
  }

  if (!response.ok) {
    if (isErrorEnvelope(body)) {
      throw new ApiError(body.error.code, body.error.message, response.status);
    }
    throw new ApiError(
      ERROR_CODES.unexpected,
      COPY.genericFailure,
      response.status,
    );
  }

  return body as T;
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export interface DependencyStatus {
  name: string;
  healthy: boolean;
  detail: string | null;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  environment: string;
  version: string;
  dependencies: DependencyStatus[];
}

/**
 * Fetch backend health. A `degraded` backend answers with HTTP 503 and a
 * populated body, so the payload is read from the error path too.
 */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request<HealthResponse>(ENDPOINTS.health, { signal });
}

// ---------------------------------------------------------------------------
// Model providers
// ---------------------------------------------------------------------------

/**
 * One entry in the model selector.
 *
 * `available` is the only flag the UI switches on. A provider that is not
 * available is still rendered -- disabled, with `reason` explaining why --
 * so the option does not silently disappear between environments.
 */
export interface ProviderStatus {
  id: ProviderId;
  label: string;
  kind: ProviderKind;
  model: string;
  available: boolean;
  reason: string | null;
}

export interface ProvidersResponse {
  providers: ProviderStatus[];
  /** `null` when nothing is usable; the UI must then block sending. */
  default: ProviderId | null;
}

export async function fetchProviders(
  signal?: AbortSignal,
): Promise<ProvidersResponse> {
  return request<ProvidersResponse>(ENDPOINTS.providers, { signal });
}
