/**
 * useStreamChat — 抽取自 ModernChatPanel 的流式对话状态机 (P3-1)
 *
 * 持有所有 stream_chat 相关状态 (messages / isStreaming / progressText /
 * currentTool / tokenUsage / contextInfo / savedFlash / waitingQuestion 等),
 * 以及 send / stop / compress / delete / toggleThinking / clarify 等操作。
 *
 * 把这部分从 ModernChatPanel 拆出来, 组件文件从 1104 行降到 ~700 行。
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import {
  streamChat,
  generateMessageId,
  compressSessionContext,
  getContextStats,
} from '../api/stream';
import { getSessionMessages } from '../api/memory';
import { submitClarifyAnswer } from '../api/chat';
import { createEvaluation } from '../api/evaluation';
import { Attachment, Message, ContextInfo } from '../types';

const EXECUTION_CLAIM_PATTERNS = [
  '已调用', '已执行', '已打开', '已访问', '已搜索', '已截图', '已导航', '我已经调用', '我已调用',
];

function looksLikeExecutionClaim(content: string): boolean {
  const text = (content || '').toLowerCase();
  return EXECUTION_CLAIM_PATTERNS.some((p) => text.includes(p));
}

export interface UseStreamChatOptions {
  sessionId: string;
  onError?: (err: string) => void;
  onSessionCreated?: (sessionId: string) => void;
}

export interface UseStreamChatReturn {
  messages: Message[];
  isStreaming: boolean;
  isLoading: boolean;
  errorMessage: string | null;
  progressText: string;
  elapsed: number;
  currentTool: { name: string; emoji: string; startTime: number } | null;
  toolElapsed: number;
  tokenUsage: { input: number; output: number; total: number } | null;
  contextInfo: ContextInfo | null;
  isCompressing: boolean;
  savedFlash: string | null;
  expandedThinkingMsgId: string | null;
  waitingQuestion: { question: string; choices: string[]; id: string } | null;
  pendingContinue: { prompt: string; reason: string } | null;
  setErrorMessage: (msg: string | null) => void;
  loadMessages: (sid: string) => Promise<void>;
  handleSend: (text: string, attachments?: Attachment[]) => Promise<void>;
  handleStop: () => void;
  handleCompress: (force?: boolean) => Promise<void>;
  handleDelete: (id: string) => void;
  handleToggleThinking: (id: string) => void;
  handleClarifyAnswer: (answer: string) => Promise<void>;
  handleContinue: () => Promise<void>;
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  refreshContextStats: () => Promise<void>;
}

export function useStreamChat({ sessionId, onError, onSessionCreated }: UseStreamChatOptions): UseStreamChatReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [progressText, setProgressText] = useState<string>('');
  const [elapsed, setElapsed] = useState<number>(0);
  const [currentTool, setCurrentTool] = useState<{ name: string; emoji: string; startTime: number } | null>(null);
  const [toolElapsed, setToolElapsed] = useState<number>(0);
  const [tokenUsage, setTokenUsage] = useState<{ input: number; output: number; total: number } | null>(null);
  const [contextInfo, setContextInfo] = useState<ContextInfo | null>(null);
  const [isCompressing, setIsCompressing] = useState(false);
  const [savedFlash, setSavedFlash] = useState<string | null>(null);
  const [expandedThinkingMsgId, setExpandedThinkingMsgId] = useState<string | null>(null);
  const [waitingQuestion, setWaitingQuestion] = useState<{ question: string; choices: string[]; id: string } | null>(null);
  const [pendingContinue, setPendingContinue] = useState<{ prompt: string; reason: string } | null>(null);

  const currentToolRef = useRef<{ name: string; emoji: string; startTime: number } | null>(null);
  useEffect(() => { currentToolRef.current = currentTool; }, [currentTool]);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const savedFlashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastEventTimeRef = useRef<number>(Date.now());
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const thinkingStartedRef = useRef<boolean>(false);
  // 追踪 agent 中间过程 (工具调用+叙述), 用于 UI "任务过程"折叠面板
  const traceRef = useRef<{ msgId: string | null; flushedLen: number; hasTool: boolean }>({
    msgId: null, flushedLen: 0, hasTool: false,
  });
  const fullContentRef = useRef<string>('');

  const pushTrace = useCallback((msgId: string, step: import('../types').TraceStep) => {
    setMessages((prev) => prev.map((m) =>
      m.id === msgId ? { ...m, trace: [...(m.trace || []), step] } : m
    ));
  }, []);

  const flushPendingTextIntoTrace = useCallback((msgId: string) => {
    const full = fullContentRef.current;
    const st = traceRef.current;
    if (st.msgId !== msgId) return;
    const pending = full.slice(st.flushedLen)
      .replace(/<think>[\s\S]*?<\/think>/g, '')
      .trim();
    if (pending) {
      pushTrace(msgId, { kind: 'text', content: pending, timestamp: Date.now() });
    }
    st.flushedLen = full.length;
  }, [pushTrace]);

  const loadMessages = useCallback(async (sid: string) => {
    if (!sid) return;
    try {
      const data = await getSessionMessages(sid);
      const metaStart = '<<<TOOL_META_JSON>>>';
      const metaEnd = '<<<TOOL_META_JSON_END>>>';
      const msgs: Message[] = (data.messages || []).map((m: any, i: number) => {
        const rawContent = m.content || '';
        const metaStartIdx = rawContent.indexOf(metaStart);
        const metaEndIdx = rawContent.indexOf(metaEnd);
        let toolsUsed: string[] | undefined;
        let commandsExecuted: string[] | undefined;
        let cleanedContent = rawContent;
        if (metaStartIdx >= 0 && metaEndIdx > metaStartIdx) {
          const metaJson = rawContent.slice(metaStartIdx + metaStart.length, metaEndIdx).trim();
          try {
            const parsed = JSON.parse(metaJson);
            toolsUsed = Array.isArray(parsed.tools_used) ? parsed.tools_used : undefined;
            commandsExecuted = Array.isArray(parsed.commands_executed) ? parsed.commands_executed : undefined;
          } catch {
            // ignore malformed metadata
          }
          cleanedContent = rawContent.slice(0, metaStartIdx).trim();
        }
        const cleanedForThink = cleanedContent.replace(/<\|im_start\|[^|]*\|[^>]*>[\s\S]*?<\|im_end\|>/g, '');
        const thinkMatch = cleanedForThink.match(/<think>([\s\S]*?)<\/think>/);
        const thinking = thinkMatch ? thinkMatch[1] : '';
        const displayContent = cleanedForThink.replace(/<think>[\s\S]*?<\/think>/g, '').trim();

        let toolMeta: Message['toolMeta'] | undefined;
        let artifactPreviews: Message['artifactPreviews'] | undefined;
        if (m.role === 'tool') {
          try {
            const parsed = JSON.parse(rawContent);
            if (parsed && typeof parsed === 'object') {
              toolMeta = {
                tool_call_id: parsed.tool_call_id,
                tool_name: parsed.tool_name,
                emoji: parsed.emoji,
                success: parsed.success,
                content: parsed.content,
                result_full: parsed.result_full,
                error: parsed.error,
                error_type: parsed.error_type,
                suggestion: parsed.suggestion,
                elapsed: parsed.elapsed,
              };

              const previews = Array.isArray(parsed.artifact_previews) ? parsed.artifact_previews : [];
              if (previews.length > 0) {
                artifactPreviews = previews
                  .filter((item: any) => item && item.path && item.kind)
                  .map((item: any) => ({
                    path: String(item.path),
                    name: String(item.name || item.path.split('/').pop() || 'artifact'),
                    kind: item.kind === 'image' ? 'image' : 'web',
                    preview_url: String(item.preview_url || item.open_url || ''),
                    open_url: String(item.open_url || item.preview_url || ''),
                    render_mode: item.render_mode === 'image' ? 'image' : 'iframe',
                  }));
              } else {
                const candidateText = String(parsed.result_full || parsed.content || '');
                const pathMatch = candidateText.match(/absolute_path=([^\s\n]+)/);
                const fileMatch = candidateText.match(/workspace\/(?:[^\s\n/]+)\/([^\s\n]+)/);
                const targetPath = pathMatch?.[1] || '';
                const name = fileMatch?.[1] || parsed.tool_name || 'artifact';
                const kind: 'web' | 'image' | undefined = /\.(png|jpg|jpeg|gif|webp)$/i.test(name)
                  ? 'image'
                  : /\.(html?|xhtml|htm)$/i.test(name) || /<html|<!doctype|<iframe/i.test(candidateText)
                    ? 'web'
                    : undefined;
                if (kind && targetPath) {
                  const backend = (typeof window !== 'undefined' && (window as any).__BACKEND_URL__) || 'http://127.0.0.1:8000';
                  const previewUrl = targetPath.startsWith('http')
                    ? targetPath
                    : `${backend}/api/files/serve?path=${encodeURIComponent(targetPath)}`;
                  artifactPreviews = [{
                    path: targetPath,
                    name,
                    kind,
                    preview_url: previewUrl,
                    open_url: previewUrl,
                  }];
                }
              }
            }
          } catch {
            toolMeta = { content: displayContent || rawContent };
          }
        }

        const trace = toolMeta ? [{
          kind: toolMeta.success === false ? 'tool_error' as const : 'tool_result' as const,
          tool_name: toolMeta.tool_name,
          preview: toolMeta.content,
          result_full: toolMeta.result_full,
          emoji: toolMeta.emoji,
          duration: toolMeta.elapsed,
          timestamp: new Date(m.created_at || Date.now()).getTime(),
        }] : (toolsUsed?.length ? toolsUsed.map((tool_name) => ({
          kind: 'tool_call' as const,
          tool_name,
          timestamp: new Date(m.created_at || Date.now()).getTime(),
        })) : undefined);
        return {
          id: m.id || `msg-${i}`,
          role: m.role,
          content: m.role === 'tool' ? (toolMeta?.content || displayContent || rawContent) : displayContent,
          thinking: thinking || undefined,
          timestamp: new Date(m.created_at || Date.now()).getTime(),
          status: 'completed' as const,
          toolsUsed,
          commandsExecuted,
          toolMeta,
          artifactPreviews,
          trace,
        };
      });
      setMessages(msgs);
    } catch {
      setMessages([]);
    }
  }, []);

  useEffect(() => {
    if (sessionId) loadMessages(sessionId);
  }, [sessionId, loadMessages]);

  const refreshContextStats = useCallback(async () => {
    if (!sessionId) return;
    try {
      const stats = await getContextStats(sessionId);
      if (stats && !stats.error && stats.threshold_tokens !== undefined) {
        setContextInfo({
          chars: stats.chars ?? 0,
          estimated_tokens: stats.estimated_tokens ?? 0,
          threshold_tokens: stats.threshold_tokens,
          percent: stats.percent ?? 0,
          approaching: stats.approaching ?? false,
        });
      }
    } catch (err) {
      console.warn('[useStreamChat] getContextStats 失败:', err);
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) {
      setContextInfo(null);
      return;
    }
    let cancelled = false;
    getContextStats(sessionId).then((stats) => {
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
      console.warn('[useStreamChat] getContextStats 失败:', err);
    });
    return () => { cancelled = true; };
  }, [sessionId]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      if (savedFlashTimerRef.current) clearTimeout(savedFlashTimerRef.current);
    };
  }, []);

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
        setProgressText((prev) => {
          if (prev && !prev.startsWith('💭') && !prev.startsWith('⏳')) return prev;
          return label;
        });
        setMessages((prev) => prev.map((m) =>
          m.id === msgId && m.status === 'streaming' ? { ...m, progressLabel: label } : m
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

  const startStream = useCallback((text: string, msgId: string, clarifyQId?: string, clarifyAns?: string, attachmentIds?: string[]) => {
    abortRef.current?.abort();
    abortRef.current = streamChat(text, sessionId || undefined, true, {
      onStart: () => {
        setIsStreaming(true);
        setProgressText('连接中...');
        setExpandedThinkingMsgId(null);
        thinkingStartedRef.current = false;
        traceRef.current = { msgId: msgId, flushedLen: 0, hasTool: false };
        fullContentRef.current = '';
        startHeartbeat(msgId);
        markActive();
      },
      onProgress: (content) => {
        setProgressText(content);
        markActive();
        setMessages((prev) => prev.map((m) =>
          m.id === msgId && m.status === 'streaming' ? { ...m, progressLabel: content } : m
        ));
      },
      onToolStart: (toolName, args, emoji) => {
        setToolElapsed(0);
        setCurrentTool({ name: toolName, emoji, startTime: Date.now() });
        traceRef.current.hasTool = true;
        flushPendingTextIntoTrace(msgId);
        pushTrace(msgId, {
          kind: 'tool_call', tool_name: toolName, args, emoji, timestamp: Date.now(),
        });
        markActive();
      },
      onToolComplete: (toolName, preview, duration, emoji, resultFull) => {
        setCurrentTool(null);
        pushTrace(msgId, {
          kind: 'tool_result', tool_name: toolName, preview, duration, emoji,
          result_full: resultFull,
          timestamp: Date.now(),
        });
        markActive();
        if (preview) {
          console.log(`[tool] ${emoji} ${toolName} (${duration.toFixed(1)}s): ${preview}`);
        }
      },
      onToolError: (toolName, error, emoji) => {
        setCurrentTool(null);
        pushTrace(msgId, {
          kind: 'tool_error', tool_name: toolName, content: error, emoji,
          timestamp: Date.now(),
        });
        markActive();
        console.warn(`[tool] ${emoji} ${toolName} 出错: ${error}`);
      },
      onToolFeedback: (content) => {
        markActive();
        if (content) console.log('[tool feedback]', content);
      },
      onBudgetWarning: (content) => {
        markActive();
        if (content) console.warn('[budget]', content);
      },
      onThinkingDelta: (content) => {
        setMessages((prev) => prev.map((m) =>
          m.id === msgId ? { ...m, thinking: (m.thinking || '') + content } : m
        ));
        if (!thinkingStartedRef.current) {
          thinkingStartedRef.current = true;
          setProgressText('💭 思考中…');
        }
        markActive();
      },
      onThinkingDone: () => { markActive(); },
      onAsk: (question, choices, question_id) => {
        setWaitingQuestion({ question, choices, id: question_id });
        setIsStreaming(false);
        setProgressText('等待回答...');
        markActive();
      },
      onUsage: (input, output, total) => {
        setTokenUsage({ input, output, total });
      },
      onContext: (info) => {
        setContextInfo(info);
      },
      onContent: (_chunk, full) => {
        setProgressText('');
        markActive();
        fullContentRef.current = full;
        const thinkMatch = full.match(/<think>([\s\S]*?)<\/think>/);
        const thinking = thinkMatch ? thinkMatch[1] : '';
        // 如果本条消息经历过工具调用, 只把"最后一次工具后"的文本作为最终气泡内容,
        // 之前的叙述在下一次 tool_start / done 时被 flush 到 trace 时间线
        const st = traceRef.current;
        const rawTail = st.hasTool ? full.slice(st.flushedLen) : full;
        const displayContent = rawTail.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
        setMessages((prev) => prev.map((m) =>
          m.id === msgId ? { ...m, content: displayContent, thinking: thinking || m.thinking, status: 'streaming' as const } : m
        ));
      },
      onDone: (data) => {
        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
        stopHeartbeat();
        setProgressText('');
        setCurrentTool(null);
        // done 时如果最后一段文本还未落到 trace 且没有真实答案内容, 兜底把它作为最终答案
        // 若有 tool 且最后 content 为空, 用最后一段 pending 作为答案
        const st = traceRef.current;
        if (st.hasTool) {
          const full = fullContentRef.current;
          const tail = full.slice(st.flushedLen).replace(/<think>[\s\S]*?<\/think>/g, '').trim();
          if (!tail) {
            // agent 完成后没有再输出新 content, 说明最后一段本身就应是答案 → 把最近一次 flush 之前的最后一段 text 回补作为 content
            setMessages((prev) => prev.map((m) => {
              if (m.id !== msgId) return m;
              if (m.content && m.content.trim().length > 0) return m;
              const lastText = (m.trace || []).filter((s) => s.kind === 'text').slice(-1)[0];
              if (!lastText) return m;
              return { ...m, content: (lastText.content || '').trim(), trace: (m.trace || []).slice(0, -1) };
            }));
          }
        }
        setMessages((prev) => prev.map((m) =>
          m.id === msgId ? {
            ...m,
            status: 'completed' as const,
            toolsUsed: data.tools_used || [],
            commandsExecuted: data.commands_executed || [],
            artifactPreviews: data.artifact_previews || [],
            needsContinue: Boolean(data.needs_continue),
            stopReason: data.stop_reason || undefined,
            continuePrompt: data.continue_prompt || undefined,
            endedBy: data.ended_by || undefined,
            executionClaimMismatch: looksLikeExecutionClaim(m.content) && !((data.tools_used && data.tools_used.length > 0) || (data.commands_executed && data.commands_executed.length > 0)),
          } : m
        ));
        if (data.needs_continue) {
          setPendingContinue({
            prompt: data.continue_prompt || '继续上一个任务，从未完成的下一步继续执行。',
            reason: data.stop_reason || '长任务达到单次执行上限',
          });
        } else {
          setPendingContinue(null);
        }
        setIsStreaming(false);
        setIsLoading(false);
        abortRef.current = null;

        if (data.session_id) {
          if (data.session_id !== sessionId) onSessionCreated?.(data.session_id);
          getContextStats(data.session_id).then((stats) => {
            if (!stats.error && stats.chars !== undefined && stats.estimated_tokens !== undefined
              && stats.threshold_tokens !== undefined && stats.percent !== undefined
              && stats.approaching !== undefined) {
              setContextInfo(stats as ContextInfo);
            }
          }).catch(() => undefined);
        }

        if (data.session_id && data.tools_used && data.tools_used.length > 0) {
          createEvaluation({
            session_id: data.session_id,
            tools_used: data.tools_used || [],
            commands_executed: data.commands_executed || [],
            processing_time: data.processing_time || 0,
            usage: data.usage || {},
          }).catch((err) => {
            console.error('[评估] 创建评估失败:', err);
          });
        }
      },
      onError: (err) => {
        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
        stopHeartbeat();
        setProgressText('');
        setErrorMessage(err);
        setCurrentTool(null);
        setMessages((prev) => prev.map((m) =>
          m.id === msgId ? { ...m, status: 'error' as const, error: err } : m
        ));
        setIsStreaming(false);
        setIsLoading(false);
        abortRef.current = null;
        onError?.(err);
      },
    }, clarifyQId, clarifyAns, attachmentIds);
  }, [sessionId, onError]);

  const handleSend = useCallback(async (text: string, attachments: Attachment[] = []) => {
    const trimmed = text.trim();
    if ((!trimmed && attachments.length === 0) || isLoading || isStreaming) return;

    const uid = generateMessageId();
    const aid = generateMessageId();
    const displayText = trimmed || `上传了 ${attachments.length} 个附件`;
    const attachmentIds = attachments.map((item) => item.id);

    setMessages((prev) => [...prev,
      { id: uid, role: 'user', content: displayText, timestamp: Date.now(), status: 'completed', attachments },
      { id: aid, role: 'assistant', content: '', timestamp: Date.now(), status: 'streaming' },
    ]);
    setIsLoading(true);
    setErrorMessage(null);
    setPendingContinue(null);
    setElapsed(0);
    setToolElapsed(0);
    setCurrentTool(null);
    setTokenUsage(null);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setElapsed((p) => p + 100);
      setToolElapsed((p) => p + 100);
    }, 100);

    startStream(displayText, aid, undefined, undefined, attachmentIds);
  }, [isLoading, isStreaming, startStream]);

  const handleContinue = useCallback(async () => {
    if (!pendingContinue || isLoading || isStreaming) return;
    await handleSend(pendingContinue.prompt);
  }, [pendingContinue, isLoading, isStreaming, handleSend]);

  const handleStop = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    stopHeartbeat();
    abortRef.current?.abort();
    setIsStreaming(false);
    setIsLoading(false);
    setProgressText('');
    setCurrentTool(null);
    setMessages((prev) => prev.map((m) =>
      m.status === 'streaming' ? { ...m, status: 'completed' as const } : m
    ));
  }, []);

  const handleCompress = useCallback(async (force: boolean = false) => {
    if (!sessionId || isCompressing) return;
    setIsCompressing(true);
    try {
      const result = await compressSessionContext(sessionId, force);
      if (result.success) {
        await refreshContextStats();
        if (result.skipped) {
          setSavedFlash('未达阈值');
        } else {
          const saved = result.saved_pct ?? 0;
          setSavedFlash(`✓ 节省 ${saved.toFixed(0)}% (${result.before_tokens}→${result.after_tokens} tok)`);
        }
      } else {
        setSavedFlash(`✗ 压缩失败: ${result.error || '未知错误'}`);
      }
    } catch (err: any) {
      console.error('[handleCompress] 失败:', err);
      setSavedFlash(`✗ 错误: ${err?.message || String(err)}`);
    } finally {
      if (savedFlashTimerRef.current) clearTimeout(savedFlashTimerRef.current);
      savedFlashTimerRef.current = setTimeout(() => setSavedFlash(null), 3000);
      setIsCompressing(false);
    }
  }, [sessionId, isCompressing, refreshContextStats]);

  const handleDelete = useCallback((id: string) => {
    setMessages((prev) => prev.filter((m) => m.id !== id));
  }, []);

  const handleToggleThinking = useCallback((id: string) => {
    setExpandedThinkingMsgId((prev) => (prev === id ? null : id));
  }, []);

  const handleClarifyAnswer = useCallback(async (answer: string) => {
    if (!waitingQuestion) return;
    const qid = waitingQuestion.id;
    await submitClarifyAnswer(qid, answer, sessionId || undefined);
    setWaitingQuestion(null);
    setIsLoading(true);
    setIsStreaming(true);
    setProgressText('继续中...');

    const uid = generateMessageId();
    const aid = generateMessageId();
    setMessages((prev) => [...prev,
      { id: uid, role: 'user', content: answer, timestamp: Date.now(), status: 'completed' as const },
      { id: aid, role: 'assistant', content: '', timestamp: Date.now(), status: 'streaming' as const },
    ]);
    startStream(answer, aid, qid, answer);
  }, [waitingQuestion, sessionId, startStream]);

  return {
    messages,
    isStreaming,
    isLoading,
    errorMessage,
    progressText,
    elapsed,
    currentTool,
    toolElapsed,
    tokenUsage,
    contextInfo,
    isCompressing,
    savedFlash,
    expandedThinkingMsgId,
    waitingQuestion,
    pendingContinue,
    setErrorMessage,
    loadMessages,
    handleSend,
    handleStop,
    handleCompress,
    handleDelete,
    handleToggleThinking,
    handleClarifyAnswer,
    handleContinue,
    setMessages,
    refreshContextStats,
  };
}
