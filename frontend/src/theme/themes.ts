/**
 * Theme definitions — 维知 四材 (W5-3 材质感主题)
 *
 * 4 套主题对应 4 个真正不同的材质, 互相配色不重叠:
 *   墨·朱砂 (key: dark-stone)      暖白宣纸 + 墨黑 + 朱砂红 — 古典水墨
 *   纸·碧玉 (key: light-clean)     冷翡翠纸 + 深碧 + 翠绿 — 文房青绿
 *   铜·金箔 (key: sepia-warm)      深古铜底 + 金箔 + 琥珀 — 金属暖调
 *   夜·电青 (key: midnight-blue)  深电青底 + 亮青电光 — 合成器夜色
 *
 * key 名保留旧值以兼容 localStorage / 类型, 显示名/配色全部换成材质系。
 * 每套材质新增多 accent 字段 (--accent / --accent-2 / --accent-3 / --accent-4)
 * 供拓扑线场 (AmbientScene) 取色分层。
 *
 * 字体: 飘逸 + 大气 — display 用楷体/宋体轻量栈, body 用无衬线系统栈。
 */

export type ThemeId = 'dark-stone' | 'light-clean' | 'sepia-warm' | 'midnight-blue';
export type Material = 'ink-cinnabar' | 'paper-jade' | 'copper-gold' | 'night-cyan';

export interface ThemeTokens {
  id: ThemeId;
  /** 显示名 (中文, 用于 ThemeSwitcher) */
  name: string;
  /** 中文单字标记, 用于侧栏紧凑按钮 */
  glyph: string;
  description: string;
  isDark: boolean;
  material: Material;
  tokens: Record<string, string>;
}

// 飘逸 + 大气 display stack
const displayFontFamily = [
  '"马善政体"',
  '"方正清刻本悦宋"',
  '"方正宋刻本悦宋"',
  '"STKaiti"',
  '"Kaiti SC"',
  '"Kaiti"',
  '"Hannotate SC"',
  '"Hiragino Mincho ProN"',
  '"Songti SC"',
  '"Source Han Serif SC"',
  '"Noto Serif SC"',
  'STZhongsong',
  '"PingFang SC"',
  '"Microsoft YaHei"',
  'serif',
].join(', ');

