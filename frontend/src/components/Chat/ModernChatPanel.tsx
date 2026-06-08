import { useState, useEffect, useRef, useCallback } from 'react';
import { streamChat, generateMessageId, compressSessionContext, getContextStats } from '../../api/stream';
import { getSessionMessages } from '../../api/memory';
import { submitClarifyAnswer } from '../../api/chat';
import { createEvaluation } from '../../api/evaluation';
import { Message, ContextInfo } from '../../types';
import './ModernChatPanel.css';

// ── Helpers ─────────────────────────────────────────
function getEmoji(role: string): string {
  const r = role.toLowerCase();
  if (r.includes('user') || r === 'user') return '👤';
  return '🤖';
}

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
  const handleCopy = () => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  return (
    <div style={{
      background: '#2B2B2B', borderRadius: 6, overflow: 'hidden', margin: '6px 0',
      border: '1px solid #3E3E3E',
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '4px 10px', background: '#353535',
      }}>
        <span style={{ fontSize: 10, color: '#888' }}>python</span>
        <button onClick={handleCopy} style={{
          background: 'none', border: 'none', color: '#888',
          cursor: 'pointer', fontSize: 10, padding: '2px 6px', borderRadius: 3,
        }}>
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre style={{
        margin: 0, padding: '10px 12px', overflow: 'auto',
        fontSize: 12, lineHeight: 1.5, color: '#D4D4D4', maxHeight: 300,
      }}>{code}</pre>
    </div>
  );
}

