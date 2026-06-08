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
