/**
 * Theme definitions — 绿色四季 (W5-3 UI 重构)
 *
 * 4 套主题对应春夏秋冬的绿:
 *   spring  (原 key: dark-stone)     嫩芽黄绿, 明亮清新
 *   summer  (原 key: light-clean)    浓郁翠绿, 生机勃勃
 *   autumn  (原 key: sepia-warm)     苔绿 + 暖金, 沉静温润
 *   winter  (原 key: midnight-blue)  松柏墨绿, 深邃静谧
 *
 * key 名保留旧值以兼容 localStorage / 类型, 显示名/配色全部换成绿色系。
 * 每套新增 `season` 字段供枝桠背景 (BranchCanopy) 取色。
 */

export type ThemeId = 'dark-stone' | 'light-clean' | 'sepia-warm' | 'midnight-blue';
export type Season = 'spring' | 'summer' | 'autumn' | 'winter';

export interface ThemeTokens {
  id: ThemeId;
  name: string;
  emoji: string;
  description: string;
  isDark: boolean;
  season: Season;
  tokens: Record<string, string>;
}

const baseFontFamily = [
  '"Plus Jakarta Sans"',
  '"Noto Sans SC"',
  '"Nunito"',
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
  '--font-size-base': '15px',
  '--line-height-base': '1.7',
  '--sp-1': '4px', '--sp-2': '8px', '--sp-3': '12px',
  '--sp-4': '16px', '--sp-5': '20px', '--sp-6': '24px',
  '--sp-8': '32px', '--sp-10': '40px', '--sp-12': '48px',
  '--r-sm': '6px', '--r-md': '10px', '--r-lg': '14px',
  '--r-xl': '18px', '--r-2xl': '24px', '--r-full': '9999px',
  '--t-fast': '0.14s ease',
  '--t-normal': '0.24s cubic-bezier(0.22, 1, 0.36, 1)',
};

