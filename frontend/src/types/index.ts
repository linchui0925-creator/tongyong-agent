/**
 * 前端类型定义模块
 * 统一管理所有TypeScript接口和类型
 */

/** 消息角色枚举 */
export type MessageRole = 'user' | 'assistant' | 'system';

/** 消息状态枚举 */
export type MessageStatus = 'sending' | 'streaming' | 'completed' | 'error' | 'waiting';

/** Agent 中间过程步骤 (类似 Codex 展示的可追溯任务时间线) */
export type TraceStepKind = 'text' | 'tool_call' | 'tool_result' | 'tool_error';

export interface TraceStep {
    kind: TraceStepKind;
    /** 用户可读的文字内容 (text 段落, 或 tool 结果预览) */
    content?: string;
    tool_name?: string;
    args?: Record<string, any>;
    preview?: string;
    /** 完整结果 (后端截断到 4KB), 用于二级展开查看 */
    result_full?: string;
    emoji?: string;
    duration?: number;
    timestamp: number;
}

/** 对话消息接口 */
export interface Message {
    id: string;
    role: MessageRole;
    content: string;
    timestamp: number;
    status: MessageStatus;
    error?: string;
    /** 提取的思考过程内容 */
    thinking?: string;
    /** Agent 完成本条回复过程中的中间步骤 (工具调用/中间叙述), 供 UI 折叠成"任务过程"面板 */
    trace?: TraceStep[];
    toolsUsed?: string[];
    commandsExecuted?: string[];
    artifactPreviews?: ArtifactPreview[];
    attachments?: Attachment[];
    executionClaimMismatch?: boolean;
    needsContinue?: boolean;
    stopReason?: string;
    continuePrompt?: string;
    endedBy?: 'budget' | 'ask' | 'evidence_missing' | 'tool_required_retry_exhausted' | 'manual_stop' | 'unknown';
    /** tool 消息的结构化载荷（刷新后可恢复展示） */
    toolMeta?: {
        tool_call_id?: string;
        tool_name?: string;
        emoji?: string;
        success?: boolean;
        content?: string;
        result_full?: string;
        error?: string;
        error_type?: string;
        suggestion?: string;
        elapsed?: number;
        artifact_previews?: ArtifactPreview[];
    };
    /** 流式输出过程中后端推送的阶段描述（如 "正在思考..."），渲染在气泡里 */
    progressLabel?: string;
}

/** 会话信息接口 */
export interface Session {
    id: string;
    name: string;
    created_at: string;
    updated_at: string;
    message_count?: number;
}

/** 聊天请求参数 */
export interface ChatRequest {
    message: string;
    session_id?: string;
    use_memory?: boolean;
}

/** 聊天响应数据 */
export interface ChatResponse {
    reply: string;
    session_id: string;
    memory_added?: any[];
    memory_verification?: any;
    tools_used?: string[];
    processing_time?: number;
}

/** 流式事件类型 */
export type StreamEventType = 'start' | 'content' | 'done' | 'error' | 'progress'
    | 'tool_start' | 'tool_complete' | 'tool_error' | 'tool_feedback'
    | 'thinking_delta' | 'thinking_done' | 'ask' | 'budget_warning'
    | 'usage' | 'context';

/** 工具事件数据 */
export interface ToolEvent {
    tool_name: string;
    arguments?: Record<string, any>;
    result_preview?: string;
    /** 工具完成事件的完整结果 (截断到 4KB) */
    result_full?: string;
    duration?: number;
    error?: boolean;
    emoji: string;
    timestamp: number;
}

/** 流式事件数据 */
export interface StreamEvent {
    type: StreamEventType;
    content?: string;
    full_content?: string;
    session_id?: string;
    memory_added?: any[];
    tools_used?: string[];
    commands_executed?: string[];
    artifact_previews?: ArtifactPreview[];
    processing_time?: number;
    timestamp: number;
    error?: string;
    code?: string;
    emoji?: string;
    tool_name?: string;
    arguments?: Record<string, any>;
    result_preview?: string;
    result_full?: string;
    duration?: number;
    choices?: string[];
    question?: string;
    question_id?: string;
    /** Token 使用量 */
    usage?: {
        input_tokens?: number;
        output_tokens?: number;
        total_tokens?: number;
    };
    /** 当前 LLM 调用所在轮次（usage 事件专属） */
    round?: number;
    /** 累计 token 用量（usage 事件专属） */
    cumulative?: {
        input_tokens?: number;
        output_tokens?: number;
        total_tokens?: number;
    };
    /** 上下文容量快照（context 事件专属）— 前端 TokenUsageBar 用 */
    context?: ContextInfo;
    /** 长任务达到单次执行上限时，后端提示前端可继续 */
    needs_continue?: boolean;
    stop_reason?: string;
    continue_prompt?: string;
    ended_by?: 'budget' | 'ask' | 'evidence_missing' | 'tool_required_retry_exhausted' | 'manual_stop' | 'unknown';
    /** W5-8: runtime 反思器对本轮的判定 (done 事件专属) */
    /** W5-8: plan_loaded 事件携带的计划数据 */
    plan?: any;
    reflection?: {
        decision: 'complete' | 'retry' | 'revise';
        reasons?: string[];
        correction?: string | null;
        missing_evidence?: string[];
    } | null;
}

