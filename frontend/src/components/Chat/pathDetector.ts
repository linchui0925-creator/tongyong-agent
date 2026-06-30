/**
 * W4-40: 文件路径检测 + 渲染
 *
 * 扫描文本中的文件路径, 转成可点击的 FilePathLink 组件.
 * 支持: 绝对路径 (/path/to/file) / 家目录 (~/path) / 相对路径 (./foo).
 * 排除: URL (http://... file://...) / markdown 链接 (](path)) / 已经成链接的.
 */

export interface DetectedPath {
  path: string;
  start: number;
  end: number;
}

// 常见文件扩展名 — 用于排除明显不是路径的 (e.g. "the . is 句号")
// W4-40 fix: 按长度降序排, 避免 'js' 在 'json' 之前匹配
// 之前 'package.json' 会被错配成 'package.js'
const FILE_EXTS_RAW = [
  // web
  'html', 'htm', 'css', 'scss', 'sass', 'less',
  'js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs', 'vue', 'svelte',
  'json', 'yaml', 'yml', 'toml', 'xml', 'svg',
  // backend / scripts
  'py', 'rb', 'go', 'rs', 'java', 'kt', 'swift', 'c', 'cpp', 'h', 'hpp',
  'sh', 'bash', 'zsh', 'ps1', 'bat', 'cmd',
  'sql', 'graphql', 'proto',
  // data / docs
  'md', 'mdx', 'txt', 'rst', 'tex',
  'csv', 'tsv', 'xls', 'xlsx',
  // config / build
  'env', 'ini', 'cfg', 'conf', 'lock', 'log',
  'dockerfile', 'makefile',
  // media
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'ico', 'bmp', 'pdf',
];
const FILE_EXTS = [...FILE_EXTS_RAW].sort((a, b) => b.length - a.length);

// 路径正则
// 1. 绝对路径: /dir1/dir2/file.ext
// 2. 家目录: ~/path/to/file
// 3. 相对路径: ./foo 或 ../foo
// 4. bare filename.ext (限制避免误判)
const PATH_RE = new RegExp(
  String.raw`(?:/(?:[\w.\-@]+/)+[\w.\-@]+\.[a-zA-Z0-9]{1,10})` +
  String.raw`|(?:~/[\w.\-@/]+(?:\.[a-zA-Z0-9]{1,10})?)` +
  String.raw`|(?:\.{1,2}/[\w.\-@/]+(?:\.[a-zA-Z0-9]{1,10})?)` +
  String.raw`|(?<![\w/])([A-Za-z][\w.\-@]{0,30}\.(?:` + FILE_EXTS.join('|') + `))(?![\w/])`,
  'g'
);

/**
 * 检测文本中的所有文件路径.
 */
export function detectFilePaths(text: string): DetectedPath[] {
  if (!text) return [];
  const results: DetectedPath[] = [];
  const seen = new Set<string>();

  // 排除 markdown 链接 (](path)) 和 URL 内部
  const skipRanges: Array<[number, number]> = [];
  const mdLinkRe = /\]\(([^)]+)\)/g;
  let m: RegExpExecArray | null;
  while ((m = mdLinkRe.exec(text)) !== null) {
    skipRanges.push([m.index, m.index + m[0].length]);
  }
  const urlRe = /\b(?:https?|file|ftp):\/\/[^\s)<>\]]+/g;
  while ((m = urlRe.exec(text)) !== null) {
    skipRanges.push([m.index, m.index + m[0].length]);
  }

  PATH_RE.lastIndex = 0;
  let pm: RegExpExecArray | null;
  while ((pm = PATH_RE.exec(text)) !== null) {
    const start = pm.index;
    const end = start + pm[0].length;
    if (skipRanges.some(([s, e]) => start >= s && start < e)) continue;
    const matched = pm[0];
    if (seen.has(matched)) continue;
    seen.add(matched);

    // bare filename 模式: 限制 — basename ≥ 2 字符, 不是纯数字
    if (!matched.includes('/') && !matched.startsWith('~') && !matched.startsWith('.')) {
      const basename = matched.split('.')[0];
      if (basename.length < 2 || /^\d+$/.test(basename)) continue;
    }
    results.push({ path: matched, start, end });
  }

  return results.sort((a, b) => a.start - b.start);
}

/**
 * 把文本按检测到的路径切成片段数组.
 */
export function splitTextByPaths(
  text: string
): Array<{ kind: 'text'; text: string } | { kind: 'path'; path: string; start: number; end: number }> {
  const paths = detectFilePaths(text);
  if (paths.length === 0) return [{ kind: 'text', text }];

  const segments: Array<{ kind: 'text'; text: string } | { kind: 'path'; path: string; start: number; end: number }> = [];
  let cursor = 0;
  for (const p of paths) {
    if (p.start > cursor) {
      segments.push({ kind: 'text', text: text.slice(cursor, p.start) });
    }
    segments.push({ kind: 'path', path: p.path, start: p.start, end: p.end });
    cursor = p.end;
  }
  if (cursor < text.length) {
    segments.push({ kind: 'text', text: text.slice(cursor) });
  }
  return segments;
}

/** 把路径转成 file:// URL */
export function pathToFileURL(p: string): string {
  if (/^(?:https?|file|ftp):\/\//.test(p)) return p;
  if (p.startsWith('/') || p.startsWith('./') || p.startsWith('../')) {
    return 'file://' + (p.startsWith('/') ? p : '/' + p.replace(/^\.\//, ''));
  }
  return p;
}

/** 文件扩展名 → icon kind */
export function getFileIcon(p: string): 'code' | 'text' | 'image' | 'doc' | 'generic' {
  const ext = p.split('.').pop()?.toLowerCase() || '';
  if (['html', 'htm', 'css', 'scss', 'js', 'jsx', 'ts', 'tsx', 'vue', 'svelte', 'py', 'rb', 'go', 'rs', 'java', 'kt', 'swift', 'c', 'cpp', 'h', 'hpp', 'sh', 'bash', 'json', 'yaml', 'yml', 'xml', 'toml'].includes(ext)) return 'code';
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico', 'bmp'].includes(ext)) return 'image';
  if (['md', 'mdx', 'txt', 'rst', 'tex', 'pdf'].includes(ext)) return 'doc';
  if (['csv', 'tsv', 'xls', 'xlsx'].includes(ext)) return 'text';
  return 'generic';
}
