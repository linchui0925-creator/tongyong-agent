/**
 * Theme definitions (W4-30)
 *
 * 4 套主题: 深色 (默认) / 浅色 / 护眼暖 / 暗夜蓝
 * 每套覆盖 --bg-*, --text-*, --accent-*, --bubble-*, --border-*
 */

export type ThemeId = 'dark-stone' | 'light-clean' | 'sepia-warm' | 'midnight-blue';

export interface ThemeTokens {
  id: ThemeId;
  name: string;
  emoji: string;
  description: string;
  isDark: boolean;
  tokens: Record<string, string>;
}

const baseFontFamily = [
  '"Inter"',
  '-apple-system',
  'BlinkMacSystemFont',
  '"PingFang SC"',
  '"Microsoft YaHei"',
  '"Hiragino Sans GB"',
  '"Noto Sans SC"',
  '"Helvetica Neue"',
  'Helvetica',
  'Arial',
  'sans-serif',
].join(', ');

const monoFontFamily = [
  '"JetBrains Mono"',
  '"SF Mono"',
  'Menlo',
  'Consolas',
  '"Liberation Mono"',
  'monospace',
].join(', ');

const baseTokens = {
  '--font': baseFontFamily,
  '--font-mono': monoFontFamily,
  '--font-size-base': '14.5px',
  '--line-height-base': '1.65',
  '--sp-1': '4px', '--sp-2': '8px', '--sp-3': '12px',
  '--sp-4': '16px', '--sp-5': '20px', '--sp-6': '24px',
  '--sp-8': '32px', '--sp-10': '40px', '--sp-12': '48px',
  '--r-sm': '4px', '--r-md': '6px', '--r-lg': '8px',
  '--r-xl': '12px', '--r-2xl': '16px', '--r-full': '9999px',
  '--t-fast': '0.12s ease',
  '--t-normal': '0.2s ease',
};

