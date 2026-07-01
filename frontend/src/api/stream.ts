/**
 * 流式聊天API模块
 * 提供SSE流式输出功能，支持实时对话和打字机效果
 */
import { SSECallbacks, StreamEvent } from '../types';

const API_BASE_URL = '/api/chat';
// const REQUEST_TIMEOUT = 120000;  // unused - stream handled by AbortController

/**
 * 解析SSE事件数据
 * @param event - SSE事件
 * @returns 解析后的事件对象
 */
function parseEventData(event: MessageEvent): StreamEvent | null {
    try {
        const data = JSON.parse(event.data);
        return {
            type: data.type || 'unknown',
            content: data.content,
            full_content: data.full_content,
            session_id: data.session_id,
            memory_added: data.memory_added,
            tools_used: data.tools_used,
            timestamp: data.timestamp || Date.now(),
            error: data.message || data.error,
            code: data.code,
            emoji: data.emoji,
            tool_name: data.tool_name,
            arguments: data.arguments,
            result_preview: data.result_preview,
            duration: data.duration,
            choices: data.choices,
            question: data.question,
            question_id: data.question_id,
            commands_executed: data.commands_executed,
            processing_time: data.processing_time,
            usage: data.usage,
            round: data.round,
            cumulative: data.cumulative,
            context: data.context,
            needs_continue: data.needs_continue,
            stop_reason: data.stop_reason,
            continue_prompt: data.continue_prompt,
        };
    } catch (error) {
        console.error('解析SSE事件数据失败:', error);
        return null;
    }
}

/**
 * 创建流式聊天连接
 * 使用Server-Sent Events实现实时流式输出
 * 
 * @param message - 用户消息
 * @param sessionId - 会话ID（可选）
 * @param useMemory - 是否使用记忆功能（默认true）
 * @param callbacks - 事件回调函数
 * @returns AbortController用于中断请求
 * 
 * @example
 * ```typescript
 * const controller = streamChat('你好', 'session-123', true, {
 *   onStart: () => console.log('开始流式输出'),
 *   onContent: (content, full) => updateMessage(full),
 *   onDone: (data) => console.log('完成', data),
 *   onError: (error) => console.error('错误', error)
 * });
 * 
 * // 中断流式输出
 * controller.abort();
 * ```
 */