// ── Typing Indicator ─────────────────────────────────────────
function TypingIndicator({ currentTool, toolElapsed, progressText, heartbeat }: {
  currentTool?: { name: string; emoji?: string; startTime: number } | null;
  toolElapsed?: number;
  progressText?: string;
  heartbeat?: string | null;
}) {
  // 优先级: heartbeat (5s+ 无事件兜底) > currentTool (工具调用中) > progressText (后端 progress) > 默认三个点
  let label: string | null = null;
  let icon = '💭';
  if (heartbeat) {
    label = heartbeat;
    icon = heartbeat.startsWith('⏳') ? '⏳' : '💭';
  } else if (currentTool) {
    const emoji = currentTool.emoji || '🔧';
    const sec = (toolElapsed ?? 0).toFixed(1);
    label = `${currentTool.name} · ${sec}s`;
    icon = emoji;
  } else if (progressText) {
    label = progressText;
    icon = '💭';
  }
  return (
    <div className="chat-bubble-row">
      <div className="chat-bubble-avatar">🤖</div>
      <div className="chat-bubble chat-bubble--typing">
        <div className="chat-bubble-body" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '2px 0' }}>
          <span style={{ display: 'inline-flex', gap: 4 }} aria-hidden>
            {[0, 1, 2].map(i => (
              <span key={i} style={{
                width: 8, height: 8, borderRadius: '50%', background: 'var(--brand-primary, #4F7A4A)', display: 'inline-block',
                animation: `thinkingBounce 1.2s infinite ${i * 0.2}s`,
              }} />
            ))}
          </span>
          {icon && <span style={{ fontSize: 15 }}>{icon}</span>}
          {label && (
            <span style={{ fontSize: 15, fontWeight: 500, color: 'var(--text-primary, #222)' }}>
              {label}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Token Usage Bar ─────────────────────────────────────────
// 显示在 .chat-input 上方，实时反映 context 容量 + 主动压缩按钮。
// 数据源：后端 SSE "context" 事件 + 主动调 /api/chat/compress。
// 颜色随百分比变化：<50% 绿（安全）/ 50-80% 黄（注意）/ >80% 红（接近阈值）。
function TokenUsageBar({
  contextInfo,
  isCompressing,
  savedFlash,
  onCompress,
}: {
  contextInfo: ContextInfo | null;
  isCompressing: boolean;
  savedFlash: string | null;
  onCompress: () => void;
}) {
  if (!contextInfo) {
    return (
      <div className="token-usage-bar token-usage-bar--idle">
        <span className="token-usage-label">tokens</span>
        <span className="token-usage-value">— / —</span>
        <span className="token-usage-percent">0%</span>
      </div>
    );
  }
  const { estimated_tokens, threshold_tokens, percent, approaching } = contextInfo;
  const level = percent >= 80 ? 'danger' : percent >= 50 ? 'warn' : 'ok';
  return (
    <div className={`token-usage-bar token-usage-bar--${level}`}>
      <span className="token-usage-label">tokens</span>
      <span className="token-usage-value">
        {estimated_tokens.toLocaleString()} / {threshold_tokens.toLocaleString()}
      </span>
      <div className="token-usage-track">
        <div
          className="token-usage-fill"
          style={{ width: `${Math.min(percent, 100)}%` }}
        />
        {/* 50% 阈值标记 — 被动压缩临界值 */}
        <div className="token-usage-marker token-usage-marker--threshold" title="被动压缩临界值（50%）" />
      </div>
      <span className="token-usage-percent">{percent.toFixed(1)}%</span>
      {approaching && <span className="token-usage-warning" title="接近压缩阈值">⚠</span>}
      {savedFlash && <span className="token-usage-flash">{savedFlash}</span>}
      <button
        className="token-usage-compress-btn"
        onClick={onCompress}
        disabled={isCompressing}
        title="主动压缩上下文（LLM summarization）"
      >
        {isCompressing ? '⏳ 压缩中' : '🗜 压缩'}
      </button>
    </div>
  );
}

// ── Message Bubble ─────────────────────────────────────────
function MessageBubble({
  msg, isUser, isFirstInGroup, isLastInGroup, onDelete, onToggleThinking, thinkingExpanded,
}: {
  msg: Message;
  isUser: boolean;
  isFirstInGroup: boolean;
  isLastInGroup: boolean;
  onDelete: (id: string) => void;
  onToggleThinking: (id: string) => void;
  thinkingExpanded: boolean;
}) {
  const isError = msg.status === 'error';
  const isStreaming = msg.status === 'streaming';
  const blocks = splitCodeBlocks(msg.content);

  return (
    <div className={`chat-bubble-row ${isUser ? 'chat-bubble-row--user' : ''}`}>
      {isFirstInGroup ? (
        <div className="chat-bubble-avatar">{getEmoji(msg.role)}</div>
      ) : (
        <div style={{ width: 36, flexShrink: 0 }} />
      )}

      <div className="chat-bubble-content">
        <div className={`chat-bubble ${isError ? 'chat-bubble--error' : ''} ${msg.executionClaimMismatch ? 'chat-bubble--mismatch' : ''}`}>
          <div className="chat-bubble-body">
            {/* 阶段 1 思考动效已迁移到 TypingIndicator 组件（消息列表底部），避免重复 */}
            {blocks.length === 1 && blocks[0].type === 'text' ? (
              <>
                {msg.content}
                {isStreaming && msg.content && <span className="chat-cursor" />}
              </>
            ) : (
              blocks.map((b, i) =>
                b.type === 'code' ? (
                  <CodeBlock key={i} code={b.content} />
                ) : (
                  <span key={i}>{b.content}{isStreaming && msg.content && i === blocks.length - 1 ? <span className="chat-cursor" /> : null}</span>
                )
              )
            )}
            {isError && <span style={{ marginLeft: 4, fontWeight: 600 }}>❌</span>}
          </div>

          {msg.thinking && (
            <div className="chat-thinking-toggle">
              <button
                className="chat-thinking-btn"
                onClick={() => onToggleThinking(msg.id)}
              >
                💭 {thinkingExpanded ? '收起' : '查看'}思考过程
              </button>
              {thinkingExpanded && (
                <div className="chat-thinking-content">{msg.thinking}</div>
              )}
            </div>
          )}
          {msg.executionClaimMismatch && (
            <div className="chat-thinking-content" style={{ color: 'var(--danger)', fontSize: 12 }}>
              该回复声称已经执行操作，但前端没有检测到本轮真实工具调用或命令执行。
            </div>
          )}
        </div>

        {isLastInGroup && (
          <div className="chat-bubble-meta">
            <span className="chat-bubble-time">{formatTime(msg.timestamp)}</span>
            <button className="chat-bubble-delete" onClick={() => onDelete(msg.id)} title="删除">×</button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Should show time separator ─────────────────────────────────
function shouldShowTime(msgs: Message[], idx: number): boolean {
  if (idx === 0) return true;
  const prev = msgs[idx - 1];
  const curr = msgs[idx];
  if (prev.role !== curr.role) return true;
  const diff = curr.timestamp - prev.timestamp;
  return diff > 5 * 60 * 1000; // 5 minutes gap
}

interface ModernChatPanelProps {
  initialSessionId?: string;
}

function ModernChatPanel({ initialSessionId }: ModernChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [currentSessionId, setCurrentSessionId] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const [progressText, setProgressText] = useState<string>('');
  const [elapsed, setElapsed] = useState<number>(0);
  const [currentTool, setCurrentTool] = useState<{name: string; emoji: string; startTime: number} | null>(null);
  const currentToolRef = useRef<{name: string; emoji: string; startTime: number} | null>(null);
  useEffect(() => { currentToolRef.current = currentTool; }, [currentTool]);
  const [toolElapsed, setToolElapsed] = useState<number>(0);
  const [expandedThinkingMsgId, setExpandedThinkingMsgId] = useState<string | null>(null);
  const [waitingQuestion, setWaitingQuestion] = useState<{question: string; choices: string[]; id: string} | null>(null);
  const [waitingAnswer, setWaitingAnswer] = useState('');
  // 步骤历史：展示 agent 工作 pipeline（保留 setter 调用，值不再显示）
  const [, setStepHistory] = useState<Array<{id: string; text: string; status: 'done' | 'current'; emoji?: string}>>([]);
  const [, setExecutionSummary] = useState<string[]>([]);
  // Token 使用量
  const [tokenUsage, setTokenUsage] = useState<{input: number; output: number; total: number} | null>(null);
  // 上下文容量信息（驱动 TokenUsageBar）— SSE 实时更新 + 启动时 / 切 session 时从
  // /api/chat/context-stats 拉一次初始值
  const [contextInfo, setContextInfo] = useState<ContextInfo | null>(null);
  // 主动压缩进行中状态（按钮 disabled）
  const [isCompressing, setIsCompressing] = useState(false);
  // 压缩完成后短时显示的"节省了 X%"提示（3s 后自动清空）
  const [savedFlash, setSavedFlash] = useState<string | null>(null);
  const savedFlashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const looksLikeExecutionClaim = useCallback((content: string) => {
    const text = (content || '').toLowerCase();
    const patterns = ['已调用', '已执行', '已打开', '已访问', '已搜索', '已截图', '已导航', '我已经调用', '我已调用'];
    return patterns.some((p) => text.includes(p));
  }, []);

  // Sync session
  useEffect(() => {
    if (initialSessionId) setCurrentSessionId(initialSessionId);
  }, [initialSessionId]);

  // Load history
  const loadMessages = useCallback(async (sid: string) => {
    if (!sid) return;
    try {
      const data = await getSessionMessages(sid);
      const msgs: Message[] = (data.messages || []).map((m: any, i: number) => {
        // 清理 content 中的 thinking 标签和特殊 token（离线保存时可能未清理）
        const rawContent = m.content || '';
        // 清理 <|im_start|>...<|im_end|> 标签（MiniMax 模型输出）
        const cleanedForThink = rawContent.replace(/<\|im_start\|[^|]*\|[^>]*>[\s\S]*?<\|im_end\|>/g, '');
        const thinkMatch = cleanedForThink.match(/<think>([\s\S]*?)晖/);
        const thinking = thinkMatch ? thinkMatch[1] : '';
        const displayContent = cleanedForThink.replace(/<think>[\s\S]*?晖/g, '').trim();
        return {
          id: m.id || `msg-${i}`,
          role: m.role,
          content: displayContent,
          thinking: thinking || undefined,
          timestamp: new Date(m.created_at || Date.now()).getTime(),
          status: 'completed' as const,
        };
      });
      setMessages(msgs);
    } catch {
      setMessages([]);
    }
  }, []);

  useEffect(() => {
    if (currentSessionId) loadMessages(currentSessionId);
  }, [currentSessionId, loadMessages]);

  // 切 session / 启动时拉一次 context 容量（给 TokenUsageBar 初始值）
  useEffect(() => {
    if (!currentSessionId) {
      setContextInfo(null);
      return;
    }
    let cancelled = false;
    getContextStats(currentSessionId).then((stats) => {
      if (cancelled) return;
      if (stats && !stats.error && stats.threshold_tokens !== undefined) {
        setContextInfo({
          chars: stats.chars ?? 0,
          estimated_tokens: stats.estimated_tokens ?? 0,
          threshold_tokens: stats.threshold_tokens,
          percent: stats.percent ?? 0,
          approaching: stats.approaching ?? false,
        });
      }
    }).catch((err) => {
      console.warn('[TokenUsageBar] getContextStats 失败:', err);
    });
    return () => { cancelled = true; };
  }, [currentSessionId]);

  // 清理 savedFlash timer 防止 unmount 后 setState
  useEffect(() => {
    return () => {
      if (savedFlashTimerRef.current) clearTimeout(savedFlashTimerRef.current);
    };
  }, []);

  // Auto-scroll — only when user is near the bottom
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

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    };
  }, []);

  // Heartbeat — 当 SSE 长时间没事件时，主动在状态栏显示"还在思考…(Xs)"
  // 解决 LLM 推理停顿（content 发完后等 5-30s 才发 tool_call）时用户以为已完成的痛点
  const lastEventTimeRef = useRef<number>(Date.now());
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const thinkingStartedRef = useRef<boolean>(false);  // 思考阶段是否已推过 progressText (避免频繁 setState)
  const startHeartbeat = (msgId: string) => {
    if (heartbeatRef.current) clearInterval(heartbeatRef.current);
    lastEventTimeRef.current = Date.now();
    heartbeatRef.current = setInterval(() => {
      const gap = Math.floor((Date.now() - lastEventTimeRef.current) / 1000);
      if (gap >= 5) {
        const tool = currentToolRef.current;
        const label = tool
          ? `⏳ ${tool.name} 执行中… (${gap}s)`
          : `💭 还在思考… (${gap}s)`;
        setProgressText(prev => {
          if (prev && !prev.startsWith('💭') && !prev.startsWith('⏳')) return prev;
          return label;
        });
        setMessages(prev => prev.map(m =>
          m.id === msgId && m.status === 'streaming'
            ? { ...m, progressLabel: label }
            : m
        ));
      }
    }, 5000);
  };
  const stopHeartbeat = () => {
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  };
  const markActive = () => { lastEventTimeRef.current = Date.now(); };

  // Tab title 实时反映 agent 状态（用户在 tab 切换走也能看到在不在工作）
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

  const handleSend = useCallback(async () => {
    const text = inputValue.trim();
    if (!text || isLoading || isStreaming) return;

    abortRef.current?.abort();
    abortRef.current = null;

    const uid = generateMessageId();
    const aid = generateMessageId();

    setMessages(prev => [...prev,
      { id: uid, role: 'user', content: text, timestamp: Date.now(), status: 'completed' },
      { id: aid, role: 'assistant', content: '', timestamp: Date.now(), status: 'streaming' },
    ]);
    setInputValue('');
    setIsLoading(true);
    setErrorMessage(null);
    setElapsed(0);
    setToolElapsed(0);
    setCurrentTool(null);
    setStepHistory([]);
    setExecutionSummary([]);
    setTokenUsage(null);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setElapsed(prev => prev + 100);
      setToolElapsed(prev => prev + 100);
    }, 100);
    if (textareaRef.current) textareaRef.current.style.height = 'auto';

    abortRef.current = streamChat(text, currentSessionId || undefined, true, {
      onStart: () => {
        setIsStreaming(true);
        setProgressText('连接中...');
        setExpandedThinkingMsgId(null);
        thinkingStartedRef.current = false;
        startHeartbeat(aid);
        markActive();
      },
      onProgress: (content) => {
        setProgressText(content);
        markActive();
        // 同步把进度写进 assistant 消息体，让用户看到 "🤔 加载历史对话..." 等状态
        setMessages(prev => prev.map(m =>
          m.id === aid && m.status === 'streaming'
            ? { ...m, progressLabel: content }
            : m
        ));
        // 记录步骤：完成上一个步骤，标记当前步骤
        if (content && content !== progressText) {
          setStepHistory(prev => {
            const updated = prev.map(s => s.status === 'current' ? { ...s, status: 'done' as const } : s);
            const exists = updated.some(s => s.text === content);
            if (!exists) {
              updated.push({ id: `step-${generateMessageId()}`, text: content, status: 'current' as const });
            }
            return updated;
          });
        }
      },
      onToolStart: (toolName, _args, emoji) => {
        setToolElapsed(0);
        setCurrentTool({ name: toolName, emoji, startTime: Date.now() });
        markActive();
        // 工具启动：完成当前步骤，记录工具步骤
        setStepHistory(prev => {
          const updated = prev.map(s => s.status === 'current' ? { ...s, status: 'done' as const } : s);
          updated.push({ id: `tool-${generateMessageId()}`, text: `⚡ 调用 ${toolName}`, status: 'done' as const, emoji });
          return updated;
        });
      },
      onToolComplete: (toolName, preview, duration, emoji) => {
        setCurrentTool(null);
        markActive();
        if (preview) {
          setExecutionSummary(prev => [...prev.slice(-5), `${emoji} ${toolName} (${duration.toFixed(1)}s): ${preview}`]);
        }
      },
      onToolError: (toolName, error, emoji) => {
        setCurrentTool(null);
        markActive();
        setExecutionSummary(prev => [...prev.slice(-5), `${emoji} ${toolName} 出错: ${error}`]);
      },
      onToolFeedback: (content) => {
        markActive();
        if (content) {
          setExecutionSummary(prev => [...prev.slice(-5), content]);
        }
      },
      onBudgetWarning: (content) => {
        markActive();
        if (content) {
          setExecutionSummary(prev => [...prev.slice(-5), content]);
        }
      },
      onThinkingDelta: (content) => {
        setMessages(prev => prev.map(m =>
          m.id === aid ? { ...m, thinking: (m.thinking || '') + content } : m
        ));
        // 思考阶段首次 delta 才推 progressText（避免频繁 setState）
        if (!thinkingStartedRef.current) {
          thinkingStartedRef.current = true;
          setProgressText('💭 思考中…');
        }
        markActive();
      },
      onThinkingDone: () => { markActive(); },
      onAsk: (question, choices, question_id) => {
        setWaitingQuestion({ question, choices, id: question_id });
        setWaitingAnswer('');
        setIsStreaming(false);
        setProgressText('等待回答...');
        markActive();
      },
      onUsage: (input, output, total) => {
        setTokenUsage({ input, output, total });
      },
      onContext: (info) => {
        // 实时 context 容量快照（每轮 LLM 调用前/压缩后推）— 直接 setState 触发重渲染
        setContextInfo(info);
      },
      onContent: (_chunk, full) => {
        setProgressText('');
        markActive();
        // 提取 thinking 内容并过滤
        const thinkMatch = full.match(/<think>([\s\S]*?)晖/);
        const thinking = thinkMatch ? thinkMatch[1] : '';
        const displayContent = full.replace(/<think>[\s\S]*?晖/g, '').trim();
        setMessages(prev => prev.map(m =>
          m.id === aid ? { ...m, content: displayContent, thinking: thinking || m.thinking, status: 'streaming' as const } : m
        ));
      },
      onDone: (data) => {
        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
        stopHeartbeat();
        setProgressText('');
        setCurrentTool(null);
        setStepHistory([]);  // 完成时清空步骤历史
        setMessages(prev => prev.map(m =>
          m.id === aid ? {
            ...m,
            status: 'completed' as const,
            toolsUsed: data.tools_used || [],
            commandsExecuted: data.commands_executed || [],
            executionClaimMismatch: looksLikeExecutionClaim(m.content) && !((data.tools_used && data.tools_used.length > 0) || (data.commands_executed && data.commands_executed.length > 0)),
          } : m
        ));
        setIsStreaming(false);
        setIsLoading(false);
        abortRef.current = null;

        // 自动创建评估记录
        if (data.session_id && data.tools_used && data.tools_used.length > 0) {
          createEvaluation({
            session_id: data.session_id,
            tools_used: data.tools_used || [],
            commands_executed: data.commands_executed || [],
            processing_time: data.processing_time || 0,
            usage: data.usage || {},
          }).catch(err => {
            console.error('[评估] 创建评估失败:', err);
          });
        }
      },
      onError: (err) => {
        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
        stopHeartbeat();
        setProgressText('');
        setErrorMessage(err);
        setStepHistory([]);
        setCurrentTool(null);
        setMessages(prev => prev.map(m =>
          m.id === aid ? { ...m, status: 'error' as const, error: err } : m
        ));
        setIsStreaming(false);
        setIsLoading(false);
        abortRef.current = null;
      },
    });
  }, [inputValue, isLoading, isStreaming, currentSessionId]);

  const handleStop = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    stopHeartbeat();
    abortRef.current?.abort();
    setIsStreaming(false);
    setIsLoading(false);
    setProgressText('');
    setCurrentTool(null);
    setStepHistory([]);
    setMessages(prev => prev.map(m =>
      m.status === 'streaming' ? { ...m, status: 'completed' as const } : m
    ));
  }, []);

  // 主动压缩（TokenUsageBar 按钮触发）。
  // 调 POST /api/chat/compress：
  //   - 默认尊重 should_compress 阈值，未达则返回 skipped
  //   - force=true 跳过阈值检查
  // 压缩完成后用返回的 after_tokens 立即刷新 TokenUsageBar，
  // 并显示 3s 绿色 "✓ 节省了 X%" flash 让用户得到反馈。
  const handleCompress = useCallback(async (force: boolean = false) => {
    if (!currentSessionId || isCompressing) return;
    setIsCompressing(true);
    try {
      const result = await compressSessionContext(currentSessionId, force);
      if (result.success) {
        // 重新拉一次精确容量（compress API 走的是 storage 写回，百分比会立刻变）
        const stats = await getContextStats(currentSessionId);
        if (stats && !stats.error && stats.threshold_tokens !== undefined) {
          setContextInfo({
            chars: stats.chars ?? 0,
            estimated_tokens: stats.estimated_tokens ?? 0,
            threshold_tokens: stats.threshold_tokens,
            percent: stats.percent ?? 0,
            approaching: stats.approaching ?? false,
          });
        }
        if (result.skipped) {
          setSavedFlash('未达阈值');
        } else {
          const saved = result.saved_pct ?? 0;
          setSavedFlash(`✓ 节省 ${saved.toFixed(0)}% (${result.before_tokens}→${result.after_tokens} tok)`);
        }
        if (savedFlashTimerRef.current) clearTimeout(savedFlashTimerRef.current);
        savedFlashTimerRef.current = setTimeout(() => setSavedFlash(null), 3000);
      } else {
        setSavedFlash(`✗ 压缩失败: ${result.error || '未知错误'}`);
        if (savedFlashTimerRef.current) clearTimeout(savedFlashTimerRef.current);
        savedFlashTimerRef.current = setTimeout(() => setSavedFlash(null), 3000);
      }
    } catch (err: any) {
      console.error('[handleCompress] 失败:', err);
      setSavedFlash(`✗ 错误: ${err?.message || String(err)}`);
      if (savedFlashTimerRef.current) clearTimeout(savedFlashTimerRef.current);
      savedFlashTimerRef.current = setTimeout(() => setSavedFlash(null), 3000);
    } finally {
      setIsCompressing(false);
    }
  }, [currentSessionId, isCompressing]);

  const handleDelete = useCallback((id: string) => {
    setMessages(prev => prev.filter(m => m.id !== id));
  }, []);

  const handleToggleThinking = useCallback((id: string) => {
    setExpandedThinkingMsgId(prev => prev === id ? null : id);
  }, []);

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputValue(e.target.value);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + 'px';
    }
  }, []);

  const handleKey = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  }, [handleSend]);

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

      {/* 工具执行仪表板 — 仅显示当前正在运行的工具 */}
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
      {/* 进度提示（无工具调用时） */}
      {isStreaming && !currentTool && (
        <div className="chat-statusbar">
          <span className="chat-statusbar-dot" />
          <span className="chat-statusbar-text">{progressText || '思考中...'}</span>
          {tokenUsage && (
            <span className="chat-statusbar-token">⏱ {tokenUsage.total}</span>
          )}
          <span className="chat-statusbar-elapsed">{(elapsed / 1000).toFixed(1)}s</span>
        </div>
      )}
      {/* 工具执行中 */}
      {isStreaming && currentTool && tokenUsage && (
        <div className="chat-statusbar">
          <span className="chat-statusbar-dot" />
          <span className="chat-statusbar-text">{progressText || '执行中...'}</span>
          <span className="chat-statusbar-token">⏱ {tokenUsage.total}</span>
          <span className="chat-statusbar-elapsed">{(elapsed / 1000).toFixed(1)}s</span>
        </div>
      )}

      {/* Clarify 交互 UI */}
      {waitingQuestion && (
        <div className="chat-clarify">
          <div className="chat-clarify-question">{waitingQuestion.question}</div>
          <div className="chat-clarify-choices">
            {waitingQuestion.choices.map((choice, i) => (
              <button
                key={i}
                className="chat-clarify-choice"
                onClick={async () => {
                  await submitClarifyAnswer(waitingQuestion.id, choice, currentSessionId || undefined);
                  setWaitingQuestion(null);
                  setWaitingAnswer('');
                  setIsLoading(true);
                  setIsStreaming(true);
                  setProgressText('继续中...');
                  setExecutionSummary([]);
                  setStepHistory([]);
                  // 重新发起流式请求，续上对话
                  const uid = generateMessageId();
                  const aid = generateMessageId();
                  setMessages(prev => [...prev,
                    { id: uid, role: 'user', content: choice, timestamp: Date.now(), status: 'completed' as const },
                    { id: aid, role: 'assistant', content: '', timestamp: Date.now(), status: 'streaming' as const },
                  ]);
                  abortRef.current = streamChat(choice, currentSessionId || undefined, true, {
                    onStart: () => {
                      setIsStreaming(true);
                      setProgressText('继续中...');
                      thinkingStartedRef.current = false;
                      startHeartbeat(aid);
                      markActive();
                    },
                    onProgress: (content) => {
                      setProgressText(content);
                      markActive();
                      setMessages(prev => prev.map(m =>
                        m.id === aid && m.status === 'streaming'
                          ? { ...m, progressLabel: content }
                          : m
                      ));
                    },
                    onToolStart: (toolName, _args, emoji) => {
                      setToolElapsed(0);
                      setCurrentTool({ name: toolName, emoji, startTime: Date.now() });
                      markActive();
                    },
                    onToolComplete: (toolName, preview, duration, emoji) => {
                      setCurrentTool(null);
                      markActive();
                      if (preview) {
                        setExecutionSummary(prev => [...prev.slice(-5), `${emoji} ${toolName} (${duration.toFixed(1)}s): ${preview}`]);
                      }
                    },
                    onToolError: (toolName, error, emoji) => {
                      setCurrentTool(null);
                      setExecutionSummary(prev => [...prev.slice(-5), `${emoji} ${toolName} 出错: ${error}`]);
                    },
                    onToolFeedback: (content) => {
                      if (content) {
                        setExecutionSummary(prev => [...prev.slice(-5), content]);
                      }
                    },
                    onBudgetWarning: (content) => {
                      if (content) {
                        setExecutionSummary(prev => [...prev.slice(-5), content]);
                      }
                    },
                    onThinkingDelta: (content) => {
                      setMessages(prev => prev.map(m =>
                        m.id === aid ? { ...m, thinking: (m.thinking || '') + content } : m
                      ));
                      if (!thinkingStartedRef.current) {
                        thinkingStartedRef.current = true;
                        setProgressText('💭 思考中…');
                      }
                      markActive();
                    },
                    onThinkingDone: () => {},
                    onAsk: (question, choices, question_id) => {
                      setWaitingQuestion({ question, choices, id: question_id });
                      setWaitingAnswer('');
                    },
                    onContext: (info) => {
                      setContextInfo(info);
                    },
                    onDone: () => {
                      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
                      stopHeartbeat();
                      setProgressText('');
                      setStepHistory([]);
                      setMessages(prev => prev.map(m =>
                        m.id === aid ? { ...m, status: 'completed' as const } : m
                      ));
                      setIsStreaming(false);
                      setIsLoading(false);
                      setCurrentTool(null);
                      abortRef.current = null;
                    },
                    onError: (err) => {
                      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
                      stopHeartbeat();
                      setProgressText('');
                      setStepHistory([]);
                      setErrorMessage(err);
                      setMessages(prev => prev.map(m =>
                        m.id === aid ? { ...m, status: 'error' as const, error: err } : m
                      ));
                      setIsStreaming(false);
                      setIsLoading(false);
                      setCurrentTool(null);
                      abortRef.current = null;
                    },
                  }, waitingQuestion.id, choice);
                }}
              />
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
                    await submitClarifyAnswer(waitingQuestion.id, answer, currentSessionId || undefined);
                    setWaitingQuestion(null);
                    setWaitingAnswer('');
                    // 续流逻辑同上
                    setIsLoading(true);
                    setIsStreaming(true);
                    setExecutionSummary([]);
                    setStepHistory([]);
                    const uid = generateMessageId();
                    const aid = generateMessageId();
                    setMessages(prev => [...prev,
                      { id: uid, role: 'user', content: answer, timestamp: Date.now(), status: 'completed' as const },
                      { id: aid, role: 'assistant', content: '', timestamp: Date.now(), status: 'streaming' as const },
                    ]);
                    abortRef.current = streamChat(answer, currentSessionId || undefined, true, {
                      onStart: () => { setIsStreaming(true); setProgressText('继续中...'); thinkingStartedRef.current = false; startHeartbeat(aid); markActive(); },
                      onProgress: (content) => {
                        setProgressText(content);
                        markActive();
                        setMessages(prev => prev.map(m =>
                          m.id === aid && m.status === 'streaming'
                            ? { ...m, progressLabel: content }
                            : m
                        ));
                      },
                      onToolStart: (toolName, _args, emoji) => { setToolElapsed(0); setCurrentTool({ name: toolName, emoji, startTime: Date.now() }); markActive(); },
                      onToolComplete: (toolName, preview, duration, emoji) => {
                        setCurrentTool(null);
                        markActive();
                        if (preview) {
                          setExecutionSummary(prev => [...prev.slice(-5), `${emoji} ${toolName} (${duration.toFixed(1)}s): ${preview}`]);
                        }
                      },
                      onToolError: (toolName, error, emoji) => {
                        setCurrentTool(null);
                        markActive();
                        setExecutionSummary(prev => [...prev.slice(-5), `${emoji} ${toolName} 出错: ${error}`]);
                      },
                      onToolFeedback: (content) => {
                        markActive();
                        if (content) {
                          setExecutionSummary(prev => [...prev.slice(-5), content]);
                        }
                      },
                      onBudgetWarning: (content) => {
                        markActive();
                        if (content) {
                          setExecutionSummary(prev => [...prev.slice(-5), content]);
                        }
                      },
                      onThinkingDelta: (content) => {
                        setMessages(prev => prev.map(m => m.id === aid ? { ...m, thinking: (m.thinking || '') + content } : m));
                        if (!thinkingStartedRef.current) {
                          thinkingStartedRef.current = true;
                          setProgressText('💭 思考中…');
                        }
                        markActive();
                      },
                      onThinkingDone: () => { markActive(); },
                      onAsk: (question, choices, question_id) => { setWaitingQuestion({ question, choices, id: question_id }); setWaitingAnswer(''); markActive(); },
                      onContext: (info) => { setContextInfo(info); },
                      onContent: (_chunk, full) => {
                        setProgressText('');
                        markActive();
                        const thinkMatch = full.match(/<think>([\s\S]*?)晖/);
                        const thinking = thinkMatch ? thinkMatch[1] : '';
                        const displayContent = full.replace(/<think>[\s\S]*?晖/g, '').trim();
                        setMessages(prev => prev.map(m => m.id === aid ? { ...m, content: displayContent, thinking: thinking || m.thinking, status: 'streaming' as const } : m));
                      },
                      onDone: () => {
                        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
                        stopHeartbeat();
                        setProgressText('');
                        setStepHistory([]);
                        setMessages(prev => prev.map(m =>
                          m.id === aid ? { ...m, status: 'completed' as const } : m
                        ));
                        setIsStreaming(false);
                        setIsLoading(false);
                        setCurrentTool(null);
                        abortRef.current = null;
                      },
                      onError: (err) => {
                        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
                        stopHeartbeat();
                        setProgressText('');
                        setStepHistory([]);
                        setErrorMessage(err);
                        setMessages(prev => prev.map(m =>
                          m.id === aid ? { ...m, status: 'error' as const, error: err } : m
                        ));
                        setIsStreaming(false);
                        setIsLoading(false);
                        setCurrentTool(null);
                        abortRef.current = null;
                      },
                    });
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
              <button className="chat-send-btn" onClick={handleSend} disabled={!inputValue.trim() || isLoading} title="发送">→</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default ModernChatPanel;
