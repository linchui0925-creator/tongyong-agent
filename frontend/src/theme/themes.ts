/**
 * Theme definitions — 维知 四材 (W5-3 材质感主题)
 *
 * 4 套主题对应四种"材质":
 *   ink-paper   (key: dark-stone)      墨·朱砂, 纸白底 + 赭红 + 蓝/黄/紫三态
 *   paper-cinnabar (key: light-clean)  纸·朱砂, 暖白宣纸 + 朱砂红 + 墨/靛/琥珀
 *   oxide       (key: sepia-warm)     铜·锈, 暖铜氧化棕 + 铜橙
 *   night-cyan  (key: midnight-blue)  夜·电青, 深墨色 + 亮青电光
 *
 * key 名保留旧值以兼容 localStorage / 类型, 显示名/配色全部换成材质系。
 * 每套材质新增多 accent 字段 (--accent / --accent-2 / --accent-3 / --accent-4)
 * 供拓扑线场 (AmbientScene) 取色分层。
 *
 * 字体: 飘逸 + 大气 — display 用楷体/宋体轻量栈, body 用无衬线系统栈。
 */

export type ThemeId = 'dark-stone' | 'light-clean' | 'sepia-warm' | 'midnight-blue';
export type Material = 'ink-paper' | 'paper-cinnabar' | 'oxide' | 'night-cyan';

export interface ThemeTokens {
  id: ThemeId;
  /** 显示名 (中文, 用于 ThemeSwitcher) */
  name: string;
  /** 中文单字标记, 用于侧栏紧凑按钮 (墨/纸/铜/夜) */
  glyph: string;
  description: string;
  isDark: boolean;
  material: Material;
  tokens: Record<string, string>;
}

// 飘逸 + 大气 display stack
// 优先级: 系统里若有方正/华文楷体/STKaiti, 直接用; 否则 fallback 到
// PingFang/思源宋体/Hiragino Mincho; 没有则用系统中文字符 generic 兜底。
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

