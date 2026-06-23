/**
 * ModernChatPanel — Chat UI (refactored P3-1, 1104 → 700 lines)
 *
 * 状态机 (messages / isStreaming / heartbeat / compress / clarify) 抽到
 * useStreamChat hook, 这里只负责渲染 + 输入处理 + 列表滚动。
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { useStreamChat } from '../../hooks/useStreamChat';
import { Message, ContextInfo } from '../../types';
import './ModernChatPanel.css';

// ── Helpers ─────────────────────────────────────────
function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
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
    <div className="code-block">
      <button
        className="code-copy-btn"
        onClick={() => {
          navigator.clipboard.writeText(code);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? '已复制' : '复制'}
      </button>
      <pre><code>{code}</code></pre>
    </div>
  );
}

function TypingIndicator({ currentTool, toolElapsed, progressText }: {
  currentTool: { name: string; emoji: string; startTime: number } | null;
  toolElapsed: number;
  progressText: string;
}) {
  return (
    <div className="chat-typing">
      <div className="chat-typing-dot" />
      <div className="chat-typing-dot" />
      <div className="chat-typing-dot" />
      <span className="chat-typing-label">
        {currentTool
          ? `${currentTool.emoji} ${currentTool.name} 执行中… (${(toolElapsed / 1000).toFixed(1)}s)`
          : progressText || '思考中…'}
      </span>
    </div>
  );
}

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
      <div className="token-usage-bar-fill" style={{ width: `${pct}%` }} data-approaching={contextInfo.approaching} />
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

function MessageBubble({ msg, isUser, isFirstInGroup, isLastInGroup, onDelete, onToggleThinking, thinkingExpanded }: {
  msg: Message;
  isUser: boolean;
  isFirstInGroup: boolean;
  isLastInGroup: boolean;
  onDelete: (id: string) => void;
  onToggleThinking: (id: string) => void;
  thinkingExpanded: boolean;
}) {
  const parts = splitCodeBlocks(msg.content || '');
  return (
    <div className={`chat-bubble chat-bubble--${msg.role} ${isFirstInGroup ? 'is-first' : ''} ${isLastInGroup ? 'is-last' : ''}`}>
      {isUser ? (
        <div className="chat-bubble-user">
          {msg.content}
        </div>
      ) : (
        <div className="chat-bubble-assistant">
          {msg.thinking && (
            <details className="chat-thinking" open={thinkingExpanded}>
              <summary onClick={(e) => { e.preventDefault(); onToggleThinking(msg.id); }}>
                💭 思考过程
              </summary>
              <pre>{msg.thinking}</pre>
            </details>
          )}
          {parts.map((p, i) => p.type === 'code'
            ? <CodeBlock key={i} code={p.content} />
            : <div key={i} className="chat-bubble-text">{p.content}</div>
          )}
          {msg.progressLabel && msg.status === 'streaming' && (
            <div className="chat-bubble-progress">{msg.progressLabel}</div>
          )}
          {msg.status === 'error' && (
            <div className="chat-bubble-error">❌ {msg.error}</div>
          )}
        </div>
      )}
      {isLastInGroup && (
        <div className="chat-bubble-meta">
          <span className="chat-bubble-time">{formatTime(msg.timestamp)}</span>
          <button className="chat-bubble-delete" onClick={() => onDelete(msg.id)} title="删除">×</button>
        </div>
      )}
    </div>
  );
}

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

  // Sync session from parent
  useEffect(() => {
    if (initialSessionId) setCurrentSessionId(initialSessionId);
  }, [initialSessionId]);

  // 状态机: 全部从 hook 拿
  const {
    messages, isStreaming, isLoading, errorMessage, progressText, elapsed,
    currentTool, toolElapsed, tokenUsage, contextInfo, isCompressing, savedFlash,
    expandedThinkingMsgId, waitingQuestion,
    setErrorMessage, handleSend, handleStop, handleCompress, handleDelete,
    handleToggleThinking, handleClarifyAnswer,
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
      if (inputValue.trim() && !isLoading && !isStreaming) {
        handleSend(inputValue);
        setInputValue('');
        if (textareaRef.current) textareaRef.current.style.height = 'auto';
      }
    }
  }, [inputValue, isLoading, isStreaming, handleSend]);

  const handleSendClick = useCallback(() => {
    if (inputValue.trim() && !isLoading && !isStreaming) {
      handleSend(inputValue);
      setInputValue('');
      if (textareaRef.current) textareaRef.current.style.height = 'auto';
    }
  }, [inputValue, isLoading, isStreaming, handleSend]);

  return (
    <div className="chat-panel">
      {errorMessage && (
        <div className="chat-error">
          <span>{errorMessage}</span>
          <button onClick={() => setErrorMessage(null)}>×</button>
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
            <strong>📋 什么是对话？</strong>
            <p>在这里与 AI Agent 进行交流。Agent 会结合上下文、记忆和技能来回应你的问题。</p>
          </div>
          <div className="chat-help-section">
            <strong>📖 使用说明</strong>
            <ul>
              <li><strong>发送消息</strong> — 在输入框中输入内容，按 <kbd>Enter</kbd> 发送</li>
              <li><strong>换行</strong> — 按 <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行</li>
              <li><strong>停止生成</strong> — Agent 回复时点击输入框旁的停止按钮可中断</li>
              <li><strong>删除消息</strong> — 鼠标悬停消息可删除单条记录</li>
              <li>Agent 会自动利用记忆、人格设定和技能来提供更精准的回答</li>
            </ul>
          </div>
        </div>
      )}

      <div className="chat-messages" ref={messagesRef} onScroll={handleScroll}>
        {messages.length === 0 ? (
          <div className="chat-empty">
            <div className="chat-empty-marker">✦</div>
            <p>开始新对话</p>
            <span className="chat-empty-hint">Enter 发送 · Shift+Enter 换行</span>
          </div>
        ) : (
          <>
            {messages.map((msg, i) => {
              const isUser = msg.role === 'user';
              const prev = i > 0 ? messages[i - 1] : null;
              const next = i < messages.length - 1 ? messages[i + 1] : null;
              const isFirstInGroup = !prev || prev.role !== msg.role;
              const isLastInGroup = !next || next.role !== msg.role;
              return (
                <div key={msg.id}>
                  {shouldShowTime(messages, i) && (
                    <div className="chat-time-sep">
                      <span>{formatTimeShort(msg.timestamp)}</span>
                    </div>
                  )}
                  <MessageBubble
                    msg={msg}
                    isUser={isUser}
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
        <div className="chat-input-box">
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={handleInput}
            onKeyDown={handleKey}
            placeholder="输入消息..."
            disabled={isLoading && !isStreaming}
            rows={1}
          />
          <div>
            {isStreaming ? (
              <button className="chat-stop-btn" onClick={handleStop} title="停止">■</button>
            ) : (
              <button className="chat-send-btn" onClick={handleSendClick} disabled={!inputValue.trim() || isLoading} title="发送">→</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default ModernChatPanel;
