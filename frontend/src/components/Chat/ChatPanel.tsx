import { useState, useEffect, useRef } from 'react'
import { chat } from '../../api/chat'
import { getSessions, createSession } from '../../api/memory'
import './ChatPanel.css'

interface Message {
    role: string
    content: string
    timestamp?: number
}

interface ChatPanelProps {
    messages: Message[]
    onSendMessage: (message: string, reply: string) => void
    sessionId: string
    onSessionChange: (sessionId: string) => void
}

interface Session {
    id: string
    name: string
    created_at: string
    updated_at: string
}

// 默认头像配置
const DEFAULT_AVATARS: Record<'user' | 'assistant', string[]> = {
    user: [
        'https://api.dicebear.com/7.x/avataaars/svg?seed=user1',
        'https://api.dicebear.com/7.x/avataaars/svg?seed=user2',
        'https://api.dicebear.com/7.x/avataaars/svg?seed=user3',
        'https://api.dicebear.com/7.x/avataaars/svg?seed=user4',
        'https://api.dicebear.com/7.x/avataaars/svg?seed=user5',
    ],
    assistant: [
        '🤖', // 机器人emoji
        '🧠', // 大脑emoji
        '💡', // 灯泡emoji
        '🎯', // 靶心emoji
        '✨', // 闪亮emoji
    ]
}

