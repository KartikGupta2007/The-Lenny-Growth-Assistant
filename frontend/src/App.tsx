/**
 * Application shell.
 *
 * Current scope: prove the frontend -> FastAPI boundary, surface backend
 * availability, and let the user choose the model that will answer. The
 * sidebar / chat / artifact-viewer layout from design.md section 3 is built
 * once the chat API exists.
 */

import { useEffect, useState } from 'react';

import { ApiError, fetchHealth, type HealthResponse } from './api/client';
import { ModelSelector } from './components/ModelSelector';
import { COPY, type ProviderId } from './constants';
import { useProviders } from './hooks/useProviders';

type ConnectionState =
  | { status: 'checking' }
  | { status: 'ready'; health: HealthResponse }
  | { status: 'degraded'; message: string }
  | { status: 'unreachable'; message: string };

export default function App() {
  const [connection, setConnection] = useState<ConnectionState>({
    status: 'checking',
  });
  const { state: providers, selected, select } = useProviders();

  useEffect(() => {
    const controller = new AbortController();

    fetchHealth(controller.signal)
      .then((health) => setConnection({ status: 'ready', health }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message =
          error instanceof Error ? error.message : COPY.unreachable;
        // A 503 from /health means the backend is up but a dependency is not.
        setConnection({
          status: error instanceof ApiError ? 'degraded' : 'unreachable',
          message,
        });
      });

    return () => controller.abort();
  }, []);

  const handleSelect = (id: ProviderId) => {
    select(id);
  };

  const noModelAvailable =
    providers.status === 'ready' && selected === null;

  return (
    <main className="shell">
      <header className="shell-header">
        <h1>{COPY.appTitle}</h1>
        <p className="tagline">{COPY.tagline}</p>
      </header>

      <section aria-live="polite" className="status">
        {connection.status === 'checking' && <p>{COPY.connecting}</p>}

        {connection.status === 'ready' && (
          <p className="status-ok">
            <span aria-hidden="true">●</span> {COPY.backendConnected} (
            {connection.health.environment} · v{connection.health.version})
          </p>
        )}

        {connection.status === 'degraded' && (
          <p className="status-warn">
            <span aria-hidden="true">▲</span> {connection.message}
          </p>
        )}

        {connection.status === 'unreachable' && (
          <p className="status-error">
            <span aria-hidden="true">✕</span> {connection.message}
          </p>
        )}
      </section>

      <section className="panel">
        {providers.status === 'loading' && (
          <p className="muted">{COPY.loadingModels}</p>
        )}

        {providers.status === 'error' && (
          <p className="status-error">
            <span aria-hidden="true">✕</span> {providers.message}
          </p>
        )}

        {providers.status === 'ready' && (
          <>
            <ModelSelector
              providers={providers.providers}
              selected={selected}
              onSelect={handleSelect}
            />

            {noModelAvailable && (
              <p className="status-error" role="alert">
                {COPY.noModelAvailable}
              </p>
            )}
          </>
        )}
      </section>
    </main>
  );
}
