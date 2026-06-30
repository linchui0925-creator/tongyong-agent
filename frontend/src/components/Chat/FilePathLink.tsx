/**
 * W4-40: 文件路径可点击链接组件
 *
 * 渲染一个 icon + 文件名的 pill, 点击打开 file:// 链接.
 * 类似 Codex / Claude Code 那种 "📄 hello.html" 风格.
 */
import { getFileIcon } from './pathDetector';

interface FilePathLinkProps {
  path: string;
}

const ICONS = {
  code: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16 18 22 12 16 6" />
      <polyline points="8 6 2 12 8 18" />
    </svg>
  ),
  text: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="8" y1="6" x2="21" y2="6" />
      <line x1="8" y1="12" x2="21" y2="12" />
      <line x1="8" y1="18" x2="21" y2="18" />
      <line x1="3" y1="6" x2="3.01" y2="6" />
      <line x1="3" y1="12" x2="3.01" y2="12" />
      <line x1="3" y1="18" x2="3.01" y2="18" />
    </svg>
  ),
  image: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
    </svg>
  ),
  doc: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="9" y1="13" x2="15" y2="13" />
      <line x1="9" y1="17" x2="15" y2="17" />
    </svg>
  ),
  generic: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  ),
};

function buildHref(path: string): string {
  // absolute / relative with leading . or ..
  if (/^(?:https?|file|ftp):\/\//.test(path)) return path;
  if (path.startsWith('/') || path.startsWith('./') || path.startsWith('../')) {
    const cleaned = path.replace(/^\.\//, '');
    return 'file://' + (path.startsWith('/') ? path : '/' + cleaned);
  }
  // bare filename — 没路径, file:// 没法定位, 让浏览器搜不到, 不加 href
  return '';
}

function getBasename(p: string): string {
  return p.split('/').pop() || p;
}

export function FilePathLink({ path }: FilePathLinkProps) {
  const kind = getFileIcon(path);
  const href = buildHref(path);
  const basename = getBasename(path);
  const showFullPath = path !== basename && path.length <= 60;
  const title = href ? `点击打开 ${path}` : `相对路径, 当前目录需要手动定位: ${path}`;

  const handleClick = (e: React.MouseEvent) => {
    if (!href) {
      e.preventDefault();
      // bare filename: 复制到剪贴板, 提示用户
      navigator.clipboard?.writeText(path).catch(() => {});
      return;
    }
    // file:// 链接用新 tab 打开, 浏览器会弹 "allow file://" 提示
    e.preventDefault();
    window.open(href, '_blank', 'noopener,noreferrer');
  };

  return (
    <a
      className={`file-link file-link--${kind}`}
      href={href || '#'}
      onClick={handleClick}
      title={title}
      data-file-path={path}
    >
      <span className="file-link__icon">{ICONS[kind]}</span>
      <span className="file-link__name">{basename}</span>
      {showFullPath && <span className="file-link__dir">{path.slice(0, -(basename.length))}</span>}
    </a>
  );
}
