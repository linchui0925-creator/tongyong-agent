/**
 * ModernChatPanel — 维知 (W5-3 重设计)
 *
 * 居中聊天: max-width 980px, 消息气泡 760px
 * 顶部不再有 chat-header (由 App.tsx 顶部标题栏承担)
 * 空状态: 维知 飘逸 wordmark + 一句引导 + 3-4 个快捷入口
 * 流式生成时通过 weizhi:streaming CustomEvent 让顶部标题栏出现 1px 横扫
 */

import { useEffect, useRef, useCallback, useState, useMemo } from 'react';
import { useStreamChat } from '../../hooks/useStreamChat';
import { Message, ContextInfo, ArtifactPreview, Attachment } from '../../types';
import { uploadAttachments } from '../../api/attachments';
import { MarkdownContent } from './MarkdownContent';
import { detectFilePaths, getFileIcon } from './pathDetector';
import ComposerModelControl from './ComposerModelControl';
import './ModernChatPanel.css';

// ── Constants ─────────────────────────────────────────
const AGENT_NAME = '维知';


// ── Helpers ─────────────────────────────────────────
function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', {
    hour: '2-digit', minute: '2-digit',
  });
}

function formatTimeShort(ts: number): string {
  const d = new Date(ts);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) + ' ' +
    d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function splitCodeBlocks(text: string): Array<{ type: 'text' | 'code'; content: string }> {
  const parts: Array<{ type: 'text' | 'code'; content: string }> = [];
  const regex = /```(\w*)\s*\n([\s\S]*?)```/g;
  let lastIdx = 0;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIdx) {
      parts.push({ type: 'text', content: text.slice(lastIdx, match.index).trim() });
    }
    parts.push({ type: 'code', content: match[2].trim() });
    lastIdx = match.index + match[0].length;
  }
  if (lastIdx < text.length) {
    parts.push({ type: 'text', content: text.slice(lastIdx).trim() });
  }
  return parts;
}

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="chat-code-block">
      <button
        className="chat-code-copy-btn"
        onClick={() => {
          navigator.clipboard.writeText(code);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? '✓ 已复制' : '复制'}
      </button>
      <pre><code>{code}</code></pre>
    </div>
  );
}

function ArtifactPreviewCard({ artifact }: { artifact: ArtifactPreview }) {
  const backend = (typeof window !== 'undefined' && (window as any).__BACKEND_URL__) || 'http://127.0.0.1:8000';
  const previewUrl = artifact.preview_url.startsWith('http') ? artifact.preview_url : backend + artifact.preview_url;
  const openUrl = artifact.open_url.startsWith('http') ? artifact.open_url : backend + artifact.open_url;
  if (artifact.kind === 'image') {
    return (
      <div className="chat-artifact chat-artifact--image">
        <div className="chat-artifact-header">
          <span className="chat-artifact-title">{artifact.name}</span>
          <div className="chat-artifact-actions">
            <a className="chat-artifact-open" href={openUrl} target="_blank" rel="noopener noreferrer">打开</a>
            <a className="chat-artifact-open" href={previewUrl} target="_blank" rel="noopener noreferrer">预览</a>
          </div>
        </div>
        <a href={openUrl} target="_blank" rel="noopener noreferrer">
          <img className="chat-artifact-image" src={openUrl} alt={artifact.name} />
        </a>
      </div>
    );
  }
  return (
    <div className="chat-artifact">
      <div className="chat-artifact-header">
        <span className="chat-artifact-title">{artifact.name}</span>
        <div className="chat-artifact-actions">
          <a className="chat-artifact-open" href={previewUrl} target="_blank" rel="noopener noreferrer">预览</a>
          <a className="chat-artifact-open" href={openUrl} target="_blank" rel="noopener noreferrer">打开</a>
        </div>
      </div>
      <iframe
        className="chat-artifact-frame"
        src={previewUrl}
        title={artifact.name}
        sandbox="allow-scripts allow-forms allow-pointer-lock allow-popups allow-modals"
      />
    </div>
  );
}