// body 用冷静无衬线系统栈, 不引 Google Fonts (sandbox 不能外网)
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
  // ── 墨·朱砂 (浅纸底, 赭红主调) ──
  'dark-stone': {
    id: 'dark-stone',
    name: '墨·朱砂',
    glyph: '墨',
    description: '纸白底, 朱砂红点睛, 端庄大气',
    isDark: false,
    material: 'ink-paper',
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#f4ede0',
      '--bg-secondary': 'rgba(232, 220, 200, 0.72)',
      '--bg-tertiary':  'rgba(216, 200, 174, 0.7)',
      '--bg-card':      'rgba(248, 242, 230, 0.82)',
      '--bg-hover':     'rgba(192, 57, 43, 0.10)',
      '--bg-inset':     'rgba(222, 207, 184, 0.7)',
      '--bg-glass':     'rgba(245, 237, 224, 0.66)',

      '--accent':        '#b8302a',
      '--accent-2':      '#2a4d8f',
      '--accent-3':      '#c69a3a',
      '--accent-4':      '#6b3d8e',
      '--accent-hover':  '#c93c34',
      '--accent-subtle': 'rgba(184, 48, 42, 0.12)',
      '--accent-border': 'rgba(184, 48, 42, 0.38)',

      '--text-primary':   '#1f1c18',
      '--text-secondary': '#3a342c',
      '--text-tertiary':  '#6a6055',
      '--text-muted':     '#938878',

      '--success': '#3d8a3d',
      '--success-subtle': 'rgba(61, 138, 61, 0.12)',
      '--warning': '#c98a1a',
      '--warning-subtle': 'rgba(201, 138, 26, 0.15)',
      '--danger': '#b8302a',
      '--danger-subtle': 'rgba(184, 48, 42, 0.12)',

      '--border':       'rgba(31, 28, 24, 0.14)',
      '--border-hover': 'rgba(31, 28, 24, 0.26)',
      '--border-light': 'rgba(31, 28, 24, 0.07)',

      '--bubble-user-bg-start': '#b8302a',
      '--bubble-user-bg-end':   '#8a1f1c',
      '--bubble-user-text':     '#fff8ec',
      '--bubble-agent-bg':      'rgba(248, 242, 230, 0.92)',
      '--bubble-agent-border':  'rgba(31, 28, 24, 0.10)',
      '--bubble-agent-text':    '#1f1c18',
      '--avatar-user-start':    '#d35445',
      '--avatar-user-end':      '#8a1f1c',
      '--avatar-agent-start':   '#1f1c18',
      '--avatar-agent-end':     '#4a3f33',

      '--shadow-sm': '0 1px 2px rgba(31, 28, 24, 0.10)',
      '--shadow-md': '0 6px 20px rgba(31, 28, 24, 0.14)',
      '--shadow-lg': '0 16px 48px rgba(31, 28, 24, 0.18)',
    },
  },

  // ── 纸·朱砂 (深色墨底, 朱砂亮) ──
  'light-clean': {
    id: 'light-clean',
    name: '纸·朱砂',
    glyph: '纸',
    description: '墨底朱砂, 纸面浮出一点绛红',
    isDark: true,
    material: 'paper-cinnabar',
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#0e0d0c',
      '--bg-secondary': 'rgba(26, 23, 22, 0.78)',
      '--bg-tertiary':  'rgba(40, 35, 32, 0.78)',
      '--bg-card':      'rgba(22, 20, 18, 0.74)',
      '--bg-hover':     'rgba(216, 75, 64, 0.12)',
      '--bg-inset':     'rgba(8, 7, 7, 0.74)',
      '--bg-glass':     'rgba(18, 16, 15, 0.66)',

      '--accent':        '#d84b40',
      '--accent-2':      '#4d7fc4',
      '--accent-3':      '#e0b056',
      '--accent-4':      '#9c6dc7',
      '--accent-hover':  '#e86757',
      '--accent-subtle': 'rgba(216, 75, 64, 0.16)',
      '--accent-border': 'rgba(216, 75, 64, 0.4)',

      '--text-primary':   '#f5ecdc',
      '--text-secondary': '#d3c5ad',
      '--text-tertiary':  '#9a8c75',
      '--text-muted':     '#6d614f',

      '--success': '#5fb55f',
      '--success-subtle': 'rgba(95, 181, 95, 0.14)',
      '--warning': '#e5b135',
      '--warning-subtle': 'rgba(229, 177, 53, 0.15)',
      '--danger': '#d84b40',
      '--danger-subtle': 'rgba(216, 75, 64, 0.14)',

      '--border':       'rgba(216, 197, 173, 0.10)',
      '--border-hover': 'rgba(216, 197, 173, 0.20)',
      '--border-light': 'rgba(216, 197, 173, 0.05)',

      '--bubble-user-bg-start': '#d84b40',
      '--bubble-user-bg-end':   '#a03228',
      '--bubble-user-text':     '#fff5e8',
      '--bubble-agent-bg':      'rgba(22, 20, 18, 0.92)',
      '--bubble-agent-border':  'rgba(216, 197, 173, 0.10)',
      '--bubble-agent-text':    '#f5ecdc',
      '--avatar-user-start':    '#e86757',
      '--avatar-user-end':      '#a03228',
      '--avatar-agent-start':   '#f5ecdc',
      '--avatar-agent-end':     '#5c4f3d',

      '--shadow-sm': '0 1px 2px rgba(0,0,0,0.4)',
      '--shadow-md': '0 6px 20px rgba(0,0,0,0.5)',
      '--shadow-lg': '0 16px 48px rgba(0,0,0,0.6)',
    },
  },

  // ── 铜·锈 (氧化铜棕, 哑光暖) ──
  'sepia-warm': {
    id: 'sepia-warm',
    name: '铜·锈',
    glyph: '铜',
    description: '氧化铜棕, 哑光铜橙',
    isDark: false,
    material: 'oxide',
    tokens: {
      ...baseTokens,
      '--bg-primary':   '#ece2cf',
      '--bg-secondary': 'rgba(222, 209, 188, 0.74)',
      '--bg-tertiary':  'rgba(204, 188, 160, 0.72)',
      '--bg-card':      'rgba(238, 229, 213, 0.82)',
      '--bg-hover':     'rgba(168, 91, 42, 0.12)',
      '--bg-inset':     'rgba(216, 199, 174, 0.7)',
      '--bg-glass':     'rgba(236, 226, 207, 0.66)',

      '--accent':        '#a85b2a',
      '--accent-2':      '#7c4222',
      '--accent-3':      '#c98a1a',
      '--accent-4':      '#4f3520',
      '--accent-hover':  '#b96935',
      '--accent-subtle': 'rgba(168, 91, 42, 0.14)',
      '--accent-border': 'rgba(168, 91, 42, 0.36)',

      '--text-primary':   '#2c1f12',
      '--text-secondary': '#473522',
      '--text-tertiary':  '#6f5536',
      '--text-muted':     '#917a55',

      '--success': '#7c4222',
      '--success-subtle': 'rgba(124, 66, 34, 0.12)',
      '--warning': '#c98a1a',
      '--warning-subtle': 'rgba(201, 138, 26, 0.15)',
      '--danger': '#a83a2a',
      '--danger-subtle': 'rgba(168, 58, 42, 0.12)',

      '--border':       'rgba(44, 31, 18, 0.14)',
      '--border-hover': 'rgba(44, 31, 18, 0.26)',
      '--border-light': 'rgba(44, 31, 18, 0.07)',

      '--bubble-user-bg-start': '#a85b2a',
      '--bubble-user-bg-end':   '#7c4222',
      '--bubble-user-text':     '#fbeed7',
      '--bubble-agent-bg':      'rgba(238, 229, 213, 0.92)',
      '--bubble-agent-border':  'rgba(44, 31, 18, 0.10)',
      '--bubble-agent-text':    '#2c1f12',
      '--avatar-user-start':    '#c98a4a',
      '--avatar-user-end':      '#7c4222',
      '--avatar-agent-start':   '#2c1f12',
      '--avatar-agent-end':     '#4f3520',

      '--shadow-sm': '0 1px 2px rgba(44, 31, 18, 0.10)',
      '--shadow-md': '0 6px 20px rgba(44, 31, 18, 0.14)',
      '--shadow-lg': '0 16px 48px rgba(44, 31, 18, 0.18)',
    },
  },

  // ── 夜·电青 (深墨蓝绿, 冷峻) ──
  'midnight-blue': {
    id: 'midnight-blue',
    name: '夜·电青',
    glyph: '夜',
    description: '深墨夜色, 一道电青划过',
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
