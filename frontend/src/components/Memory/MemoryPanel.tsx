import { useState, useEffect } from 'react'
import {
  getSessions,
  getMemories,
  createSession,
  addMemory,
  updateMemory,
  deleteMemory,
  verifyMemoryLoading,
  getSettings,
  addSetting,
  updateSetting,
  deleteSetting,
} from '../../api/memory'
import './MemoryPanel.css'

interface Memory {
  id: string
  type: string
  content: string
  importance: number
  created_at: string
  updated_at?: string
  version?: number
}

interface Session {
  id: string
  name: string
  created_at: string
  updated_at: string
}

interface Setting {
  id: string
  session_id: string
  key: string
  value: string
  type: string
  created_at: string
  updated_at: string
}

interface MemoryPanelProps {
  currentSessionId: string
  onSessionChange: (sessionId: string) => void
  onRefreshSessions: () => void
}

function MemoryPanel({ currentSessionId, onSessionChange, onRefreshSessions }: MemoryPanelProps) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [currentSession, setCurrentSession] = useState<string>(currentSessionId || '')
  const [memories, setMemories] = useState<Memory[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [newSessionName, setNewSessionName] = useState('')
  const [showCreateSession, setShowCreateSession] = useState(false)
  const [newMemoryType, setNewMemoryType] = useState('操作习惯')
  const [newMemoryContent, setNewMemoryContent] = useState('')
  const [showAddMemory, setShowAddMemory] = useState(false)

  const [editingMemory, setEditingMemory] = useState<Memory | null>(null)
  const [editContent, setEditContent] = useState('')
  const [editImportance, setEditImportance] = useState(1)
  const [showEditModal, setShowEditModal] = useState(false)

  const [showSettings, setShowSettings] = useState(false)
  const [verificationStatus, setVerificationStatus] = useState<any>(null)

  const [settings, setSettings] = useState<Setting[]>([])
  const [newSettingKey, setNewSettingKey] = useState('')
  const [newSettingValue, setNewSettingValue] = useState('')
  const [editingSetting, setEditingSetting] = useState<Setting | null>(null)
  const [editSettingValue, setEditSettingValue] = useState('')
  const [showAddSetting, setShowAddSetting] = useState(false)
  const [showHelp, setShowHelp] = useState(false)

  useEffect(() => {
    if (showSettings && currentSession) {
      loadSettings(currentSession)
    }
  }, [showSettings, currentSession])

  useEffect(() => {
    try {
      loadSessions()
    } catch (e: any) {
      console.error('加载会话错误:', e)
      setSessions([])
      setError('加载会话失败: ' + (e?.message || '未知错误'))
    }
  }, [])

  useEffect(() => {
    try {
      if (currentSession) {
        loadMemories(currentSession)
      }
    } catch (e: any) {
      console.error('加载记忆错误:', e)
      setMemories([])
      setError('加载记忆失败: ' + (e?.message || '未知错误'))
    }
  }, [currentSession])

  useEffect(() => {
    if (currentSessionId && currentSessionId !== currentSession) {
      setCurrentSession(currentSessionId)
    }
  }, [currentSessionId])

  const loadSessions = async () => {
    try {
      const sessionList = await getSessions()
      setSessions(sessionList)
      if (sessionList.length > 0 && !currentSession && !currentSessionId) {
        setCurrentSession(sessionList[0].id)
        onSessionChange(sessionList[0].id)
      }
    } catch (error) {
      console.error('加载会话失败', error)
    } finally {
      setLoading(false)
    }
  }

  const loadMemories = async (sessionId: string) => {
    try {
      const memoryList = await getMemories(sessionId)
      setMemories(memoryList)
    } catch (error) {
      console.error('加载记忆失败', error)
    }
  }

  const handleCreateSession = async () => {
    if (!newSessionName.trim()) return
    try {
      const session = await createSession(newSessionName)
      if (session?.id) {
        setCurrentSession(session.id)
        onSessionChange(session.id)
      }
      setNewSessionName('')
      setShowCreateSession(false)
      await loadSessions()
      onRefreshSessions()
    } catch (error) {
      console.error('创建会话失败', error)
    }
  }

  const handleAddMemory = async () => {
    if (!newMemoryContent.trim() || !currentSession) return
    try {
      await addMemory(newMemoryType, newMemoryContent, 2, currentSession)
      setNewMemoryContent('')
      setShowAddMemory(false)
      await loadMemories(currentSession)
    } catch (error) {
      console.error('添加记忆失败', error)
    }
  }

  const handleEditMemory = (memory: Memory) => {
    setEditingMemory(memory)
    setEditContent(memory.content)
    setEditImportance(memory.importance)
    setShowEditModal(true)
  }

  const handleUpdateMemory = async () => {
    if (!editingMemory || !editContent.trim()) return
    try {
      await updateMemory(editingMemory.id, editContent, editImportance)
      setShowEditModal(false)
      setEditingMemory(null)
      await loadMemories(currentSession)
    } catch (error) {
      console.error('更新记忆失败', error)
    }
  }

  const handleDeleteMemory = async (memoryId: string) => {
    if (!confirm('确定要删除这条记忆吗？')) return
    try {
      await deleteMemory(memoryId)
      await loadMemories(currentSession)
    } catch (error) {
      console.error('删除记忆失败', error)
    }
  }

  const handleVerify = async () => {
    if (!currentSession) return
    try {
      const data = await verifyMemoryLoading(currentSession)
      setVerificationStatus(data)
    } catch (error) {
      console.error('验证失败', error)
    }
  }

  const loadSettings = async (sessionId: string) => {
    try {
      const data = await getSettings(sessionId)
      setSettings(data.settings || data || [])
    } catch (error) {
      console.error('加载设定失败', error)
    }
  }

  const handleAddSetting = async () => {
    if (!newSettingKey.trim() || !newSettingValue.trim() || !currentSession) return
    try {
      await addSetting(currentSession, newSettingKey.trim(), newSettingValue.trim())
      setNewSettingKey('')
      setNewSettingValue('')
      setShowAddSetting(false)
      await loadSettings(currentSession)
    } catch (error) {
      console.error('添加设定失败', error)
    }
  }

  const handleEditSetting = (setting: Setting) => {
    setEditingSetting(setting)
    setEditSettingValue(setting.value)
  }

  const handleUpdateSetting = async () => {
    if (!editingSetting || !editSettingValue.trim()) return
    try {
      await updateSetting(editingSetting.session_id, editingSetting.key, editSettingValue.trim())
      setEditingSetting(null)
      await loadSettings(editingSetting.session_id)
    } catch (error) {
      console.error('更新设定失败', error)
    }
  }

  const handleDeleteSetting = async (setting: Setting) => {
    if (!confirm(`确定要删除设定"${setting.key}"吗？`)) return
    try {
      await deleteSetting(setting.session_id, setting.key)
      await loadSettings(setting.session_id)
    } catch (error) {
      console.error('删除设定失败', error)
    }
  }

  const handleSessionChange = (sessionId: string) => {
    setCurrentSession(sessionId)
    onSessionChange(sessionId)
  }

  return (
    <div className="memory-panel">
      {error && (
        <div className="memory-error">{error}</div>
      )}

      {/* Toolbar */}
      <div className="memory-toolbar">
        <div className="memory-toolbar-left">
          <select
            value={currentSession}
            onChange={(e) => handleSessionChange(e.target.value)}
            className="memory-session-select"
          >
            {sessions.length === 0 ? (
              <option value="">暂无会话</option>
            ) : (
              sessions.map(session => (
                <option key={session.id} value={session.id}>
                  {session.name}
                </option>
              ))
            )}
          </select>
        </div>
        <div className="memory-toolbar-actions">
          <button className="btn btn-ghost" onClick={() => setShowHelp(!showHelp)}>
            {showHelp ? '收起帮助' : '帮助'}
          </button>
          <button className="btn btn-ghost" onClick={() => setShowAddMemory(true)}>添加记忆</button>
          <button className="btn btn-ghost" onClick={() => setShowCreateSession(true)}>新建会话</button>
          <button className="btn btn-ghost" onClick={handleVerify}>验证</button>
          <button
            className={`btn ${showSettings ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setShowSettings(!showSettings)}
          >
            设定
          </button>
        </div>
      </div>

      {/* Help */}
      {showHelp && (
        <div className="memory-help">
          <div className="memory-help-section">
            <strong>📋 什么是记忆？</strong>
            <p>记忆模块用于管理 Agent 的学习记录，包含操作习惯、分析结论和关键决策三种类型。这些记忆会被 Agent 在对话中自动检索和使用。</p>
          </div>
          <div className="memory-help-section">
            <strong>📖 使用说明</strong>
            <ul>
              <li><strong>添加记忆</strong> — 选择类型（操作习惯/分析结论/关键决策），输入内容后保存</li>
              <li><strong>编辑/删除</strong> — 每条记忆卡片上都有编辑和删除按钮</li>
              <li><strong>会话管理</strong> — 下拉切换会话，点击"新建会话"创建新的对话空间</li>
              <li><strong>设定</strong> — 为当前会话设置 key-value 配置项，用于定制 Agent 行为</li>
              <li><strong>验证</strong> — 检查当前会话的记忆加载状态</li>
            </ul>
          </div>
        </div>
      )}

      {/* Create session form */}
      {showCreateSession && (
        <div className="memory-inline-form">
          <input
            className="input"
            type="text"
            placeholder="会话名称"
            value={newSessionName}
            onChange={(e) => setNewSessionName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCreateSession()}
          />
          <div className="memory-inline-form-actions">
            <button className="btn btn-primary" onClick={handleCreateSession}>创建</button>
            <button className="btn btn-secondary" onClick={() => setShowCreateSession(false)}>取消</button>
          </div>
        </div>
      )}

      {/* Add memory form */}
      {showAddMemory && (
        <div className="memory-inline-form">
          <div className="memory-inline-form-row">
            <select
              className="input"
              value={newMemoryType}
              onChange={(e) => setNewMemoryType(e.target.value)}
              style={{ width: 'auto' }}
            >
              <option value="操作习惯">操作习惯</option>
              <option value="分析结论">分析结论</option>
              <option value="关键决策">关键决策</option>
            </select>
            <input
              className="input"
              type="text"
              placeholder="记忆内容"
              value={newMemoryContent}
              onChange={(e) => setNewMemoryContent(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAddMemory()}
            />
          </div>
          <div className="memory-inline-form-actions">
            <button className="btn btn-primary" onClick={handleAddMemory}>添加</button>
            <button className="btn btn-secondary" onClick={() => setShowAddMemory(false)}>取消</button>
          </div>
        </div>
      )}

      {/* Settings panel */}
      {showSettings && (
        <div className="memory-settings">
          <div className="memory-settings-header">
            <span className="memory-settings-title">会话设定</span>
            <button
              className="btn btn-ghost"
              onClick={() => setShowAddSetting(!showAddSetting)}
            >
              {showAddSetting ? '关闭' : '+ 添加'}
            </button>
          </div>

          {showAddSetting && (
            <div className="memory-inline-form">
              <input
                className="input"
                type="text"
                placeholder="设定名称"
                value={newSettingKey}
                onChange={(e) => setNewSettingKey(e.target.value)}
              />
              <input
                className="input"
                type="text"
                placeholder="设定值"
                value={newSettingValue}
                onChange={(e) => setNewSettingValue(e.target.value)}
              />
              <div className="memory-inline-form-actions">
                <button className="btn btn-primary" onClick={handleAddSetting}>添加</button>
                <button className="btn btn-secondary" onClick={() => setShowAddSetting(false)}>取消</button>
              </div>
            </div>
          )}

          {editingSetting && (
            <div className="memory-inline-form">
              <span className="memory-edit-label">编辑: {editingSetting.key}</span>
              <input
                className="input"
                type="text"
                value={editSettingValue}
                onChange={(e) => setEditSettingValue(e.target.value)}
              />
              <div className="memory-inline-form-actions">
                <button className="btn btn-primary" onClick={handleUpdateSetting}>保存</button>
                <button className="btn btn-secondary" onClick={() => setEditingSetting(null)}>取消</button>
              </div>
            </div>
          )}

          <div className="memory-settings-list">
            {settings.length === 0 ? (
              <div className="memory-settings-empty">暂无设定</div>
            ) : (
              settings.map(setting => (
                <div key={setting.id} className="memory-setting-item">
                  <div className="memory-setting-info">
                    <span className="memory-setting-key">{setting.key}</span>
                    <span className="memory-setting-value">{setting.value}</span>
                  </div>
                  <div className="memory-setting-actions">
                    <button className="btn btn-ghost" onClick={() => handleEditSetting(setting)}>编辑</button>
                    <button className="btn btn-ghost" onClick={() => handleDeleteSetting(setting)}>删除</button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Memory list */}
      <div className="memory-list">
        {loading ? (
          <div className="memory-empty">加载中...</div>
        ) : memories.length === 0 ? (
          <div className="memory-empty">暂无记忆</div>
        ) : (
          memories.map(memory => (
            <div key={memory.id} className="memory-item">
              <div className="memory-item-top">
                <span className={`memory-item-type memory-type--${memory.type}`}>{memory.type}</span>
                <span className="memory-item-importance">
                  {'★'.repeat(Math.min(memory.importance, 5))}
                </span>
                {memory.version && memory.version > 1 && (
                  <span className="memory-item-version">v{memory.version}</span>
                )}
              </div>
              <div className="memory-item-content">{memory.content}</div>
              <div className="memory-item-bottom">
                <span className="memory-item-time">
                  {new Date(memory.created_at).toLocaleString('zh-CN')}
                  {memory.updated_at && memory.updated_at !== memory.created_at && (
                    <span className="memory-item-updated">
                      （更新: {new Date(memory.updated_at).toLocaleString('zh-CN')}）
                    </span>
                  )}
                </span>
                <div className="memory-item-actions">
                  <button className="btn btn-ghost" onClick={() => handleEditMemory(memory)}>编辑</button>
                  <button className="btn btn-ghost" onClick={() => handleDeleteMemory(memory.id)}>删除</button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Verification result */}
      {verificationStatus && (
        <div className="memory-verify-result">
          <span className="memory-verify-close" onClick={() => setVerificationStatus(null)}>×</span>
          <div className="memory-verify-title">验证结果</div>
          <div className="memory-verify-row">
            <span>永久设定</span><span>{verificationStatus.settings?.length || 0}</span>
          </div>
          <div className="memory-verify-row">
            <span>操作习惯</span><span>{verificationStatus.operation_habits?.length || 0}</span>
          </div>
          <div className="memory-verify-row">
            <span>分析结论</span><span>{verificationStatus.conclusions?.length || 0}</span>
          </div>
          <div className="memory-verify-row">
            <span>关键决策</span><span>{verificationStatus.decisions?.length || 0}</span>
          </div>
        </div>
      )}

      {/* Edit modal */}
      {showEditModal && editingMemory && (
        <div className="modal-overlay" onClick={() => setShowEditModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">编辑记忆</div>
            <div className="modal-body">
              <div className="modal-field">
                <label>类型</label>
                <span className="modal-field-value">{editingMemory.type}</span>
              </div>
              <div className="modal-field">
                <label>内容</label>
                <textarea
                  className="input"
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  rows={4}
                />
              </div>
              <div className="modal-field">
                <label>重要性</label>
                <select
                  className="input"
                  value={editImportance}
                  onChange={(e) => setEditImportance(Number(e.target.value))}
                  style={{ width: 'auto' }}
                >
                  <option value={1}>1 - 低</option>
                  <option value={2}>2 - 中</option>
                  <option value={3}>3 - 高</option>
                  <option value={4}>4 - 很高</option>
                  <option value={5}>5 - 极高</option>
                </select>
              </div>
            </div>
            <div className="modal-actions">
              <button className="btn btn-primary" onClick={handleUpdateMemory}>保存</button>
              <button className="btn btn-secondary" onClick={() => setShowEditModal(false)}>取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default MemoryPanel