export const themes: Record<ThemeId, ThemeTokens> = {
  // ── 1. 深色石 (默认) ──
  'dark-stone': {
    id: 'dark-stone',
    name: '深色石',
    emoji: '🌑',
    description: '暖琥珀 accent 的深色主题, 经典氛围',
    isDark: true,
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#1c1917',
      '--bg-secondary': '#292524',
      '--bg-tertiary':  '#3f3a36',
      '--bg-card':      '#2e2926',
      '--bg-hover':     '#3f3a36',
      '--bg-inset':     '#141110',
      '--bg-glass':     'rgba(41, 37, 36, 0.85)',

      '--accent':        '#f59e0b',
      '--accent-hover':  '#fbbf24',
      '--accent-subtle': 'rgba(245, 158, 11, 0.15)',
      '--accent-border': 'rgba(245, 158, 11, 0.35)',

      '--text-primary':   '#f5f5f4',
      '--text-secondary': '#d6d3d1',
      '--text-tertiary':  '#a8a29e',
      '--text-muted':     '#78716c',

      '--success': '#84cc16',
      '--success-subtle': 'rgba(132, 204, 22, 0.12)',
      '--warning': '#f59e0b',
      '--warning-subtle': 'rgba(245, 158, 11, 0.15)',
      '--danger': '#f87171',
      '--danger-subtle': 'rgba(248, 113, 113, 0.12)',

      '--border':       'rgba(255, 255, 255, 0.08)',
      '--border-hover': 'rgba(255, 255, 255, 0.14)',
      '--border-light': 'rgba(255, 255, 255, 0.05)',

      // Chat-specific
      '--bubble-user-bg-start': '#4F46E5',
      '--bubble-user-bg-end':   '#3B82F6',
      '--bubble-user-text':     '#FFFFFF',
      '--bubble-agent-bg':      '#2A2A2D',
      '--bubble-agent-border':  'rgba(255, 255, 255, 0.06)',
      '--bubble-agent-text':    '#E5E7EB',
      '--avatar-user-start':    '#6366F1',
      '--avatar-user-end':      '#8B5CF6',
      '--avatar-agent-start':   '#10B981',
      '--avatar-agent-end':     '#06B6D4',

      '--shadow-sm': '0 1px 2px rgba(0,0,0,0.4)',
      '--shadow-md': '0 4px 12px rgba(0,0,0,0.5)',
      '--shadow-lg': '0 8px 32px rgba(0,0,0,0.6)',
    },
  },

  // ── 2. 浅色 (iOS 风) ──
  'light-clean': {
    id: 'light-clean',
    name: '浅色简',
    emoji: '☀️',
    description: '白底 + 蓝紫 accent, 清新简洁',
    isDark: false,
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#FFFFFF',
      '--bg-secondary': '#F9FAFB',
      '--bg-tertiary':  '#F3F4F6',
      '--bg-card':      '#FFFFFF',
      '--bg-hover':     '#F3F4F6',
      '--bg-inset':     '#F3F4F6',
      '--bg-glass':     'rgba(255, 255, 255, 0.85)',

      '--accent':        '#3B82F6',
      '--accent-hover':  '#2563EB',
      '--accent-subtle': 'rgba(59, 130, 246, 0.10)',
      '--accent-border': 'rgba(59, 130, 246, 0.30)',

      '--text-primary':   '#111827',
      '--text-secondary': '#4B5563',
      '--text-tertiary':  '#6B7280',
      '--text-muted':     '#9CA3AF',

      '--success': '#10B981',
      '--success-subtle': 'rgba(16, 185, 129, 0.10)',
      '--warning': '#F59E0B',
      '--warning-subtle': 'rgba(245, 158, 11, 0.10)',
      '--danger': '#EF4444',
      '--danger-subtle': 'rgba(239, 68, 68, 0.08)',

      '--border':       'rgba(0, 0, 0, 0.08)',
      '--border-hover': 'rgba(0, 0, 0, 0.14)',
      '--border-light': 'rgba(0, 0, 0, 0.04)',

      '--bubble-user-bg-start': '#3B82F6',
      '--bubble-user-bg-end':   '#6366F1',
      '--bubble-user-text':     '#FFFFFF',
      '--bubble-agent-bg':      '#F3F4F6',
      '--bubble-agent-border':  'rgba(0, 0, 0, 0.06)',
      '--bubble-agent-text':    '#1F2937',
      '--avatar-user-start':    '#6366F1',
      '--avatar-user-end':      '#8B5CF6',
      '--avatar-agent-start':   '#0EA5E9',
      '--avatar-agent-end':     '#06B6D4',

      '--shadow-sm': '0 1px 2px rgba(0,0,0,0.04)',
      '--shadow-md': '0 4px 12px rgba(0,0,0,0.08)',
      '--shadow-lg': '0 8px 32px rgba(0,0,0,0.10)',
    },
  },

  // ── 3. 护眼暖 (Sepia) ──
  'sepia-warm': {
    id: 'sepia-warm',
    name: '护眼暖',
    emoji: '📖',
    description: '米黄底 + 棕红 accent, 长时间阅读不累',
    isDark: false,
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#F4ECD8',
      '--bg-secondary': '#EBE0C7',
      '--bg-tertiary':  '#DCD0B4',
      '--bg-card':      '#F9F2DD',
      '--bg-hover':     '#DCD0B4',
      '--bg-inset':     '#E5D8B8',
      '--bg-glass':     'rgba(244, 236, 216, 0.85)',

      '--accent':        '#A0522D',
      '--accent-hover':  '#8B4513',
      '--accent-subtle': 'rgba(160, 82, 45, 0.12)',
      '--accent-border': 'rgba(160, 82, 45, 0.30)',

      '--text-primary':   '#3E2C1C',
      '--text-secondary': '#5C4A38',
      '--text-tertiary':  '#7A6448',
      '--text-muted':     '#9B8466',

      '--success': '#658B47',
      '--success-subtle': 'rgba(101, 139, 71, 0.12)',
      '--warning': '#C68C2E',
      '--warning-subtle': 'rgba(198, 140, 46, 0.15)',
      '--danger': '#B33A3A',
      '--danger-subtle': 'rgba(179, 58, 58, 0.10)',

      '--border':       'rgba(62, 44, 28, 0.12)',
      '--border-hover': 'rgba(62, 44, 28, 0.20)',
      '--border-light': 'rgba(62, 44, 28, 0.06)',

      '--bubble-user-bg-start': '#A0522D',
      '--bubble-user-bg-end':   '#8B4513',
      '--bubble-user-text':     '#FBF5E5',
      '--bubble-agent-bg':      '#F9F2DD',
      '--bubble-agent-border':  'rgba(62, 44, 28, 0.10)',
      '--bubble-agent-text':    '#3E2C1C',
      '--avatar-user-start':    '#A0522D',
      '--avatar-user-end':      '#CD853F',
      '--avatar-agent-start':   '#658B47',
      '--avatar-agent-end':     '#8FBC8F',

      '--shadow-sm': '0 1px 2px rgba(62, 44, 28, 0.10)',
      '--shadow-md': '0 4px 12px rgba(62, 44, 28, 0.15)',
      '--shadow-lg': '0 8px 32px rgba(62, 44, 28, 0.20)',
    },
  },

  // ── 4. 暗夜蓝 (Midnight) ──
  'midnight-blue': {
    id: 'midnight-blue',
    name: '暗夜蓝',
    emoji: '🌊',
    description: '深蓝底 + 青蓝 accent, 静谧专业',
    isDark: true,
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#0F172A',
      '--bg-secondary': '#1E293B',
      '--bg-tertiary':  '#334155',
      '--bg-card':      '#1E293B',
      '--bg-hover':     '#334155',
      '--bg-inset':     '#0A0F1F',
      '--bg-glass':     'rgba(30, 41, 59, 0.85)',

      '--accent':        '#06B6D4',
      '--accent-hover':  '#22D3EE',
      '--accent-subtle': 'rgba(6, 182, 212, 0.15)',
      '--accent-border': 'rgba(6, 182, 212, 0.35)',

      '--text-primary':   '#F1F5F9',
      '--text-secondary': '#CBD5E1',
      '--text-tertiary':  '#94A3B8',
      '--text-muted':     '#64748B',

      '--success': '#22C55E',
      '--success-subtle': 'rgba(34, 197, 94, 0.12)',
      '--warning': '#EAB308',
      '--warning-subtle': 'rgba(234, 179, 8, 0.15)',
      '--danger': '#F87171',
      '--danger-subtle': 'rgba(248, 113, 113, 0.12)',

      '--border':       'rgba(148, 163, 184, 0.12)',
      '--border-hover': 'rgba(148, 163, 184, 0.20)',
      '--border-light': 'rgba(148, 163, 184, 0.06)',

      '--bubble-user-bg-start': '#0EA5E9',
      '--bubble-user-bg-end':   '#6366F1',
      '--bubble-user-text':     '#FFFFFF',
      '--bubble-agent-bg':      '#1E293B',
      '--bubble-agent-border':  'rgba(148, 163, 184, 0.10)',
      '--bubble-agent-text':    '#E2E8F0',
      '--avatar-user-start':    '#6366F1',
      '--avatar-user-end':      '#8B5CF6',
      '--avatar-agent-start':   '#06B6D4',
      '--avatar-agent-end':     '#3B82F6',

      '--shadow-sm': '0 1px 2px rgba(0,0,0,0.4)',
      '--shadow-md': '0 4px 12px rgba(0,0,0,0.5)',
      '--shadow-lg': '0 8px 32px rgba(0,0,0,0.6)',
    },
  },
};

export const themeList: ThemeTokens[] = Object.values(themes);

export const DEFAULT_THEME: ThemeId = 'dark-stone';