function ChatPanel({ messages, onSendMessage, sessionId, onSessionChange }: ChatPanelProps) {
    const [inputMessage, setInputMessage] = useState('')
    const [isLoading, setIsLoading] = useState(false)
    const [sessions, setSessions] = useState<Session[]>([])
    const [showCreateSession, setShowCreateSession] = useState(false)
    const [newSessionName, setNewSessionName] = useState('')
    const [userAvatar, setUserAvatar] = useState(DEFAULT_AVATARS.user[0])
    const [assistantAvatar, setAssistantAvatar] = useState(DEFAULT_AVATARS.assistant[0])
    const [showAvatarMenu, setShowAvatarMenu] = useState<'user' | 'assistant' | null>(null)
    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    
    const messagesEndRef = useRef<HTMLDivElement>(null)
    const textareaRef = useRef<HTMLTextAreaElement>(null)

    // 自动滚动到最新消息
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [messages, isLoading])

    useEffect(() => {
        loadSessions()
    }, [])

    useEffect(() => {
        if (sessionId) {
            loadMessages(sessionId)
        }
    }, [sessionId])

    // 加载会话列表
    const loadSessions = async () => {
        try {
            const sessionList = await getSessions()
            setSessions(sessionList)
            if (sessionList.length > 0 && !sessionId) {
                onSessionChange(sessionList[0].id)
            }
        } catch (error) {
            console.error('加载会话失败', error)
            setErrorMessage('加载会话失败')
        }
    }

    const loadMessages = async (sid: string) => {
        console.log('会话已切换:', sid)
    }

    // 发送消息
    const handleSendMessage = async () => {
        if (!inputMessage.trim() || isLoading) return
        
        const messageToSend = inputMessage.trim()
        
        // ✅ 立即清空输入框
        setInputMessage('')
        setIsLoading(true)
        setErrorMessage(null)
        
        // 重置输入框高度
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto'
        }
        
        try {
            const result = await chat(messageToSend, sessionId || undefined)
            
            // ✅ 消息发送后立即更新聊天列表
            onSendMessage(messageToSend, result.reply || '智能体已收到消息')
            
        } catch (error) {
            console.error('发送消息失败', error)
            const errorMsg = error instanceof Error ? error.message : '发送消息失败，请重试'
            setErrorMessage(errorMsg)
            // 即使失败也要清空输入框
            onSendMessage(messageToSend, `❌ ${errorMsg}`)
        } finally {
            setIsLoading(false)
        }
    }

    const handleCreateSession = async () => {
        if (!newSessionName.trim()) return
        try {
            const session = await createSession(newSessionName)
            if (session) {
                onSessionChange(session.id)
                setNewSessionName('')
                setShowCreateSession(false)
                await loadSessions()
            }
        } catch (error) {
            console.error('创建会话失败', error)
        }
    }

    const handleKeyPress = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            handleSendMessage()
        }
    }

    // 自动调整输入框高度
    const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        setInputMessage(e.target.value)
        
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto'
            textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 150) + 'px'
        }
    }

    // 切换头像
    const handleAvatarChange = (role: 'user' | 'assistant', avatar: string) => {
        if (role === 'user') {
            setUserAvatar(avatar)
            localStorage.setItem('userAvatar', avatar)
        } else {
            setAssistantAvatar(avatar)
            localStorage.setItem('assistantAvatar', avatar)
        }
        setShowAvatarMenu(null)
    }

    // 初始化头像
    useEffect(() => {
        const savedUserAvatar = localStorage.getItem('userAvatar')
        const savedAssistantAvatar = localStorage.getItem('assistantAvatar')
        
        if (savedUserAvatar) {
            setUserAvatar(savedUserAvatar)
        }
        if (savedAssistantAvatar) {
            setAssistantAvatar(savedAssistantAvatar)
        }
    }, [])

    return (
        <div className="chat-panel">
            {/* 头部 */}
            <div className="chat-header">
                <div className="header-title">
                    <span className="ai-icon">🤖</span>
                    <h2>TongYong Agent</h2>
                </div>
                <div className="header-actions">
                    <select
                        value={sessionId}
                        onChange={(e) => onSessionChange(e.target.value)}
                        className="session-select"
                    >
                        {sessions.length === 0 && (
                            <option value="">暂无会话</option>
                        )}
                        {sessions.map(session => (
                            <option key={session.id} value={session.id}>
                                {session.name}
                            </option>
                        ))}
                    </select>
                    <button 
                        className="create-session-btn"
                        onClick={() => setShowCreateSession(!showCreateSession)}
                    >
                        + 新会话
                    </button>
                </div>
            </div>

            {/* 创建会话表单 */}
            {showCreateSession && (
                <div className="create-session-form">
                    <input
                        type="text"
                        placeholder="输入会话名称"
                        value={newSessionName}
                        onChange={(e) => setNewSessionName(e.target.value)}
                        onKeyPress={(e) => e.key === 'Enter' && handleCreateSession()}
                    />
                    <button onClick={handleCreateSession}>创建</button>
                    <button onClick={() => setShowCreateSession(false)}>取消</button>
                </div>
            )}

            {/* 错误提示 */}
            {errorMessage && (
                <div className="error-banner">
                    <span>⚠️ {errorMessage}</span>
                    <button onClick={() => setErrorMessage(null)}>×</button>
                </div>
            )}

            {/* 消息列表 */}
            <div className="chat-messages">
                {messages.length === 0 ? (
                    <div className="empty-chat">
                        <div className="empty-icon">💬</div>
                        <p>开始对话吧！</p>
                        <p className="hint">输入消息后按回车发送</p>
                    </div>
                ) : (
                    messages.map((msg, index) => (
                        <div 
                            key={index} 
                            className={`message message-${msg.role}`}
                        >
                            {/* 头像 */}
                            <div 
                                className="message-avatar"
                                onClick={() => setShowAvatarMenu(showAvatarMenu === msg.role ? null : msg.role as 'user' | 'assistant')}
                                title="点击更换头像"
                            >
                                {msg.role === 'user' ? (
                                    typeof userAvatar === 'string' && userAvatar.startsWith('http') ? (
                                        <img src={userAvatar} alt="用户头像" />
                                    ) : (
                                        <span className="avatar-emoji">{userAvatar}</span>
                                    )
                                ) : (
                                    <span className="avatar-emoji">{assistantAvatar}</span>
                                )}
                            </div>
                            
                            {/* 头像选择菜单 */}
                            {showAvatarMenu === msg.role && (
                                <div className="avatar-menu">
                                    <div className="avatar-menu-title">
                                        选择{msg.role === 'user' ? '用户' : 'AI'}头像
                                    </div>
                                    <div className="avatar-options">
                                        {DEFAULT_AVATARS[msg.role as keyof typeof DEFAULT_AVATARS].map((avatar: string, idx: number) => (
                                            <div 
                                                key={idx}
                                                className="avatar-option"
                                                onClick={() => handleAvatarChange(msg.role as 'user' | 'assistant', avatar)}
                                            >
                                                {msg.role === 'user' ? (
                                                    typeof avatar === 'string' && avatar.startsWith('http') ? (
                                                        <img src={avatar} alt="头像选项" />
                                                    ) : (
                                                        <span>{avatar}</span>
                                                    )
                                                ) : (
                                                    <span className="avatar-emoji">{avatar}</span>
                                                )}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                            
                            {/* 消息内容 */}
                            <div className="message-bubble">
                                <div className="message-content">
                                    {msg.content}
                                </div>
                                {msg.timestamp && (
                                    <div className="message-time">
                                        {new Date(msg.timestamp).toLocaleTimeString('zh-CN', {
                                            hour: '2-digit',
                                            minute: '2-digit'
                                        })}
                                    </div>
                                )}
                            </div>
                        </div>
                    ))
                )}
                
                {/* ✅ 优化加载状态 - 显示打字动画 */}
                {isLoading && (
                    <div className="message message-assistant">
                        <div className="message-avatar">
                            <span className="avatar-emoji">{assistantAvatar}</span>
                        </div>
                        <div className="message-bubble">
                            <div className="message-content loading">
                                <div className="typing-indicator">
                                    <span className="typing-dot"></span>
                                    <span className="typing-dot"></span>
                                    <span className="typing-dot"></span>
                                </div>
                                <span className="loading-text">思考中...</span>
                            </div>
                        </div>
                    </div>
                )}
                
                <div ref={messagesEndRef} />
            </div>

            {/* 输入区域 */}
            <div className="chat-input">
                <div className="input-wrapper">
                    <textarea
                        ref={textareaRef}
                        value={inputMessage}
                        onChange={handleInputChange}
                        onKeyPress={handleKeyPress}
                        placeholder="输入消息..."
                        rows={1}
                        disabled={isLoading}
                    />
                    <button 
                        className="send-btn"
                        onClick={handleSendMessage}
                        disabled={isLoading || !inputMessage.trim()}
                    >
                        {isLoading ? (
                            <span className="loading-spinner">⟳</span>
                        ) : (
                            <span>发送</span>
                        )}
                    </button>
                </div>
                <div className="input-hint">
                    按 Enter 发送，Shift + Enter 换行
                </div>
            </div>
        </div>
    )
}

export default ChatPanel
