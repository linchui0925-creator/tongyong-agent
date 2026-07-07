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
import { remarkFilePaths } from './filePathRemark';
import { detectFilePaths } from './pathDetector';
import { FilePathLink, MarkdownImageLink } from './FilePathLink';
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
      {(() => {
        // W4-40: 跟原始 Components 类型交叉, 加 filePath 自定义节点 (类型未导出所以 any)
        const customComponents: import('react-markdown').Components & { filePath: (p: { value: string }) => JSX.Element } = {
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
          a: ({ children, href }) => <MarkdownImageLink href={href}>{children}</MarkdownImageLink>,
          // 引用
          blockquote: ({ children, ...props }) => (
            <blockquote className="md-blockquote" {...props}>{children}</blockquote>
          ),
          // 水平线
          hr: () => <hr className="md-hr" />,
          // 代码 — W4-40 fix: inline code 命中文件路径时, 渲染 FilePathLink (可点击打开) 而非复制按钮
          // isInline 判断: mdast 里 inlineCode 和 code 节点都有 position, 之前 !node?.position 永远 false
          // 走 node.type === 'inlineCode' 或 props.inline === true
          code: ({ className, children, ...props }) => {
            // W4-40 fix: inline code 命中文件路径时, 渲染 FilePathLink (可点击打开) 而非复制按钮
            // hast 节点对 inline 和 block 都长一样 (tagName='code'), 用单行 vs 多行判断 inline
            // 单行 = inline, 多行 = block (不可能是文件路径)
            const codeText = String(children).replace(/\n$/, '');
            const isInline = !codeText.includes('\n');
            if (isInline) {
              // W4-40 fix: `hello.html` / `./foo.py` / `/abs/path` — 路径被 markdown 包成 inline code, 在这层改成可点击 pill
              // 复用 detectFilePaths 保证跟 remark 插件判定一致 (含 bare filename / 绝对 / 相对 / 排除 markdown link + URL)
              const trimmed = codeText.trim();
              const looksLikePath = trimmed.length > 0 && detectFilePaths(trimmed).some(p => p.path === trimmed);
              if (looksLikePath) {
                return <FilePathLink path={trimmed} />;
              }
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
          // W4-40: 文件路径节点 — remarkFilePaths 注入的自定义类型
          filePath: ({ value }) => <FilePathLink path={value} />,
        };
        return (
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkFilePaths]}
        rehypePlugins={[rehypeSanitize]}
        components={customComponents}
      >
        {text}
      </ReactMarkdown>
        );
      })()}
    </div>
  );
}
