/**
 * 聊天API模块
 * 提供聊天功能，支持会话管理和记忆检索
 */
import axios, { AxiosInstance, AxiosError } from 'axios'

// API配置常量
const API_BASE_URL = '/api/chat'
const REQUEST_TIMEOUT = 30000  // 30秒超时

// 创建axios实例
const api: AxiosInstance = axios.create({
    baseURL: API_BASE_URL,
    timeout: REQUEST_TIMEOUT,
    headers: {
        'Content-Type': 'application/json'
    }
})

// 请求拦截器
api.interceptors.request.use(
    (config) => {
        console.log(`[API请求] ${config.method?.toUpperCase()} ${config.url}`, {
            params: config.params,
            data: config.data
        })
        return config
    },
    (error) => {
        console.error('[请求错误]', error)
        return Promise.reject(error)
    }
)

// 响应拦截器
api.interceptors.response.use(
    (response) => {
        console.log(`[API响应] ${response.config.url}`, response.data)
        return response
    },
    async (error: AxiosError) => {
        const originalRequest = error.config
        
        // 处理超时错误
        if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
            console.error('[请求超时]', originalRequest?.url)
            return Promise.reject(new Error('请求超时，请检查网络连接'))
        }
        
        // 处理网络错误
        if (!error.response) {
            console.error('[网络错误]', error.message)
            return Promise.reject(new Error('网络连接失败，请检查网络设置'))
        }
        
        // 处理HTTP错误
        const status = error.response.status
        let errorMessage = `服务器错误 (${status})`
        
        switch (status) {
            case 400:
                errorMessage = '请求参数错误'
                break
            case 401:
                errorMessage = '未授权，请重新登录'
                break
            case 403:
                errorMessage = '没有权限访问'
                break
            case 404:
                errorMessage = '请求的资源不存在'
                break
            case 500:
                errorMessage = '服务器内部错误'
                break
            case 502:
            case 503:
            case 504:
                errorMessage = '服务器暂时不可用'
                break
        }
        
        console.error(`[HTTP错误] ${status}`, error.response.data)
        return Promise.reject(new Error(errorMessage))
    }
)

/**
 * 文件信息接口
 */
export interface FileInfo {
    name: string
    size: number
    type: string
}

/**
 * 聊天请求参数
 */
export interface ChatRequest {
    message: string
    session_id?: string
    use_memory?: boolean
    files?: FileInfo[]
}

/**
 * 聊天响应数据
 */
export interface ChatResponse {
    reply: string
    session_id: string
    memory_added?: any[]
    memory_verification?: any
    tools_used?: string[]
    error?: string
}

/**
 * 发送聊天消息
 * 支持自动重试和错误处理
 * 
 * @param message - 用户消息内容
 * @param sessionId - 会话ID（可选）
 * @param useMemory - 是否使用记忆功能
 * @param files - 上传的文件列表
 * @returns Promise<ChatResponse> 聊天响应
 * 
 * @example
 * ```typescript
 * try {
 *   const response = await chat('你好', 'session-123');
 *   console.log('回复:', response.reply);
 * } catch (error) {
 *   console.error('发送失败:', error.message);
 * }
 * ```
 */
export async function chat(
    message: string, 
    sessionId?: string, 
    useMemory: boolean = true,
    files?: FileInfo[]
): Promise<ChatResponse> {
    // 参数验证
    if (!message || message.trim() === '') {
        throw new Error('消息内容不能为空')
    }
    
    if (message.length > 10000) {
        throw new Error('消息内容过长，最大支持10000字符')
    }
    
    // 构建请求数据
    const requestData: ChatRequest = {
        message: message.trim(),
        session_id: sessionId || undefined,
        use_memory: useMemory,
        files: files || undefined
    }
    
    console.log('[发送消息]', requestData)
    
    try {
        const response = await api.post<ChatResponse>('', requestData)
        if (!response.data || typeof response.data.reply !== 'string') {
            throw new Error('响应数据格式错误')
        }
        return response.data
    } catch (error) {
        if (axios.isAxiosError(error)) {
            throw error
        }
        if (error instanceof Error) {
            console.error('[聊天错误]', error.message)
            throw error
        }
        console.error('[聊天错误]', error)
        throw new Error('发送消息失败，请重试')
    }
}

/**
 * 获取API健康状态
 */
export async function checkHealth(): Promise<boolean> {
    try {
        const response = await api.get('/')
        return response.status === 200
    } catch (error) {
        console.error('[健康检查失败]', error)
        return false
    }
}

/**
 * 提交 clarify 问题的用户回答
 */
export async function submitClarifyAnswer(
    questionId: string,
    answer: string,
    sessionId?: string
): Promise<{ success: boolean; error?: string }> {
    try {
        const response = await api.post('/clarify', {
            question_id: questionId,
            answer,
            session_id: sessionId || undefined
        })
        return response.data
    } catch (error) {
        console.error('[提交回答失败]', error)
        if (axios.isAxiosError(error)) {
            return { success: false, error: error.message }
        }
        return { success: false, error: '提交回答失败' }
    }
}