export interface ArtifactPreview {
    path: string;
    name: string;
    kind: 'web' | 'image';
    preview_url: string;
    open_url: string;
    render_mode?: 'iframe' | 'image';
}

export interface Attachment {
    id: string;
    session_id?: string | null;
    filename: string;
    name: string;
    mime_type: string;
    size: number;
    sha256?: string;
    kind: 'image' | 'file' | 'pdf' | 'text' | 'table' | 'document';
    url: string;
    preview_url?: string;
    open_url?: string;
    created_at?: number;
    extraction_status?: string;
    extraction_summary?: string;
    extraction_error?: string | null;
    extraction_meta?: Record<string, any>;
}

/** 上下文容量信息 — 后端 _context() 事件载荷，驱动 TokenUsageBar */
export interface ContextInfo {
    chars: number;
    estimated_tokens: number;
    threshold_tokens: number;
    percent: number;          // estimated_tokens / threshold_tokens * 100
    approaching: boolean;     // estimated_tokens >= threshold_tokens * 0.8
}

/** SSE事件源 */
export interface SSECallbacks {
    onStart?: () => void;
    onProgress?: (content: string) => void;
    onContent?: (content: string, fullContent: string) => void;
    onDone?: (data: StreamEvent) => void;
    onError?: (error: string) => void;
    /** 工具开始执行 */
    onToolStart?: (toolName: string, args: Record<string, any>, emoji: string) => void;
    /** 工具执行完成 */
    onToolComplete?: (toolName: string, preview: string, duration: number, emoji: string, resultFull?: string) => void;
    /** 工具执行出错 */
    onToolError?: (toolName: string, error: string, emoji: string) => void;
    /** 工具执行反馈（如已调用工具列表） */
    onToolFeedback?: (content: string) => void;
    /** 预算警告或阶段性告警 */
    onBudgetWarning?: (content: string) => void;
    /** 思考过程增量 */
    onThinkingDelta?: (content: string) => void;
    /** 思考过程完成 */
    onThinkingDone?: () => void;
    /** W5-8: plan_loaded 事件 — 计划已加载 */
    onPlanLoaded?: (plan: any) => void;
    /** 等待用户交互式回答 */
    onAsk?: (question: string, choices: string[], question_id: string) => void;
    /** ask-first 时自动聚焦到输入框上方面板 */
    onAskPanelOpen?: (question: string) => void;
    /** Token 使用量更新（实时） */
    onUsage?: (inputTokens: number, outputTokens: number, totalTokens: number) => void;
    /** 上下文容量更新（实时）— 每次 LLM 调用前/压缩后推，TokenUsageBar 用 */
    onContext?: (info: ContextInfo) => void;
    /** 语音层：识别到用户语音文本 */
    onVoiceTranscript?: (text: string) => void;
    /** 语音层：TTS 音频已生成 */
    onVoiceAudioReady?: (audioUrl: string) => void;
}

/** UI主题配置 */
export interface ThemeConfig {
    primaryColor: string;
    secondaryColor: string;
    backgroundColor: string;
    textColor: string;
    borderRadius: number;
    fontFamily: string;
}

/** 用户偏好设置 */
export interface UserPreferences {
    theme: 'light' | 'dark' | 'auto';
    fontSize: number;
    streamingSpeed: number;
    showTimestamps: boolean;
    enableKeyboardShortcuts: boolean;
    autoScroll: boolean;
}

/** 确认对话框配置 */
export interface ConfirmDialogConfig {
    title: string;
    message: string;
    confirmText?: string;
    cancelText?: string;
    type?: 'warning' | 'danger' | 'info';
    onConfirm: () => void;
    onCancel?: () => void;
}

/** 快捷键配置 */
export interface KeyboardShortcut {
    key: string;
    ctrl?: boolean;
    shift?: boolean;
    alt?: boolean;
    meta?: boolean;
    action: () => void;
    description: string;
}

/** 头像配置 */
export interface AvatarConfig {
    type: 'image' | 'emoji';
    value: string;
}

/** 打字机效果配置 */
export interface TypewriterConfig {
    enabled: boolean;
    speed: number;
    minDelay: number;
    maxDelay: number;
}
