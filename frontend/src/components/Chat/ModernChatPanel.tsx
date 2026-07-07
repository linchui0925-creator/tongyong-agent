/**
 * ModernChatPanel — Chat UI (W4-29 redesign)
 *
 * 视觉参考 WeChat / iMessage / Telegram: 人物分明, 清晰头像 + 名称
 * - 顶部 chat header: agent 头像 + 名称 + 在线状态
 * - 每条消息: 头像 (40px 圆) + 名称 + 气泡 + 时间
 * - 配色: 用户主色蓝, AI 中性深灰, 整体保持深色 app 协调
 * - 字体: 系统字体栈, 14.5px 正文, 12px 时间, 13px 名称
 *
 * 状态机 (messages / isStreaming / heartbeat / compress / clarify) 抽到
 * useStreamChat hook, 这里只负责渲染 + 输入处理 + 列表滚动。
 */

import { useEffect, useRef, useCallback, useState, useMemo } from 'react';
import { useStreamChat } from '../../hooks/useStreamChat';
import { Message, ContextInfo, ArtifactPreview, Attachment } from '../../types';
import { uploadAttachments } from '../../api/attachments';
import { MarkdownContent } from './MarkdownContent';
import { ThemeSwitcher } from '../Theme/ThemeSwitcher';
import { detectFilePaths, getFileIcon } from './pathDetector';
import './ModernChatPanel.css';