export const themes: Record<ThemeId, ThemeTokens> = {
  // ── 春 · 嫩芽 (明亮浅绿) ──
  'dark-stone': {
    id: 'dark-stone',
    name: '春·嫩芽',
    emoji: '🌱',
    description: '嫩芽黄绿, 明亮清新的初春气息',
    isDark: false,
    season: 'spring',
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#f3f8ec',
      '--bg-secondary': 'rgba(233, 243, 219, 0.72)',
      '--bg-tertiary':  'rgba(214, 232, 190, 0.72)',
      '--bg-card':      'rgba(249, 252, 242, 0.78)',
      '--bg-hover':     'rgba(132, 204, 22, 0.12)',
      '--bg-inset':     'rgba(226, 238, 208, 0.7)',
      '--bg-glass':     'rgba(247, 251, 238, 0.64)',

      '--accent':        '#4d9a2a',
      '--accent-hover':  '#5fb536',
      '--accent-subtle': 'rgba(132, 204, 22, 0.16)',
      '--accent-border': 'rgba(77, 154, 42, 0.4)',

      '--text-primary':   '#22331a',
      '--text-secondary': '#3c5230',
      '--text-tertiary':  '#5c7049',
      '--text-muted':     '#87996f',

      '--success': '#4d9a2a',
      '--success-subtle': 'rgba(77, 154, 42, 0.12)',
      '--warning': '#c98a1a',
      '--warning-subtle': 'rgba(201, 138, 26, 0.15)',
      '--danger': '#c2410c',
      '--danger-subtle': 'rgba(194, 65, 12, 0.12)',

      '--border':       'rgba(60, 82, 48, 0.14)',
      '--border-hover': 'rgba(60, 82, 48, 0.26)',
      '--border-light': 'rgba(60, 82, 48, 0.07)',

      '--bubble-user-bg-start': '#6bbf3a',
      '--bubble-user-bg-end':   '#4d9a2a',
      '--bubble-user-text':     '#ffffff',
      '--bubble-agent-bg':      'rgba(249, 252, 242, 0.9)',
      '--bubble-agent-border':  'rgba(60, 82, 48, 0.1)',
      '--bubble-agent-text':    '#22331a',
      '--avatar-user-start':    '#8bd450',
      '--avatar-user-end':      '#4d9a2a',
      '--avatar-agent-start':   '#a3d977',
      '--avatar-agent-end':     '#5fb536',

      '--shadow-sm': '0 1px 2px rgba(45, 70, 30, 0.08)',
      '--shadow-md': '0 6px 20px rgba(45, 70, 30, 0.12)',
      '--shadow-lg': '0 16px 48px rgba(45, 70, 30, 0.16)',
    },
  },

  // ── 夏 · 浓翠 (深色饱和绿) ──
  'light-clean': {
    id: 'light-clean',
    name: '夏·浓翠',
    emoji: '🌿',
    description: '浓郁翠绿, 生机勃勃的盛夏林荫',
    isDark: true,
    season: 'summer',
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#0c1a0f',
      '--bg-secondary': 'rgba(18, 38, 24, 0.72)',
      '--bg-tertiary':  'rgba(30, 58, 38, 0.72)',
      '--bg-card':      'rgba(16, 34, 22, 0.7)',
      '--bg-hover':     'rgba(74, 222, 128, 0.12)',
      '--bg-inset':     'rgba(9, 22, 14, 0.7)',
      '--bg-glass':     'rgba(14, 30, 20, 0.62)',

      '--accent':        '#34d058',
      '--accent-hover':  '#5ee87b',
      '--accent-subtle': 'rgba(52, 208, 88, 0.16)',
      '--accent-border': 'rgba(52, 208, 88, 0.4)',

      '--text-primary':   '#eafff0',
      '--text-secondary': '#c2e8cd',
      '--text-tertiary':  '#8bbf9a',
      '--text-muted':     '#5f8a6d',

      '--success': '#34d058',
      '--success-subtle': 'rgba(52, 208, 88, 0.14)',
      '--warning': '#e5b135',
      '--warning-subtle': 'rgba(229, 177, 53, 0.15)',
      '--danger': '#f87171',
      '--danger-subtle': 'rgba(248, 113, 113, 0.12)',

      '--border':       'rgba(120, 200, 150, 0.12)',
      '--border-hover': 'rgba(120, 200, 150, 0.22)',
      '--border-light': 'rgba(120, 200, 150, 0.06)',

      '--bubble-user-bg-start': '#34d058',
      '--bubble-user-bg-end':   '#15803d',
      '--bubble-user-text':     '#04140a',
      '--bubble-agent-bg':      'rgba(20, 40, 27, 0.9)',
      '--bubble-agent-border':  'rgba(120, 200, 150, 0.1)',
      '--bubble-agent-text':    '#dcf5e4',
      '--avatar-user-start':    '#5ee87b',
      '--avatar-user-end':      '#15803d',
      '--avatar-agent-start':   '#34d058',
      '--avatar-agent-end':     '#0d9488',

      '--shadow-sm': '0 1px 2px rgba(0,0,0,0.4)',
      '--shadow-md': '0 6px 20px rgba(0,0,0,0.5)',
      '--shadow-lg': '0 16px 48px rgba(0,0,0,0.6)',
    },
  },

  // ── 秋 · 苔金 (暖调低饱和绿) ──
  'sepia-warm': {
    id: 'sepia-warm',
    name: '秋·苔金',
    emoji: '🍃',
    description: '苔绿 + 暖金, 沉静温润的深秋',
    isDark: false,
    season: 'autumn',
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#eef0df',
      '--bg-secondary': 'rgba(226, 229, 205, 0.74)',
      '--bg-tertiary':  'rgba(206, 210, 178, 0.74)',
      '--bg-card':      'rgba(244, 246, 228, 0.8)',
      '--bg-hover':     'rgba(120, 140, 60, 0.12)',
      '--bg-inset':     'rgba(219, 223, 194, 0.7)',
      '--bg-glass':     'rgba(240, 242, 224, 0.64)',

      '--accent':        '#6d8b2f',
      '--accent-hover':  '#809f3c',
      '--accent-subtle': 'rgba(109, 139, 47, 0.14)',
      '--accent-border': 'rgba(109, 139, 47, 0.34)',

      '--text-primary':   '#2f3320',
      '--text-secondary': '#4a4f33',
      '--text-tertiary':  '#6b704f',
      '--text-muted':     '#93976f',

      '--success': '#6d8b2f',
      '--success-subtle': 'rgba(109, 139, 47, 0.12)',
      '--warning': '#c07d1e',
      '--warning-subtle': 'rgba(192, 125, 30, 0.15)',
      '--danger': '#b3492a',
      '--danger-subtle': 'rgba(179, 73, 42, 0.1)',

      '--border':       'rgba(47, 51, 32, 0.13)',
      '--border-hover': 'rgba(47, 51, 32, 0.22)',
      '--border-light': 'rgba(47, 51, 32, 0.06)',

      '--bubble-user-bg-start': '#8ba33f',
      '--bubble-user-bg-end':   '#6d8b2f',
      '--bubble-user-text':     '#fbfced',
      '--bubble-agent-bg':      'rgba(244, 246, 228, 0.9)',
      '--bubble-agent-border':  'rgba(47, 51, 32, 0.1)',
      '--bubble-agent-text':    '#2f3320',
      '--avatar-user-start':    '#a8bf5e',
      '--avatar-user-end':      '#6d8b2f',
      '--avatar-agent-start':   '#c9a227',
      '--avatar-agent-end':     '#809f3c',

      '--shadow-sm': '0 1px 2px rgba(60, 64, 30, 0.1)',
      '--shadow-md': '0 6px 20px rgba(60, 64, 30, 0.14)',
      '--shadow-lg': '0 16px 48px rgba(60, 64, 30, 0.18)',
    },
  },

  // ── 冬 · 松墨 (深邃墨绿) ──
  'midnight-blue': {
    id: 'midnight-blue',
    name: '冬·松墨',
    emoji: '🌲',
    description: '松柏墨绿, 深邃静谧的寒冬',
    isDark: true,
    season: 'winter',
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#0a1512',
      '--bg-secondary': 'rgba(16, 30, 26, 0.74)',
      '--bg-tertiary':  'rgba(26, 46, 40, 0.74)',
      '--bg-card':      'rgba(14, 28, 24, 0.72)',
      '--bg-hover':     'rgba(45, 212, 191, 0.1)',
      '--bg-inset':     'rgba(7, 18, 15, 0.72)',
      '--bg-glass':     'rgba(12, 26, 22, 0.64)',

      '--accent':        '#2fb391',
      '--accent-hover':  '#4bd0ad',
      '--accent-subtle': 'rgba(47, 179, 145, 0.15)',
      '--accent-border': 'rgba(47, 179, 145, 0.36)',

      '--text-primary':   '#e4f5ee',
      '--text-secondary': '#bcdccf',
      '--text-tertiary':  '#84a89a',
      '--text-muted':     '#587569',

      '--success': '#2fb391',
      '--success-subtle': 'rgba(47, 179, 145, 0.13)',
      '--warning': '#d1a43a',
      '--warning-subtle': 'rgba(209, 164, 58, 0.15)',
      '--danger': '#f08a7a',
      '--danger-subtle': 'rgba(240, 138, 122, 0.12)',

      '--border':       'rgba(120, 190, 170, 0.12)',
      '--border-hover': 'rgba(120, 190, 170, 0.22)',
      '--border-light': 'rgba(120, 190, 170, 0.06)',

      '--bubble-user-bg-start': '#2fb391',
      '--bubble-user-bg-end':   '#0f766e',
      '--bubble-user-text':     '#ffffff',
      '--bubble-agent-bg':      'rgba(18, 34, 29, 0.9)',
      '--bubble-agent-border':  'rgba(120, 190, 170, 0.1)',
      '--bubble-agent-text':    '#dcefe7',
      '--avatar-user-start':    '#4bd0ad',
      '--avatar-user-end':      '#0f766e',
      '--avatar-agent-start':   '#2fb391',
      '--avatar-agent-end':     '#3b7a6b',

      '--shadow-sm': '0 1px 2px rgba(0,0,0,0.4)',
      '--shadow-md': '0 6px 20px rgba(0,0,0,0.5)',
      '--shadow-lg': '0 16px 48px rgba(0,0,0,0.6)',
    },
  },
};

export const themeList: ThemeTokens[] = Object.values(themes);

export const DEFAULT_THEME: ThemeId = 'dark-stone';