// body 用冷静无衬线系统栈
const baseFontFamily = [
  '"Inter"',
  '"SF Pro Text"',
  '"Noto Sans SC"',
  '"PingFang SC"',
  '"Hiragino Sans GB"',
  '-apple-system',
  'BlinkMacSystemFont',
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
  '--font-display': displayFontFamily,
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
  // ── 墨·朱砂 — 暖白宣纸 + 墨黑 + 朱砂 ──
  'dark-stone': {
    id: 'dark-stone',
    name: '墨·朱砂',
    glyph: '墨',
    description: '暖白宣纸, 朱砂红点睛, 端庄大气',
    isDark: false,
    material: 'ink-cinnabar',
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#f4eee0',
      '--bg-secondary': 'rgba(232, 220, 200, 0.72)',
      '--bg-tertiary':  'rgba(216, 200, 174, 0.7)',
      '--bg-card':      'rgba(248, 242, 230, 0.82)',
      '--bg-hover':     'rgba(184, 48, 42, 0.10)',
      '--bg-inset':     'rgba(222, 207, 184, 0.7)',
      '--bg-glass':     'rgba(245, 237, 224, 0.66)',

      '--accent':        '#b8302a',
      '--accent-2':      '#1a1815',
      '--accent-3':      '#8a5a2a',
      '--accent-4':      '#4a3f33',
      '--accent-hover':  '#c93c34',
      '--accent-subtle': 'rgba(184, 48, 42, 0.12)',
      '--accent-border': 'rgba(184, 48, 42, 0.38)',

      '--text-primary':   '#1a1815',
      '--text-secondary': '#3a342c',
      '--text-tertiary':  '#6a6055',
      '--text-muted':     '#938878',

      '--success': '#3d8a3d',
      '--success-subtle': 'rgba(61, 138, 61, 0.12)',
      '--warning': '#c98a1a',
      '--warning-subtle': 'rgba(201, 138, 26, 0.15)',
      '--danger': '#b8302a',
      '--danger-subtle': 'rgba(184, 48, 42, 0.12)',

      '--border':       'rgba(26, 24, 21, 0.14)',
      '--border-hover': 'rgba(26, 24, 21, 0.26)',
      '--border-light': 'rgba(26, 24, 21, 0.07)',

      '--bubble-user-bg-start': '#b8302a',
      '--bubble-user-bg-end':   '#8a1f1c',
      '--bubble-user-text':     '#fff8ec',
      '--bubble-agent-bg':      'rgba(248, 242, 230, 0.92)',
      '--bubble-agent-border':  'rgba(26, 24, 21, 0.10)',
      '--bubble-agent-text':    '#1a1815',
      '--avatar-user-start':    '#d35445',
      '--avatar-user-end':      '#8a1f1c',
      '--avatar-agent-start':   '#1a1815',
      '--avatar-agent-end':     '#4a3f33',

      '--shadow-sm': '0 1px 2px rgba(26, 24, 21, 0.10)',
      '--shadow-md': '0 6px 20px rgba(26, 24, 21, 0.14)',
      '--shadow-lg': '0 16px 48px rgba(26, 24, 21, 0.18)',
    },
  },

  // ── 纸·碧玉 — 冷翡翠纸 + 深碧 ──
  'light-clean': {
    id: 'light-clean',
    name: '纸·碧玉',
    glyph: '纸',
    description: '冷翡翠纸, 翠绿主调, 文房青绿',
    isDark: false,
    material: 'paper-jade',
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#dee5dd',
      '--bg-secondary': 'rgba(204, 217, 202, 0.72)',
      '--bg-tertiary':  'rgba(184, 200, 182, 0.7)',
      '--bg-card':      'rgba(228, 235, 226, 0.82)',
      '--bg-hover':     'rgba(58, 110, 82, 0.10)',
      '--bg-inset':     'rgba(196, 210, 195, 0.7)',
      '--bg-glass':     'rgba(222, 229, 220, 0.66)',

      '--accent':        '#2f6e52',
      '--accent-2':      '#1a3830',
      '--accent-3':      '#7a8a4a',
      '--accent-4':      '#3a5a78',
      '--accent-hover':  '#3a8765',
      '--accent-subtle': 'rgba(47, 110, 82, 0.14)',
      '--accent-border': 'rgba(47, 110, 82, 0.38)',

      '--text-primary':   '#1a2823',
      '--text-secondary': '#2e3f37',
      '--text-tertiary':  '#4d6359',
      '--text-muted':     '#7a8a82',

      '--success': '#2f6e52',
      '--success-subtle': 'rgba(47, 110, 82, 0.12)',
      '--warning': '#a87a2a',
      '--warning-subtle': 'rgba(168, 122, 42, 0.15)',
      '--danger': '#a83a2a',
      '--danger-subtle': 'rgba(168, 58, 42, 0.12)',

      '--border':       'rgba(26, 40, 35, 0.14)',
      '--border-hover': 'rgba(26, 40, 35, 0.26)',
      '--border-light': 'rgba(26, 40, 35, 0.07)',

      '--bubble-user-bg-start': '#2f6e52',
      '--bubble-user-bg-end':   '#1a4a36',
      '--bubble-user-text':     '#f0f5ee',
      '--bubble-agent-bg':      'rgba(228, 235, 226, 0.92)',
      '--bubble-agent-border':  'rgba(26, 40, 35, 0.10)',
      '--bubble-agent-text':    '#1a2823',
      '--avatar-user-start':    '#4a8a6a',
      '--avatar-user-end':      '#1a4a36',
      '--avatar-agent-start':   '#1a3830',
      '--avatar-agent-end':     '#3a5a48',

      '--shadow-sm': '0 1px 2px rgba(26, 40, 35, 0.10)',
      '--shadow-md': '0 6px 20px rgba(26, 40, 35, 0.14)',
      '--shadow-lg': '0 16px 48px rgba(26, 40, 35, 0.18)',
    },
  },

  // ── 铜·金箔 — 深古铜底 + 金箔 ──
  'sepia-warm': {
    id: 'sepia-warm',
    name: '铜·金箔',
    glyph: '铜',
    description: '深古铜底, 金箔为亮, 金属暖调',
    isDark: true,
    material: 'copper-gold',
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#1d140e',
      '--bg-secondary': 'rgba(38, 26, 18, 0.78)',
      '--bg-tertiary':  'rgba(54, 38, 26, 0.78)',
      '--bg-card':      'rgba(32, 22, 16, 0.74)',
      '--bg-hover':     'rgba(212, 160, 80, 0.12)',
      '--bg-inset':     'rgba(14, 10, 7, 0.74)',
      '--bg-glass':     'rgba(28, 20, 14, 0.66)',

      '--accent':        '#d4a050',
      '--accent-2':      '#a87035',
      '--accent-3':      '#e8c478',
      '--accent-4':      '#7a4818',
      '--accent-hover':  '#e0b06a',
      '--accent-subtle': 'rgba(212, 160, 80, 0.16)',
      '--accent-border': 'rgba(212, 160, 80, 0.40)',

      '--text-primary':   '#f0e3cc',
      '--text-secondary': '#cdbfa4',
      '--text-tertiary':  '#9a8a6e',
      '--text-muted':     '#6e5e48',

      '--success': '#7ab87a',
      '--success-subtle': 'rgba(122, 184, 122, 0.14)',
      '--warning': '#e8c478',
      '--warning-subtle': 'rgba(232, 196, 120, 0.15)',
      '--danger': '#d87862',
      '--danger-subtle': 'rgba(216, 120, 98, 0.14)',

      '--border':       'rgba(212, 184, 140, 0.12)',
      '--border-hover': 'rgba(212, 184, 140, 0.22)',
      '--border-light': 'rgba(212, 184, 140, 0.06)',

      '--bubble-user-bg-start': '#d4a050',
      '--bubble-user-bg-end':   '#a87035',
      '--bubble-user-text':     '#1d140e',
      '--bubble-agent-bg':      'rgba(32, 22, 16, 0.92)',
      '--bubble-agent-border':  'rgba(212, 184, 140, 0.12)',
      '--bubble-agent-text':    '#f0e3cc',
      '--avatar-user-start':    '#e8c478',
      '--avatar-user-end':      '#a87035',
      '--avatar-agent-start':   '#d4a050',
      '--avatar-agent-end':     '#7a4818',

      '--shadow-sm': '0 1px 2px rgba(0, 0, 0, 0.4)',
      '--shadow-md': '0 6px 20px rgba(0, 0, 0, 0.5)',
      '--shadow-lg': '0 16px 48px rgba(0, 0, 0, 0.6)',
    },
  },

  // ── 夜·电青 — 深电青底 + 亮青电光 ──
  'midnight-blue': {
    id: 'midnight-blue',
    name: '夜·电青',
    glyph: '夜',
    description: '深电青底, 亮青电光划过',
    isDark: true,
    material: 'night-cyan',
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#0a1416',
      '--bg-secondary': 'rgba(16, 28, 32, 0.76)',
      '--bg-tertiary':  'rgba(26, 44, 50, 0.76)',
      '--bg-card':      'rgba(14, 26, 30, 0.74)',
      '--bg-hover':     'rgba(59, 212, 200, 0.10)',
      '--bg-inset':     'rgba(7, 18, 20, 0.74)',
      '--bg-glass':     'rgba(12, 24, 28, 0.66)',

      '--accent':        '#3bd4c8',
      '--accent-2':      '#5a8aab',
      '--accent-3':      '#d4b45a',
      '--accent-4':      '#9c6dc7',
      '--accent-hover':  '#56e2d6',
      '--accent-subtle': 'rgba(59, 212, 200, 0.14)',
      '--accent-border': 'rgba(59, 212, 200, 0.36)',

      '--text-primary':   '#e4f5f3',
      '--text-secondary': '#bcd8d6',
      '--text-tertiary':  '#84a8a6',
      '--text-muted':     '#58736f',

      '--success': '#3bd4c8',
      '--success-subtle': 'rgba(59, 212, 200, 0.13)',
      '--warning': '#d4b45a',
      '--warning-subtle': 'rgba(212, 180, 90, 0.15)',
      '--danger': '#f08a7a',
      '--danger-subtle': 'rgba(240, 138, 122, 0.12)',

      '--border':       'rgba(120, 190, 200, 0.12)',
      '--border-hover': 'rgba(120, 190, 200, 0.22)',
      '--border-light': 'rgba(120, 190, 200, 0.06)',

      '--bubble-user-bg-start': '#3bd4c8',
      '--bubble-user-bg-end':   '#1a8a82',
      '--bubble-user-text':     '#04201e',
      '--bubble-agent-bg':      'rgba(18, 34, 38, 0.92)',
      '--bubble-agent-border':  'rgba(120, 190, 200, 0.10)',
      '--bubble-agent-text':    '#dcefe7',
      '--avatar-user-start':    '#56e2d6',
      '--avatar-user-end':      '#1a8a82',
      '--avatar-agent-start':   '#3bd4c8',
      '--avatar-agent-end':     '#1a8a82',

      '--shadow-sm': '0 1px 2px rgba(0,0,0,0.4)',
      '--shadow-md': '0 6px 20px rgba(0,0,0,0.5)',
      '--shadow-lg': '0 16px 48px rgba(0,0,0,0.6)',
    },
  },
};

export const themeList: ThemeTokens[] = Object.values(themes);

export const DEFAULT_THEME: ThemeId = 'dark-stone';
