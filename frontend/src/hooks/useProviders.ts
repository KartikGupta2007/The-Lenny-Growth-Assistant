/**
 * Loads the model providers and owns which one is selected.
 *
 * Selection rules, in order:
 *   1. The user's remembered choice, if that provider is still available.
 *   2. The backend's `default`, which already accounts for the environment.
 *   3. Nothing selected, when no provider is usable at all.
 *
 * Rule 1 is what stops a stale `localStorage` value from pinning the UI to
 * Ollama after the app is deployed: the stored id is validated against the
 * live list on every load rather than trusted.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { fetchProviders, type ProviderStatus } from '../api/client';
import {
  COPY,
  isProviderId,
  STORAGE_KEYS,
  type ProviderId,
} from '../constants';

function readStoredProvider(): ProviderId | null {
  try {
    const value = localStorage.getItem(STORAGE_KEYS.selectedProvider);
    return isProviderId(value) ? value : null;
  } catch {
    // Private browsing / disabled site data. Selection just does not persist.
    return null;
  }
}

function storeProvider(id: ProviderId): void {
  try {
    localStorage.setItem(STORAGE_KEYS.selectedProvider, id);
  } catch {
    // Non-fatal: the session still works, it just will not be remembered.
  }
}

export type ProvidersState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; providers: ProviderStatus[] };

export interface UseProviders {
  state: ProvidersState;
  /** The selected provider, or `null` when none is usable. */
  selected: ProviderId | null;
  /** Rejects a provider that is not available; returns whether it took. */
  select: (id: ProviderId) => boolean;
  reload: () => void;
}

export function useProviders(): UseProviders {
  const [state, setState] = useState<ProvidersState>({ status: 'loading' });
  const [selected, setSelected] = useState<ProviderId | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    fetchProviders(controller.signal)
      .then((response) => {
        setState({ status: 'ready', providers: response.providers });

        const available = new Set(
          response.providers.filter((p) => p.available).map((p) => p.id),
        );
        const stored = readStoredProvider();
        const resolved =
          stored && available.has(stored)
            ? stored
            : response.default && available.has(response.default)
              ? response.default
              : null;
        setSelected(resolved);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: 'error',
          message:
            error instanceof Error ? error.message : COPY.providersFailed,
        });
      });

    return () => controller.abort();
  }, [reloadToken]);

  const select = useCallback(
    (id: ProviderId): boolean => {
      if (state.status !== 'ready') return false;
      const provider = state.providers.find((p) => p.id === id);
      if (!provider?.available) return false;
      setSelected(id);
      storeProvider(id);
      return true;
    },
    [state],
  );

  const reload = useCallback(() => setReloadToken((n) => n + 1), []);

  return useMemo(
    () => ({ state, selected, select, reload }),
    [state, selected, select, reload],
  );
}
