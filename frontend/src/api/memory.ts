/**
 * 记忆管理API模块
 * 提供会话、记忆和设定的CRUD操作
 */
import axios, { AxiosInstance, AxiosError } from 'axios'

// API配置
const API_BASE_URL = '/api/memory'
const REQUEST_TIMEOUT = 15000  // 15秒超时

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
        console.log(`[Memory API] ${config.method?.toUpperCase()} ${config.url}`)
        return config
    },
    (error) => {
        console.error('[请求错误]', error)
        return Promise.reject(error)
    }
)

// 响应拦截器
api.interceptors.response.use(
    (response) => response,
    async (error: AxiosError) => {
        // 统一错误处理
        let message = '请求失败'
        
        if (error.code === 'ECONNABORTED') {
            message = '请求超时'
        } else if (!error.response) {
            message = '网络连接失败'
        } else {
            switch (error.response.status) {
                case 404:
                    message = '资源不存在'
                    break
                case 500:
                    message = '服务器错误'
                    break
            }
        }
        
        console.error('[Memory API错误]', message, error)
        return Promise.reject(new Error(message))
    }
)

/**
 * 创建新会话
 */
export async function createSession(name: string) {
    if (!name || name.trim() === '') {
        throw new Error('会话名称不能为空')
    }
    
    const response = await api.post('/create', { name: name.trim() })
    return response.data.session || response.data
}

/**
 * 获取所有会话列表
 */
export async function getSessions() {
    const response = await api.get('/sessions')
    return response.data.sessions || []
}

/**
 * 获取指定会话的记忆
 */
export async function getMemories(sessionId: string) {
    if (!sessionId) {
        throw new Error('会话ID不能为空')
    }

    const response = await api.get(`/${sessionId}`)
    const data = response.data
    return data.memories || data
}

/**
 * 搜索记忆
 */
export async function searchMemories(query: string, k: number = 10, sessionId?: string) {
    const response = await api.post('/search', { 
        query, 
        k, 
        session_id: sessionId 
    })
    return response.data
}

/**
 * 添加记忆
 */
export async function addMemory(
    type: string, 
    content: string, 
    importance: number = 1, 
    sessionId?: string
) {
    if (!content || content.trim() === '') {
        throw new Error('记忆内容不能为空')
    }
    
    const response = await api.post('/add', { 
        type, 
        content: content.trim(), 
        importance, 
        session_id: sessionId 
    })
    return response.data
}

/**
 * 更新记忆
 */
export async function updateMemory(memoryId: string, content: string, importance?: number) {
    const response = await api.put(`/update/${memoryId}`, { 
        content, 
        importance 
    })
    return response.data
}

/**
 * 删除记忆
 */
export async function deleteMemory(memoryId: string) {
    const response = await api.delete(`/delete/${memoryId}`)
    return response.data
}

/**
 * 获取记忆版本历史
 */
export async function getMemoryVersions(memoryId: string) {
    const response = await api.get(`/versions/${memoryId}`)
    return response.data
}

/**
 * 验证记忆加载情况
 */
export async function verifyMemoryLoading(sessionId: string) {
    const response = await api.get(`/verify/${sessionId}`)
    return response.data
}

/**
 * 添加会话设定
 */
export async function addSetting(
    sessionId: string, 
    key: string, 
    value: string, 
    type: string = 'string'
) {
    const response = await api.post('/settings/add', { 
        key, 
        value, 
        type 
    }, {
        params: { session_id: sessionId }
    })
    return response.data
}

/**
 * 获取会话所有设定
 */
export async function getSettings(sessionId: string) {
    const response = await api.get(`/settings/${sessionId}`)
    return response.data
}

/**
 * 获取单个设定
 */
export async function getSetting(sessionId: string, key: string) {
    const response = await api.get(`/settings/${sessionId}/${key}`)
    return response.data
}

/**
 * 更新设定
 */
export async function updateSetting(sessionId: string, key: string, value: string) {
    const response = await api.put(`/settings/${sessionId}/${key}`, { value })
    return response.data
}

/**
 * 删除设定
 */
export async function deleteSetting(sessionId: string, key: string) {
    const response = await api.delete(`/settings/${sessionId}/${key}`)
    return response.data
}

/**
 * 健康检查
 */
export async function checkHealth() {
    try {
        const response = await api.get('/health')
        return response.data
    } catch (error) {
        console.error('[Memory健康检查失败]', error)
        return { status: 'error', error: String(error) }
    }
}

/**
 * 获取指定会话的所有消息
 */
export async function getSessionMessages(sessionId: string) {
    if (!sessionId) {
        throw new Error('会话ID不能为空')
    }
    
    const response = await api.get(`/messages/${sessionId}`)
    return response.data
}

/**
 * 更新会话名称
 */
export async function updateSession(sessionId: string, name: string) {
    if (!sessionId) {
        throw new Error('会话ID不能为空')
    }
    
    const response = await api.put(`/session/${sessionId}`, { name: name.trim() })
    return response.data
}

/**
 * 删除会话
 */
export async function deleteSession(sessionId: string) {
    if (!sessionId) {
        throw new Error('会话ID不能为空')
    }
    
    const response = await api.delete(`/session/${sessionId}`)
    return response.data
}
