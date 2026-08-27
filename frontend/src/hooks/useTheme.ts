/**
 * Light/dark theme.
 *
 * `system` follows the OS and stores nothing; choosing light or dark stamps
 * `data-theme` on <html>, which the stylesheet honours over the media query.
 */

import { useCallback, useEffect, useState } from 'react';

import { STORAGE_KEYS } from '../constants';

export type Theme = 'light' | 'dark' | 'system';

function stored(): Theme {
  try {
    const value = localStorage.getItem(STORAGE_KEYS.theme);
    return value === 'light' || value === 'dark' ? value : 'system';
  } catch {
    // Private browsing: the choice just does not persist.
    return 'system';
  }
}

function systemTheme(): 'light' | 'dark' {
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(stored);
  const [system, setSystem] = useState<'light' | 'dark'>(systemTheme);

  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const update = () => setSystem(media.matches ? 'dark' : 'light');
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);

    try {
      if (theme === 'system') localStorage.removeItem(STORAGE_KEYS.theme);
      else localStorage.setItem(STORAGE_KEYS.theme, theme);
    } catch {
      // Non-fatal.
    }
  }, [theme]);

  const resolved = theme === 'system' ? system : theme;
  const toggle = useCallback(
    () => setTheme(resolved === 'dark' ? 'light' : 'dark'),
    [resolved],
  );

  return { theme, resolved, toggle };
}
