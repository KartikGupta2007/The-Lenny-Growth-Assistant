/**
 * Light/dark theme.
 *
 * Light is the default; the operating system is not consulted. The choice is
 * stamped on <html> as `data-theme`, which the stylesheet reads. A matching
 * inline script in index.html applies a stored dark choice before first paint.
 */

import { useCallback, useEffect, useState } from 'react';

import { STORAGE_KEYS } from '../constants';

export type Theme = 'light' | 'dark';

function stored(): Theme {
  try {
    return localStorage.getItem(STORAGE_KEYS.theme) === 'dark' ? 'dark' : 'light';
  } catch {
    // Private browsing: the choice just does not persist.
    return 'light';
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(stored);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem(STORAGE_KEYS.theme, theme);
    } catch {
      // Non-fatal.
    }
  }, [theme]);

  const toggle = useCallback(
    () => setTheme((current) => (current === 'dark' ? 'light' : 'dark')),
    [],
  );

  return { theme, toggle };
}
