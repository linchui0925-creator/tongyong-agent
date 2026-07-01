/**
 * W4-40 + W4-45: 文件路径可点击链接组件
 *
 * 渲染一个 icon + 文件名的 pill, 类似 Codex / Claude Code 风格.
 * 点击 → 浏览器原生 <a target="_blank"> 跳转到 backend HTTP 端点
 *         /api/files/serve?path=...  → 真实在浏览器新 tab 打开 HTML
 * hover 时显示 "复制路径" 小按钮 (备用, 用户可能想用 Finder)
 */
import { useState, useRef, useEffect } from 'react';
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
  // W4-45: 用 backend HTTP 端点 serve 本地文件, 替代 file:// (Chrome block)
  // http(s)/ftp/file:// 走原样; 本地路径 → /api/files/serve
  if (/^(?:https?|file|ftp):\/\//.test(path)) return path;
  const backend = (typeof window !== 'undefined' && (window as any).__BACKEND_URL__) || 'http://127.0.0.1:8000';
  return backend + '/api/files/serve?path=' + encodeURIComponent(path);
}

function getBasename(p: string): string {
  return p.split('/').pop() || p;
}

function getDir(p: string, basename: string): string {
  return p.slice(0, -(basename.length));
}

export function FilePathLink({ path }: FilePathLinkProps) {
  const kind = getFileIcon(path);
  const href = buildHref(path);
  const basename = getBasename(path);
  const showFullPath = path !== basename && path.length <= 60;
  const dir = getDir(path, basename);

  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);

  const flashCopied = () => {
    setCopied(true);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(false), 1800);
  };

  const copyPath = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    try {
      await navigator.clipboard.writeText(path);
    } catch {
      // 剪贴板 API 失败 → 退化
      const ta = document.createElement('textarea');
      ta.value = path;
      ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); } catch {}
      document.body.removeChild(ta);
    }
    flashCopied();
  };

  return (
    <span className="file-link-wrap" data-file-path={path}>
      <a
        className={`file-link file-link--${kind} ${copied ? 'file-link--copied' : ''}`}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        title={`点击打开: ${path}`}
      >
        <span className="file-link__icon">{ICONS[kind]}</span>
        <span className="file-link__name">{basename}</span>
        {showFullPath && dir && <span className="file-link__dir">{dir}</span>}
        {copied && <span className="file-link__check">✓</span>}
      </a>
      <button
        className="file-link-action"
        type="button"
        onClick={copyPath}
        title={`复制路径: ${path}`}
        aria-label="复制路径"
      >
        <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      </button>
      {copied && (
        <span className="file-link-toast" role="status">
          已复制 <code>{basename}</code>
        </span>
      )}
    </span>
  );
}
