/**
 * Theme switcher — chat header 上的主题切换下拉 (W4-30)
 */

import { useEffect, useRef, useState } from 'react';
import { useTheme } from '../../theme/ThemeContext';
import { themeList, type ThemeId } from '../../theme/themes';
import './ThemeSwitcher.css';

export function ThemeSwitcher() {
  const { theme, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const current = themeList.find((t) => t.id === theme)!;

  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [open]);

  return (
    <div className="theme-switcher" ref={ref}>
      <button
        className="theme-switcher-trigger"
        onClick={() => setOpen(!open)}
        title={`主题: ${current.name}`}
        aria-label="切换主题"
      >
        <span className="theme-switcher-emoji">{current.emoji}</span>
        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="theme-switcher-caret">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {open && (
        <div className="theme-switcher-dropdown" role="menu">
          <div className="theme-switcher-label">选择主题</div>
          {themeList.map((t) => (
            <button
              key={t.id}
              className={`theme-switcher-option ${t.id === theme ? 'is-active' : ''}`}
              onClick={() => { setTheme(t.id as ThemeId); setOpen(false); }}
              role="menuitem"
            >
              <span className="theme-switcher-swatch">
                <span
                  className="theme-swatch-preview"
                  style={{
                    background: `linear-gradient(135deg, ${t.tokens['--avatar-user-start']} 0%, ${t.tokens['--avatar-user-end']} 50%, ${t.tokens['--bg-primary']} 50%, ${t.tokens['--bg-primary']} 100%)`,
                    borderColor: t.tokens['--border'],
                  }}
                />
                <span
                  className="theme-swatch-accent"
                  style={{ background: t.tokens['--accent'] }}
                />
              </span>
              <span className="theme-switcher-info">
                <span className="theme-switcher-name">
                  {t.emoji} {t.name}
                </span>
                <span className="theme-switcher-desc">{t.description}</span>
              </span>
              {t.id === theme && (
                <span className="theme-switcher-check">✓</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