export function streamChat(
    message: string,
    sessionId?: string,
    useMemory: boolean = true,
    callbacks: SSECallbacks = {},
    clarifyQuestionId?: string,
    clarifyAnswer?: string
): AbortController {
    const controller = new AbortController();

    // 参数验证
    if (!message || message.trim() === '') {
        callbacks.onError?.('消息内容不能为空');
        return controller;
    }

    if (message.length > 10000) {
        callbacks.onError?.('消息内容过长，最大支持10000字符');
        return controller;
    }

    // 构建请求数据
    const requestData = {
        message: message.trim(),
        session_id: sessionId || undefined,
        use_memory: useMemory,
        clarify_question_id: clarifyQuestionId || undefined,
        clarify_answer: clarifyAnswer || undefined
    };

    console.log('[流式聊天请求]', requestData);

    // 使用fetch API进行SSE请求
    fetch(`${API_BASE_URL}/stream`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(requestData),
        signal: controller.signal
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP错误: ${response.status}`);
        }
        return response.body?.getReader();
    })
    .then(reader => {
        if (!reader) {
            throw new Error('无法获取响应体');
        }

        const decoder = new TextDecoder();
        let buffer = '';

        const readStream = () => {
            reader.read().then(({ done, value }) => {
                if (done) {
                    console.log('[流式响应完成]');
                    return;
                }

                buffer += decoder.decode(value, { stream: true });
                console.log('[SSE原始数据]', buffer);
                
                // 处理缓冲区中的完整行
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (let i = 0; i < lines.length; i++) {
                    const trimmedLine = lines[i].trim();
                    if (!trimmedLine) continue;

                    if (trimmedLine.startsWith('event:')) {
                        const eventType = trimmedLine.slice(6).trim();
                        // Read the next line which should be the data line
                        const nextLine = lines[i + 1]?.trim();
                        if (nextLine?.startsWith('data:')) {
                            const dataLine = nextLine.slice(5);
                            const event = parseEventData({ data: dataLine } as MessageEvent);
                            if (event) {
                                handleStreamEvent(event, eventType, callbacks);
                            }
                            i++; // Skip the data line — already handled
                        }
                    } else if (trimmedLine.startsWith('data:')) {
                        const dataLine = trimmedLine.slice(5);
                        const event = parseEventData({ data: dataLine } as MessageEvent);
                        if (event) {
                            handleStreamEvent(event, event.type, callbacks);
                        }
                    }
                }

                readStream();
            });
        };

        readStream();
    })
    .catch(error => {
        // 忽略AbortError，这是正常的请求中止，不显示错误
        if (error.name === 'AbortError' || error.message?.includes('abort')) {
            console.log('[流式请求已中断]');
            return;
        }
        
        console.error('[流式请求错误]', error);
        callbacks.onError?.(error.message || '网络错误');
    });

    return controller;
}

/**
 * 处理流式事件
 */
function handleStreamEvent(
    event: StreamEvent,
    eventType: string,
    callbacks: SSECallbacks
): void {
    switch (eventType) {
        case 'start':
            console.log('[流式开始]', event);
            callbacks.onStart?.();
            break;

        case 'progress':
            console.log('[进度]', event.content);
            callbacks.onProgress?.(event.content || '');
            break;

        case 'tool_start':
            callbacks.onToolStart?.(event.tool_name || '', event.arguments || {}, event.emoji || '⚡');
            callbacks.onProgress?.(`${event.emoji || '⚡'} ${event.tool_name || ''}`);
            break;

        case 'tool_complete':
            callbacks.onToolComplete?.(event.tool_name || '', event.result_preview || '', event.duration || 0, event.emoji || '⚡');
            if (event.result_preview) {
                callbacks.onProgress?.(`${event.emoji || '⚡'} ${event.tool_name || ''} 完成: ${event.result_preview}`);
            }
            break;

        case 'tool_error':
            callbacks.onToolError?.(event.tool_name || '', event.error || '', event.emoji || '⚡');
            break;

        case 'tool_feedback':
            callbacks.onToolFeedback?.(event.content || '');
            break;

        case 'budget_warning':
            callbacks.onBudgetWarning?.(event.content || '');
            callbacks.onProgress?.(event.content || '');
            break;

        case 'usage':
            // 实时 token 使用量
            if (event.usage) {
                const { input_tokens = 0, output_tokens = 0, total_tokens = 0 } = event.usage;
                callbacks.onUsage?.(input_tokens, output_tokens, total_tokens);
            }
            break;

        case 'context':
            // 上下文容量快照 — 驱动 TokenUsageBar
            if (event.context) {
                callbacks.onContext?.(event.context);
            }
            break;

        case 'thinking_delta':
            callbacks.onThinkingDelta?.(event.content || '');
            break;

        case 'thinking_done':
            callbacks.onThinkingDone?.();
            break;

        case 'ask':
            callbacks.onAsk?.(
                event.question || '',
                event.choices || [],
                event.question_id || ''
            );
            break;

        case 'content':
            console.log('[流式内容]', event.content);
            callbacks.onContent?.(event.content || '', event.full_content || '');
            break;

        case 'done':
            console.log('[流式完成]', event);
            // 最终 token 统计
            if (event.usage) {
                const { input_tokens = 0, output_tokens = 0, total_tokens = 0 } = event.usage;
                callbacks.onUsage?.(input_tokens, output_tokens, total_tokens);
            }
            callbacks.onDone?.(event);
            break;

        case 'error':
            console.error('[流式错误]', event.error);
            callbacks.onError?.(event.error || '未知错误');
            break;

        default:
            console.warn('[未知事件类型]', eventType, event);
    }
}

/**
 * 测试流式输出端点
 */
export async function testStreamEndpoint(): Promise<boolean> {
    try {
        const response = await fetch(`${API_BASE_URL}/stream/test`);
        return response.ok;
    } catch (error) {
        console.error('[流式端点测试失败]', error);
        return false;
    }
}

/**
 * 生成唯一消息ID
 */
export function generateMessageId(): string {
    return `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * 主动压缩 session 历史上下文（前端 TokenUsageBar 触发）。
 *
 * 调后端 POST /api/chat/compress：
 *   - force=false（默认）：尊重 should_compress 阈值，未达则返回 {skipped: true}
 *   - force=true：跳过阈值检查直接压
 *
 * 返回 {success, before/after tokens, saved_pct, summary, skipped}，
 * 前端用 before/after 刷新 TokenUsageBar 进度条。
 */
export async function compressSessionContext(
    sessionId: string,
    force: boolean = false,
): Promise<{
    success: boolean;
    session_id?: string;
    before_messages?: number;
    after_messages?: number;
    before_tokens?: number;
    after_tokens?: number;
    saved_pct?: number;
    summary?: string;
    skipped?: boolean;
    forced?: boolean;
    error?: string;
}> {
    try {
        const response = await fetch(`${API_BASE_URL}/compress`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, force }),
        });
        if (!response.ok) {
            return { success: false, error: `HTTP ${response.status}` };
        }
        return await response.json();
    } catch (error: any) {
        console.error('[compressSessionContext] 失败:', error);
        return { success: false, error: error?.message || String(error) };
    }
}

/**
 * 读 session 当前 context 容量（前端启动 / 切 session 时用来初始化 TokenUsageBar）。
 *
 * 调后端 GET /api/chat/context-stats/{session_id}，返回
 * {chars, estimated_tokens, threshold_tokens, percent, approaching, message_count}。
 */
export async function getContextStats(
    sessionId: string,
): Promise<{
    session_id?: string;
    message_count?: number;
    chars?: number;
    estimated_tokens?: number;
    threshold_tokens?: number;
    percent?: number;
    approaching?: boolean;
    error?: string;
}> {
    try {
        const response = await fetch(`${API_BASE_URL}/context-stats/${encodeURIComponent(sessionId)}`);
        if (!response.ok) {
            return { error: `HTTP ${response.status}` };
        }
        return await response.json();
    } catch (error: any) {
        console.error('[getContextStats] 失败:', error);
        return { error: error?.message || String(error) };
    }
}