// ── Constants ─────────────────────────────────────────
const USER_NAME = '我';
const AGENT_NAME = 'AI 助手';
const USER_INITIAL = 'U';

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
          <a className="chat-artifact-open" href={openUrl} target="_blank" rel="noopener noreferrer">打开</a>
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
        <a className="chat-artifact-open" href={openUrl} target="_blank" rel="noopener noreferrer">打开</a>
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
  if (attachment.kind === 'image') {
    return (
      <div className="chat-attachment chat-attachment--image">
        <a href={openUrl} target="_blank" rel="noopener noreferrer">
          <img src={src} alt={attachment.name || attachment.filename} />
        </a>
        <div className="chat-attachment-meta">
          <span>{attachment.name || attachment.filename}</span>
          <span>{formatFileSize(attachment.size)}</span>
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

// ── Avatar ─────────────────────────────────────────
function Avatar({ isUser, size = 40 }: { isUser: boolean; size?: number }) {
  if (isUser) {
    return (
      <div className="chat-avatar chat-avatar--user" style={{ width: size, height: size }}>
        <span>{USER_INITIAL}</span>
      </div>
    );
  }
  return (
    <div className="chat-avatar chat-avatar--agent" style={{ width: size, height: size }}>
      <svg viewBox="0 0 24 24" width={size * 0.55} height={size * 0.55} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2a3 3 0 0 0-3 3v1a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
        <line x1="12" y1="19" x2="12" y2="22" />
      </svg>
    </div>
  );
}

// ── Typing Indicator ─────────────────────────────────────────
function TypingIndicator({ currentTool, toolElapsed, progressText }: {
  currentTool: { name: string; emoji: string; startTime: number } | null;
  toolElapsed: number;
  progressText: string;
}) {
  return (
    <div className="chat-typing">
      <Avatar isUser={false} size={36} />
      <div className="chat-typing-content">
        <div className="chat-typing-dots">
          <span /><span /><span />
        </div>
        <span className="chat-typing-label">
          {currentTool
            ? `${currentTool.emoji} ${currentTool.name} 执行中… (${(toolElapsed / 1000).toFixed(1)}s)`
            : progressText || '正在思考…'}
        </span>
      </div>
    </div>
  );
}

// ── Token Usage Bar ─────────────────────────────────────────
function TokenUsageBar({ contextInfo, isCompressing, savedFlash, onCompress }: {
  contextInfo: ContextInfo | null;
  isCompressing: boolean;
  savedFlash: string | null;
  onCompress: () => void;
}) {
  if (!contextInfo) return null;
  const pct = Math.min(100, Math.max(0, contextInfo.percent));
  return (
    <div className="token-usage-bar">
      <div className="token-usage-bar-fill" style={{ width: `${pct}%` }} data-approaching={String(contextInfo.approaching)} />
      <span className="token-usage-bar-text">
        {contextInfo.estimated_tokens} / {contextInfo.threshold_tokens} tok ({pct.toFixed(0)}%)
      </span>
      <button className="token-usage-bar-compress" onClick={onCompress} disabled={isCompressing} title="压缩上下文">
        {isCompressing ? '压缩中…' : '压缩'}
      </button>
      {savedFlash && <span className="token-usage-bar-flash">{savedFlash}</span>}
    </div>
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
  const showName = isFirstInGroup;
  const showAvatar = isLastInGroup; // avatar 只在每组最后一条显示
  return (
    <div className={`chat-row chat-row--${isUser ? 'user' : 'agent'} ${isLastInGroup ? 'is-last' : ''}`}>
      {/* 头像列: 始终占位保持气泡对齐, 非最后一条用空白 placeholder */}
      <div className="chat-row-avatar">
        {showAvatar ? <Avatar isUser={isUser} /> : <div className="chat-avatar-placeholder" />}
      </div>

      <div className="chat-row-body">
        {showName && (
          <div className="chat-row-name">{isUser ? USER_NAME : AGENT_NAME}</div>
        )}
        <div className={`chat-bubble chat-bubble--${isUser ? 'user' : 'agent'} chat-bubble--status-${msg.status}`}>
          {!isUser && msg.thinking && (
            <details className="chat-thinking" open={thinkingExpanded}>
              <summary onClick={(e) => { e.preventDefault(); onToggleThinking(msg.id); }}>
                💭 思考过程
              </summary>
              <pre>{msg.thinking}</pre>
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
          {!isUser && msg.needsContinue && (
            <div className="chat-bubble-progress">
              {msg.stopReason || '长任务达到单次执行上限，可继续执行。'}
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

// ── Chat Header ─────────────────────────────────────────
function ChatHeader({ isStreaming, messageCount }: {
  isStreaming: boolean;
  messageCount: number;
}) {
  return (
    <div className="chat-header">
      <div className="chat-header-avatar">
        <div className="chat-avatar chat-avatar--agent chat-avatar--header">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2a3 3 0 0 0-3 3v1a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="22" />
          </svg>
        </div>
        <span className={`chat-header-status ${isStreaming ? 'is-streaming' : 'is-online'}`} />
      </div>
      <div className="chat-header-info">
        <div className="chat-header-name">{AGENT_NAME}</div>
        <div className="chat-header-subtitle">
          {isStreaming ? (
            <span className="chat-header-typing">正在输入…</span>
          ) : (
            <span className="chat-header-online">● 在线</span>
          )}
        </div>
      </div>
      <div className="chat-header-meta">
        <ThemeSwitcher />
        <span className="chat-header-count">{messageCount} 条消息</span>
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
}

function ModernChatPanel({ initialSessionId }: ModernChatPanelProps) {
  const [currentSessionId, setCurrentSessionId] = useState<string>(initialSessionId || '');
  const [inputValue, setInputValue] = useState('');
  const [showHelp, setShowHelp] = useState(false);
  const [waitingAnswer, setWaitingAnswer] = useState('');
  const [pendingAttachments, setPendingAttachments] = useState<Attachment[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isDraggingFile, setIsDraggingFile] = useState(false);

  // Sync session from parent
  useEffect(() => {
    if (initialSessionId) setCurrentSessionId(initialSessionId);
  }, [initialSessionId]);

  // 状态机: 全部从 hook 拿
  const {
    messages, isStreaming, isLoading, errorMessage, progressText, elapsed,
    currentTool, toolElapsed, tokenUsage, contextInfo, isCompressing, savedFlash,
    expandedThinkingMsgId, waitingQuestion, pendingContinue,
    setErrorMessage, handleSend, handleStop, handleCompress, handleDelete,
    handleToggleThinking, handleClarifyAnswer, handleContinue,
  } = useStreamChat({ sessionId: currentSessionId });

  // Tab title
  useEffect(() => {
    const baseTitle = 'TongYong Agent';
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
      onDragLeave={(e) => { if (e.currentTarget === e.target) setIsDraggingFile(false); }}
      onDrop={handleDrop}
    >
      <ChatHeader
        isStreaming={isStreaming}
        messageCount={messages.length}
      />

      {errorMessage && (
        <div className="chat-error">
          <span>{errorMessage}</span>
          <button onClick={() => setErrorMessage(null)} aria-label="关闭错误">×</button>
        </div>
      )}

      <div className="chat-toolbar">
        <button className="btn btn-ghost" onClick={() => setShowHelp(!showHelp)}>
          {showHelp ? '收起帮助' : '帮助'}
        </button>
      </div>

      {showHelp && (
        <div className="chat-help">
          <div className="chat-help-section">
            <strong>对话</strong>
            <p>在这里与 AI 助手进行交流。会结合上下文、记忆和技能回应你的问题。</p>
          </div>
          <div className="chat-help-section">
            <strong>使用说明</strong>
            <ul>
              <li><strong>发送</strong> — 输入内容按 <kbd>Enter</kbd> 发送</li>
              <li><strong>换行</strong> — 按 <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行</li>
              <li><strong>停止</strong> — Agent 回复时点击输入框旁的停止按钮可中断</li>
              <li><strong>删除</strong> — 鼠标悬停消息可删除单条记录</li>
            </ul>
          </div>
        </div>
      )}

      <div className="chat-messages" ref={messagesRef} onScroll={handleScroll}>
        {messages.length === 0 ? (
          <div className="chat-empty">
            <Avatar isUser={false} size={64} />
            <p className="chat-empty-title">开始新对话</p>
            <span className="chat-empty-hint">Enter 发送 · Shift+Enter 换行</span>
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
            {isStreaming && <TypingIndicator currentTool={currentTool} toolElapsed={toolElapsed} progressText={progressText} />}
          </>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 工具执行仪表板 */}
      {currentTool && (
        <div className="chat-tools-dashboard">
          <div className="tool-item tool-item--running">
            <span className="tool-emoji">{currentTool.emoji}</span>
            <span className="tool-name">{currentTool.name}</span>
            <span className="tool-spinner"><span /><span /><span /></span>
            <span className="tool-duration tool-duration--live">{(toolElapsed / 1000).toFixed(1)}s</span>
          </div>
        </div>
      )}
      {/* 进度提示 */}
      {isStreaming && !currentTool && (
        <div className="chat-statusbar">
          <span className="chat-statusbar-dot" />
          <span className="chat-statusbar-text">{progressText || '思考中...'}</span>
          {tokenUsage && <span className="chat-statusbar-token">⏱ {tokenUsage.total}</span>}
          <span className="chat-statusbar-elapsed">{(elapsed / 1000).toFixed(1)}s</span>
        </div>
      )}
      {isStreaming && currentTool && tokenUsage && (
        <div className="chat-statusbar">
          <span className="chat-statusbar-dot" />
          <span className="chat-statusbar-text">{progressText || '执行中...'}</span>
          <span className="chat-statusbar-token">⏱ {tokenUsage.total}</span>
          <span className="chat-statusbar-elapsed">{(elapsed / 1000).toFixed(1)}s</span>
        </div>
      )}
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

      <TokenUsageBar
        contextInfo={contextInfo}
        isCompressing={isCompressing}
        savedFlash={savedFlash}
        onCompress={() => handleCompress(false)}
      />

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
          <button
            className="chat-attach-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading || isLoading}
            title="上传附件"
            aria-label="上传附件"
          >
            {isUploading ? '…' : '+'}
          </button>
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
            placeholder={`给 ${AGENT_NAME} 发消息…`}
            disabled={isLoading && !isStreaming}
            rows={1}
          />
          <div>
            {isStreaming ? (
              <button className="chat-stop-btn" onClick={handleStop} title="停止" aria-label="停止生成">■</button>
            ) : (
              <button className="chat-send-btn" onClick={handleSendClick} disabled={(!inputValue.trim() && pendingAttachments.length === 0) || isLoading} title="发送" aria-label="发送">→</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default ModernChatPanel;
