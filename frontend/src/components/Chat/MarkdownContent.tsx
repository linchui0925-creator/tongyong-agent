/**
 * MarkdownContent — react-markdown wrapper for chat bubbles (W4-30)
 *
 * 特性:
 * - remark-gfm: tables, strikethrough, task lists, autolink
 * - rehype-sanitize: 防 XSS
 * - 自定义组件: 紧凑 header, list, code (with copy), table, blockquote, link
 */

import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize from 'rehype-sanitize';
import './MarkdownContent.css';

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="md-copy-btn"
      onClick={() => {
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      title="复制代码"
    >
      {copied ? '✓ 已复制' : '复制'}
    </button>
  );
}

interface MarkdownContentProps {
  text: string;
  /** 'user' 气泡用浅色样式 (气泡本身有背景), 'agent' 气泡用主题色 */
  variant?: 'user' | 'agent';
}

export function MarkdownContent({ text, variant = 'agent' }: MarkdownContentProps) {
  if (!text) return null;
  return (
    <div className={`md-content md-content--${variant}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        components={{
          // 标题 — 紧凑, 跟 chat 气泡协调
          h1: ({ children, ...props }) => <h1 className="md-h1" {...props}>{children}</h1>,
          h2: ({ children, ...props }) => <h2 className="md-h2" {...props}>{children}</h2>,
          h3: ({ children, ...props }) => <h3 className="md-h3" {...props}>{children}</h3>,
          h4: ({ children, ...props }) => <h4 className="md-h4" {...props}>{children}</h4>,
          // 段落
          p: ({ children, ...props }) => <p className="md-p" {...props}>{children}</p>,
          // 列表
          ul: ({ children, ...props }) => <ul className="md-ul" {...props}>{children}</ul>,
          ol: ({ children, ...props }) => <ol className="md-ol" {...props}>{children}</ol>,
          li: ({ children, ...props }) => <li className="md-li" {...props}>{children}</li>,
          // 行内
          strong: ({ children, ...props }) => <strong className="md-strong" {...props}>{children}</strong>,
          em: ({ children, ...props }) => <em className="md-em" {...props}>{children}</em>,
          del: ({ children, ...props }) => <del className="md-del" {...props}>{children}</del>,
          // 链接 — 新窗口打开, 防钓鱼
          a: ({ children, href, ...props }) => (
            <a
              className="md-link"
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              {...props}
            >
              {children}
            </a>
          ),
          // 引用
          blockquote: ({ children, ...props }) => (
            <blockquote className="md-blockquote" {...props}>{children}</blockquote>
          ),
          // 水平线
          hr: () => <hr className="md-hr" />,
          // 代码
          code: ({ className, children, ...props }) => {
            const isInline = !(props as any).node?.position;
            const codeText = String(children).replace(/\n$/, '');
            if (isInline) {
              return <code className="md-code-inline" {...props}>{children}</code>;
            }
            return (
              <div className="md-code-block">
                <CopyButton text={codeText} />
                <pre className="md-code-pre"><code className={className} {...props}>{children}</code></pre>
              </div>
            );
          },
          pre: ({ children }) => {
            // 已经被 code 组件处理了 pre, 这里直接 children
            return <>{children}</>;
          },
          // 表格
          table: ({ children, ...props }) => (
            <div className="md-table-wrap">
              <table className="md-table" {...props}>{children}</table>
            </div>
          ),
          thead: ({ children, ...props }) => <thead className="md-thead" {...props}>{children}</thead>,
          tbody: ({ children, ...props }) => <tbody className="md-tbody" {...props}>{children}</tbody>,
          tr: ({ children, ...props }) => <tr className="md-tr" {...props}>{children}</tr>,
          th: ({ children, ...props }) => <th className="md-th" {...props}>{children}</th>,
          td: ({ children, ...props }) => <td className="md-td" {...props}>{children}</td>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
