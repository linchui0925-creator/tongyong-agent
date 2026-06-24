/**
 * Theme context + localStorage 持久化 (W4-30)
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { DEFAULT_THEME, themes, type ThemeId } from './themes';

const STORAGE_KEY = 'tongyong-theme';

interface ThemeContextValue {
  theme: ThemeId;
  setTheme: (id: ThemeId) => void;
  cycleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function loadStoredTheme(): ThemeId {
  if (typeof window === 'undefined') return DEFAULT_THEME;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored && stored in themes) return stored as ThemeId;
  } catch (e) {
    // localStorage 不可用, 用 default
  }
  return DEFAULT_THEME;
}

function applyTheme(id: ThemeId) {
  if (typeof document === 'undefined') return;
  const theme = themes[id];
  const root = document.documentElement;
  root.setAttribute('data-theme', id);
  root.style.colorScheme = theme.isDark ? 'dark' : 'light';
  for (const [k, v] of Object.entries(theme.tokens)) {
    root.style.setProperty(k, v);
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeId>(loadStoredTheme);

  useEffect(() => {
    applyTheme(theme);
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      // ignore
    }
  }, [theme]);

  const setTheme = useCallback((id: ThemeId) => {
    setThemeState(id);
  }, []);

  const cycleTheme = useCallback(() => {
    setThemeState((cur) => {
      const ids = Object.keys(themes) as ThemeId[];
      const i = ids.indexOf(cur);
      return ids[(i + 1) % ids.length];
    });
  }, []);

  const value = useMemo(() => ({ theme, setTheme, cycleTheme }), [theme, setTheme, cycleTheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    // 在 ThemeProvider 外调用时降级到 default
    return { theme: DEFAULT_THEME, setTheme: () => {}, cycleTheme: () => {} } satisfies ThemeContextValue;
  }
  return ctx;
}
