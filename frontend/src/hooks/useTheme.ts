import { useCallback, useEffect, useSyncExternalStore } from 'react';

type Theme = 'system' | 'light' | 'dark';

const STORAGE_KEY = 'theme';

function getStoredTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return 'system';
}

function applyTheme(theme: Theme) {
  const isDark =
    theme === 'dark' ||
    (theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);

  document.documentElement.classList.toggle('dark', isDark);
}

let listeners: Array<() => void> = [];
let currentTheme: Theme = getStoredTheme();

function subscribe(listener: () => void) {
  listeners = [...listeners, listener];
  return () => {
    listeners = listeners.filter(l => l !== listener);
  };
}

function getSnapshot(): Theme {
  return currentTheme;
}

function setTheme(theme: Theme) {
  currentTheme = theme;
  if (theme === 'system') {
    localStorage.removeItem(STORAGE_KEY);
  } else {
    localStorage.setItem(STORAGE_KEY, theme);
  }
  applyTheme(theme);
  listeners.forEach(l => l());
}

// Listen for OS preference changes (affects "system" mode)
if (typeof window !== 'undefined') {
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (currentTheme === 'system') {
      applyTheme('system');
    }
  });
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getSnapshot);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const cycle = useCallback(() => {
    const order: Theme[] = ['system', 'light', 'dark'];
    const next = order[(order.indexOf(theme) + 1) % order.length];
    setTheme(next);
  }, [theme]);

  return { theme, setTheme, cycle };
}