function toBackendUrl(url: string): string {
  const backend = (typeof window !== 'undefined' && (window as any).__BACKEND_URL__) || 'http://127.0.0.1:8000';
  return url.startsWith('http') ? url : backend + url;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function AttachmentView({ attachment, onRemove }: { attachment: Attachment; onRemove?: () => void }) {
  const src = toBackendUrl(attachment.preview_url || attachment.url);
  const openUrl = toBackendUrl(attachment.open_url || attachment.url);
  const status = attachment.extraction_status || '';
  const summary = attachment.extraction_summary || '';
  const statusLabel = status === 'ocr_extracted'
    ? 'OCR 已识别'
    : status === 'ocr_unavailable'
      ? 'OCR 不可用'
      : status === 'ocr_no_text'
        ? '未识别文字'
        : status === 'metadata_only'
          ? '仅元数据'
          : status === 'error'
            ? '解析失败'
            : '';
  const statusClass = status === 'ocr_extracted'
    ? 'is-ok'
    : status === 'ocr_unavailable' || status === 'ocr_no_text' || status === 'metadata_only'
      ? 'is-warn'
      : status === 'error'
        ? 'is-error'
        : '';
  if (attachment.kind === 'image') {
    return (
      <div className="chat-attachment chat-attachment--image">
        <a href={openUrl} target="_blank" rel="noopener noreferrer">
          <img src={src} alt={attachment.name || attachment.filename} />
        </a>
        <div className="chat-attachment-meta">
          <span>{attachment.name || attachment.filename}</span>
          <span>{formatFileSize(attachment.size)}</span>
          {statusLabel && <span className={`chat-attachment-status ${statusClass}`}>{statusLabel}</span>}
          {summary && <span className="chat-attachment-summary">{summary}</span>}
          {onRemove && <button onClick={onRemove} aria-label="移除附件">×</button>}
        </div>
      </div>
    );
  }
  return (
    <div className="chat-attachment chat-attachment--file">
      <a href={openUrl} target="_blank" rel="noopener noreferrer">
        <span className="chat-attachment-icon">
          {attachment.kind === 'pdf' ? 'PDF' : attachment.kind === 'table' ? 'XLS' : attachment.kind === 'document' ? 'DOC' : 'FILE'}
        </span>
        <span className="chat-attachment-name">{attachment.name || attachment.filename}</span>
        <span className="chat-attachment-size">{formatFileSize(attachment.size)}</span>
      </a>
      {statusLabel && <div className={`chat-attachment-status ${statusClass}`}>{statusLabel}</div>}
      {summary && <div className="chat-attachment-summary">{summary}</div>}
      {onRemove && <button onClick={onRemove} aria-label="移除附件">×</button>}
    </div>
  );
}

function buildLocalFileHref(path: string): string {
  if (/^(?:https?|file|ftp):\/\//.test(path)) return path;
  const backend = (typeof window !== 'undefined' && (window as any).__BACKEND_URL__) || 'http://127.0.0.1:8000';
  return backend + '/api/files/serve?path=' + encodeURIComponent(path);
}

function InlineImagePreviews({ text }: { text: string }) {
  const images = useMemo(() => {
    const seen = new Set<string>();
    return detectFilePaths(text)
      .map((item) => item.path)
      .filter((path) => getFileIcon(path) === 'image')
      .filter((path) => path.includes('/') || path.startsWith('~') || path.startsWith('.'))
      .filter((path) => {
        if (seen.has(path)) return false;
        seen.add(path);
        return true;
      });
  }, [text]);

  if (images.length === 0) return null;
  return (
    <div className="chat-inline-images">
      {images.map((path) => {
        const href = buildLocalFileHref(path);
        return (
          <a key={path} className="chat-inline-image" href={href} target="_blank" rel="noopener noreferrer">
            <img src={href} alt={path.split('/').pop() || path} />
          </a>
        );
      })}
    </div>
  );
}

// ── Typing Indicator (文字 + 加载点, 不要头像那一行) ─────────
function TypingIndicator({ currentTool, toolElapsed, progressText }: {
  currentTool: { name: string; emoji: string; startTime: number } | null;
  toolElapsed: number;
  progressText: string;
}) {
  return (
    <div className="chat-typing">
      <div className="chat-typing-content">
        <div className="chat-typing-dots">
          <span /><span /><span />
        </div>
        <span className="chat-typing-label">
          {currentTool
            ? `${currentTool.emoji || '⚙'} ${currentTool.name} 执行中… (${(toolElapsed / 1000).toFixed(1)}s)`
            : progressText || '正在思考…'}
        </span>
      </div>
    </div>
  );
}

// // ── Token Usage Bar ───────────────────────────────────────────────────
function TokenUsageRing({ contextInfo, isCompressing, savedFlash, onCompress }: {
  contextInfo: ContextInfo | null;
  isCompressing: boolean;
  savedFlash: string | null;
  onCompress: () => void;
}) {
  if (!contextInfo) return null;
  const pct = Math.min(100, Math.max(0, contextInfo.percent));
  const R = 11;
  const C = 2 * Math.PI * R;
  const dash = (pct / 100) * C;
  const title = `上下文 ${contextInfo.estimated_tokens} / ${contextInfo.threshold_tokens} tok (${pct.toFixed(0)}%) · 点击压缩`;
  return (
    <button
      type="button"
      className={`token-ring ${contextInfo.approaching ? 'is-approaching' : ''} ${isCompressing ? 'is-compressing' : ''}`}
      onClick={onCompress}
      disabled={isCompressing}
      title={title}
      aria-label={title}
    >
      <svg width="28" height="28" viewBox="0 0 28 28" className="token-ring-svg">
        <circle className="token-ring-track" cx="14" cy="14" r={R} fill="none" strokeWidth="3" />
        <circle
          className="token-ring-fill"
          cx="14" cy="14" r={R} fill="none" strokeWidth="3"
          strokeDasharray={`${dash} ${C}`}
          strokeLinecap="round"
          transform="rotate(-90 14 14)"
        />
      </svg>
      <span className="token-ring-label">{isCompressing ? '…' : `${pct.toFixed(0)}`}</span>
      {savedFlash && <span className="token-ring-flash">{savedFlash}</span>}
    </button>
  );
}

// ── Message Bubble ─────────────────────────────────────────
function MessageBubble({ msg, isFirstInGroup, isLastInGroup, onDelete, onToggleThinking, thinkingExpanded }: {
  msg: Message;
  isFirstInGroup: boolean;
  isLastInGroup: boolean;
  onDelete: (id: string) => void;
  onToggleThinking: (id: string) => void;
  thinkingExpanded: boolean;
}) {
  const isUser = msg.role === 'user';
  const parts = splitCodeBlocks(msg.content || '');
  void isFirstInGroup;
  return (
    <div className={`chat-row chat-row--${isUser ? 'user' : 'agent'} ${isLastInGroup ? 'is-last' : ''}`}>
      <div className="chat-row-body">
        <div className={`chat-bubble chat-bubble--${isUser ? 'user' : 'agent'} chat-bubble--status-${msg.status}`}>
          {!isUser && msg.thinking && (
            <details className="chat-thinking" open={thinkingExpanded}>
              <summary onClick={(e) => { e.preventDefault(); onToggleThinking(msg.id); }}>
                💭 思考过程
              </summary>
              <pre>{msg.thinking}</pre>
            </details>
          )}
          {!isUser && msg.trace && msg.trace.length > 0 && (
            <details className="chat-trace" open={msg.status === 'streaming'}>
              <summary>
                🔎 任务过程 · {msg.trace.filter((s) => s.kind === 'tool_call').length} 次工具调用
              </summary>
              <ol className="chat-trace-list">
                {msg.trace.map((step, idx) => {
                  if (step.kind === 'text') {
                    return (
                      <li key={idx} className="chat-trace-step chat-trace-step--text">
                        <span className="chat-trace-icon">📝</span>
                        <div className="chat-trace-body">{step.content}</div>
                      </li>
                    );
                  }
                  if (step.kind === 'tool_call') {
                    const argsPreview = step.args && Object.keys(step.args).length > 0
                      ? Object.entries(step.args).map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`).join(', ')
                      : '';
                    return (
                      <li key={idx} className="chat-trace-step chat-trace-step--call">
                        <span className="chat-trace-icon">{step.emoji || '⚙️'}</span>
                        <div className="chat-trace-body">
                          <span className="chat-trace-tool">{step.tool_name}</span>
                          {argsPreview && <span className="chat-trace-args">({argsPreview})</span>}
                        </div>
                      </li>
                    );
                  }
                  if (step.kind === 'tool_result') {
                    const hasFull = !!(step.result_full && step.result_full.trim() && step.result_full.trim() !== (step.preview || '').trim());
                    return (
                      <li key={idx} className="chat-trace-step chat-trace-step--result">
                        <span className="chat-trace-icon">✅</span>
                        <div className="chat-trace-body">
                          <span className="chat-trace-tool">{step.tool_name}</span>
                          {typeof step.duration === 'number' && <span className="chat-trace-duration">{step.duration.toFixed(1)}s</span>}
                          {hasFull ? (
                            <details className="chat-trace-detail">
                              <summary>
                                <span className="chat-trace-preview-inline">{step.preview}</span>
                                <span className="chat-trace-expand-hint">展开完整结果</span>
                              </summary>
                              <pre className="chat-trace-preview chat-trace-preview--full">{step.result_full}</pre>
                            </details>
                          ) : (
                            step.preview && <pre className="chat-trace-preview">{step.preview}</pre>
                          )}
                        </div>
                      </li>
                    );
                  }
                  return (
                    <li key={idx} className="chat-trace-step chat-trace-step--error">
                      <span className="chat-trace-icon">⚠️</span>
                      <div className="chat-trace-body">
                        <span className="chat-trace-tool">{step.tool_name}</span>
                        <span className="chat-trace-args">{step.content}</span>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </details>
          )}
          {parts.map((p, i) => p.type === 'code'
            ? <CodeBlock key={i} code={p.content} />
            : <MarkdownContent key={i} text={p.content} variant={isUser ? 'user' : 'agent'} />
          )}
          <InlineImagePreviews text={msg.content || ''} />
          {msg.attachments && msg.attachments.length > 0 && (
            <div className="chat-attachments">
              {msg.attachments.map((attachment) => (
                <AttachmentView key={attachment.id} attachment={attachment} />
              ))}
            </div>
          )}
          {!isUser && msg.artifactPreviews?.map((artifact) => (
            <ArtifactPreviewCard key={artifact.path} artifact={artifact} />
          ))}
          {msg.progressLabel && msg.status === 'streaming' && (
            <div className="chat-bubble-progress">{msg.progressLabel}</div>
          )}
          {msg.status === 'error' && (
            <div className="chat-bubble-error">❌ {msg.error}</div>
          )}
          {msg.status === 'streaming' && !msg.content && !msg.progressLabel && (
            <span className="chat-bubble-cursor" />
          )}
          {!isUser && (msg.needsContinue || msg.endedBy) && (
            <div className="chat-bubble-progress">
              {msg.stopReason
                ? msg.stopReason
                : msg.endedBy === 'budget'
                  ? '本次输出达到预算上限，可继续。'
                  : msg.endedBy === 'ask'
                    ? '当前流程等待用户回答后继续。'
                    : msg.endedBy === 'evidence_missing'
                      ? '任务缺少交付证据，已提前停止。'
                      : msg.endedBy === 'tool_required_retry_exhausted'
                        ? '连续多轮未成功调用工具，已停止。'
                        : '长任务达到单次执行上限，可继续执行。'}
            </div>
          )}
        </div>
        {isLastInGroup && (
          <div className="chat-row-meta">
            <span className="chat-row-time">{formatTime(msg.timestamp)}</span>
            <button className="chat-row-delete" onClick={() => onDelete(msg.id)} title="删除消息" aria-label="删除消息">×</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main ─────────────────────────────────────────
function shouldShowTime(msgs: Message[], idx: number): boolean {
  if (idx === 0) return true;
  const prev = msgs[idx - 1];
  const cur = msgs[idx];
  return cur.timestamp - prev.timestamp > 5 * 60 * 1000;
}

interface ModernChatPanelProps {
  initialSessionId?: string;
  onSessionCreated?: (sessionId: string) => void;
}

function ModernChatPanel({ initialSessionId, onSessionCreated }: ModernChatPanelProps) {
  const [currentSessionId, setCurrentSessionId] = useState<string>(initialSessionId || '');
  const [inputValue, setInputValue] = useState('');
  const [waitingAnswer, setWaitingAnswer] = useState('');
  const [pendingAttachments, setPendingAttachments] = useState<Attachment[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isDraggingFile, setIsDraggingFile] = useState(false);

  // Sync session from parent
  useEffect(() => {
    setCurrentSessionId(initialSessionId || '');
  }, [initialSessionId]);

  // 状态机: 全部从 hook 拿
  const {
    messages, isStreaming, isLoading, errorMessage, progressText,
    currentTool, toolElapsed, contextInfo, isCompressing, savedFlash,
    expandedThinkingMsgId, waitingQuestion, pendingContinue,
    setErrorMessage, handleSend, handleStop, handleCompress, handleDelete,
    handleToggleThinking, handleClarifyAnswer, handleContinue,
  } = useStreamChat({
    sessionId: currentSessionId,
    onSessionCreated: (sessionId) => {
      setCurrentSessionId(sessionId);
      onSessionCreated?.(sessionId);
    },
  });

  // Tab title
  useEffect(() => {
    const baseTitle = '维知 · Weizhi';
    if (isStreaming) {
      const stage = progressText || '思考中…';
      document.title = `⏳ ${stage} - ${baseTitle}`;
    } else if (errorMessage) {
      document.title = `❌ 错误 - ${baseTitle}`;
    } else {
      document.title = baseTitle;
    }
    return () => { document.title = baseTitle; };
  }, [isStreaming, progressText, errorMessage]);

  // 流式状态广播给 App.tsx 顶部标题栏 (用于 1px 横扫进度)
  useEffect(() => {
    window.dispatchEvent(new CustomEvent('weizhi:streaming', { detail: { streaming: isStreaming } }));
    return () => {
      window.dispatchEvent(new CustomEvent('weizhi:streaming', { detail: { streaming: false } }));
    };
  }, [isStreaming]);

  // 全局监听: 拖动取消/点击空白 都清掉 isDraggingFile
  useEffect(() => {
    if (!isDraggingFile) return;
    const clearDragging = () => setIsDraggingFile(false);
    // dragend: 用户在任何地方松开 (ESC 或 拖到面板外释放)
    window.addEventListener('dragend', clearDragging);
    // 兜底: 用户在拖动状态下点击空白区域 (没真的 drop) 也清掉
    window.addEventListener('mousedown', clearDragging);
    return () => {
      window.removeEventListener('dragend', clearDragging);
      window.removeEventListener('mousedown', clearDragging);
    };
  }, [isDraggingFile]);

  // Auto-scroll refs
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleScroll = useCallback(() => {
    const el = messagesRef.current;
    if (el) {
      const threshold = 120;
      isNearBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
    }
  }, []);

  useEffect(() => {
    if (isNearBottomRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isStreaming]);

  const addFiles = useCallback(async (files: File[]) => {
    if (!files.length || isUploading) return;
    setIsUploading(true);
    setErrorMessage(null);
    try {
      const uploaded = await uploadAttachments(files, currentSessionId || undefined);
      setPendingAttachments((prev) => [...prev, ...uploaded]);
    } catch (err: any) {
      setErrorMessage(err?.message || String(err));
    } finally {
      setIsUploading(false);
    }
  }, [currentSessionId, isUploading, setErrorMessage]);

  const clearComposer = useCallback(() => {
    setInputValue('');
    setPendingAttachments([]);
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  }, []);

  const sendComposer = useCallback(() => {
    if ((inputValue.trim() || pendingAttachments.length > 0) && !isLoading && !isStreaming) {
      handleSend(inputValue, pendingAttachments);
      clearComposer();
    }
  }, [inputValue, pendingAttachments, isLoading, isStreaming, handleSend, clearComposer]);

  // Input handling
  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputValue(e.target.value);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px';
    }
  }, []);

  const handleKey = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendComposer();
    }
  }, [sendComposer]);

  const handleSendClick = useCallback(() => {
    sendComposer();
  }, [sendComposer]);

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    void addFiles(files);
  }, [addFiles]);

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDraggingFile(false);
    void addFiles(Array.from(e.dataTransfer.files || []));
  }, [addFiles]);

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const files = Array.from(e.clipboardData.files || []);
    if (files.length > 0) void addFiles(files);
  }, [addFiles]);

  // 工具 step history (group consecutive same-role msgs)
  const visibleMessages = useMemo(() => {
    return messages.map((m, i) => {
      const prev = i > 0 ? messages[i - 1] : null;
      const next = i < messages.length - 1 ? messages[i + 1] : null;
      return {
        msg: m,
        isFirstInGroup: !prev || prev.role !== m.role,
        isLastInGroup: !next || next.role !== m.role,
      };
    });
  }, [messages]);

  return (
    <div
      className={`chat-panel ${isDraggingFile ? 'is-dragging-file' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setIsDraggingFile(true); }}
      onDragLeave={() => { setIsDraggingFile(false); }}
      onDrop={handleDrop}
    >
      {errorMessage && (
        <div className="chat-error">
          <span>{errorMessage}</span>
          <button onClick={() => setErrorMessage(null)} aria-label="关闭错误">×</button>
        </div>
      )}

      <div className="chat-messages" ref={messagesRef} onScroll={handleScroll}>
        {messages.length === 0 ? (
          <div className="chat-empty">
            <h2 className="chat-empty-wordmark">
              <span className="chat-empty-mark">维</span>
              <span className="chat-empty-name">知</span>
            </h2>
            <p className="chat-empty-title">今天想完成什么？</p>
            <span className="chat-empty-hint">Enter 发送 · Shift+Enter 换行 · 拖拽文件以附加</span>
            <div className="chat-empty-shortcuts">
              <span className="chat-empty-shortcut">新建对话</span>
              <span className="chat-empty-shortcut">团队协作</span>
              <span className="chat-empty-shortcut">浏览 MCP</span>
              <span className="chat-empty-shortcut">设置</span>
            </div>
          </div>
        ) : (
          <>
            {visibleMessages.map(({ msg, isFirstInGroup, isLastInGroup }, i) => {
              return (
                <div key={msg.id}>
                  {shouldShowTime(messages, i) && (
                    <div className="chat-time-sep">
                      <span>{formatTimeShort(msg.timestamp)}</span>
                    </div>
                  )}
                  <MessageBubble
                    msg={msg}
                    isFirstInGroup={isFirstInGroup}
                    isLastInGroup={isLastInGroup}
                    onDelete={handleDelete}
                    onToggleThinking={handleToggleThinking}
                    thinkingExpanded={expandedThinkingMsgId === msg.id}
                  />
                </div>
              );
            })}
          </>
        )}
        {isStreaming && <TypingIndicator currentTool={currentTool} toolElapsed={toolElapsed} progressText={progressText} />}
        <div ref={messagesEndRef} />
      </div>

      {!isStreaming && pendingContinue && (
        <div className="chat-statusbar chat-statusbar--continue">
          <span className="chat-statusbar-dot" />
          <span className="chat-statusbar-text">{pendingContinue.reason}</span>
          <button className="btn btn-ghost" onClick={handleContinue} disabled={isLoading}>
            继续执行
          </button>
        </div>
      )}

      {/* Clarify 交互 */}
      {waitingQuestion && (
        <div className="chat-clarify">
          <div className="chat-clarify-question">{waitingQuestion.question}</div>
          <div className="chat-clarify-choices">
            {waitingQuestion.choices.map((choice, i) => (
              <button
                key={i}
                className="chat-clarify-choice"
                onClick={() => {
                  handleClarifyAnswer(choice);
                }}
              >
                {choice}
              </button>
            ))}
          </div>
          {waitingQuestion.choices.length === 0 && (
            <div className="chat-clarify-input">
              <input
                type="text"
                name="clarify-answer"
                value={waitingAnswer}
                onChange={(e) => setWaitingAnswer(e.target.value)}
                onKeyDown={async (e) => {
                  e.stopPropagation();
                  if (e.key === 'Enter' && waitingAnswer.trim()) {
                    const answer = waitingAnswer.trim();
                    setWaitingAnswer('');
                    await handleClarifyAnswer(answer);
                  }
                }}
                placeholder="输入你的回答后按 Enter..."
                autoFocus
              />
            </div>
          )}
        </div>
      )}

      <div className="chat-input">
        {isDraggingFile && <div className="chat-drop-overlay">松开以上传附件</div>}
        {pendingAttachments.length > 0 && (
          <div className="chat-pending-attachments">
            {pendingAttachments.map((attachment) => (
              <AttachmentView
                key={attachment.id}
                attachment={attachment}
                onRemove={() => setPendingAttachments((prev) => prev.filter((item) => item.id !== attachment.id))}
              />
            ))}
          </div>
        )}
        <div className="chat-input-box">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="chat-file-input"
            onChange={handleFileInput}
            accept="image/*,.pdf,.txt,.md,.markdown,.json,.csv,.tsv,.xlsx,.xls,.docx,.pptx"
          />
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={handleInput}
            onKeyDown={handleKey}
            onPaste={handlePaste}
            placeholder={`与 ${AGENT_NAME} 聊聊…`}
            disabled={isLoading && !isStreaming}
            rows={1}
          />
          <div className="chat-input-toolbar">
            <div className="chat-input-toolbar-left">
              <button
                className="chat-attach-btn"
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading || isLoading}
                title="上传附件"
                aria-label="上传附件"
              >
                {isUploading ? '…' : '+'}
              </button>
              <ComposerModelControl />
              <TokenUsageRing
                contextInfo={contextInfo}
                isCompressing={isCompressing}
                savedFlash={savedFlash}
                onCompress={() => handleCompress(false)}
              />
            </div>
            <div className="chat-input-toolbar-right">
              {isStreaming ? (
                <button className="chat-stop-btn" onClick={handleStop} title="停止" aria-label="停止生成">■</button>
              ) : (
                <button className="chat-send-btn" onClick={handleSendClick} disabled={(!inputValue.trim() && pendingAttachments.length === 0) || isLoading} title="发送" aria-label="发送">↑</button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ModernChatPanel;
