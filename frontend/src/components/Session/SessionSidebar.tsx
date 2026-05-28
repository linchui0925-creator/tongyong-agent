import { useState, useEffect } from 'react'
import { getSessions, createSession, deleteSession, updateSession } from '../../api/memory'
import type { Session } from '../../types'
import './SessionSidebar.css'

interface SessionSidebarProps {
  currentSessionId: string | null
  onSessionSelect: (sessionId: string) => void
}

function SessionSidebar({ currentSessionId, onSessionSelect }: SessionSidebarProps) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [showNewInput, setShowNewInput] = useState(false)
  const [newSessionName, setNewSessionName] = useState('')

  const loadSessions = async () => {
    try {
      setLoading(true)
      const list = await getSessions()
      setSessions(list)
    } catch (error) {
      console.error('加载会话失败:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadSessions()
  }, [])

  const handleCreate = async () => {
    if (!newSessionName.trim()) return
    try {
      const newSession = await createSession(newSessionName.trim())
      setSessions(prev => [newSession, ...prev])
      setNewSessionName('')
      setShowNewInput(false)
      onSessionSelect(newSession.id)
    } catch (error) {
      console.error('创建会话失败:', error)
    }
  }

  const handleDelete = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('确定要删除这个会话吗？')) return
    try {
      await deleteSession(sessionId)
      setSessions(prev => prev.filter(s => s.id !== sessionId))
      if (currentSessionId === sessionId) {
        onSessionSelect(sessions[0]?.id || '')
      }
    } catch (error) {
      console.error('删除会话失败:', error)
    }
  }

  const startEdit = (session: Session, e: React.MouseEvent) => {
    e.stopPropagation()
    setEditingId(session.id)
    setEditName(session.name)
  }

  const saveEdit = async () => {
    if (!editName.trim() || !editingId) return
    try {
      const updated = await updateSession(editingId, editName.trim())
      setSessions(prev => prev.map(s => s.id === editingId ? updated : s))
      setEditingId(null)
      setEditName('')
    } catch (error) {
      console.error('更新会话失败:', error)
    }
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditName('')
  }

  return (
    <div className="session-sidebar">
      <div className="session-header">
        <span className="session-header-title">会话</span>
        <button
          className="session-header-btn"
          onClick={() => setShowNewInput(true)}
          title="新建会话"
        >
          +
        </button>
      </div>

      {showNewInput && (
        <div className="session-create">
          <input
            type="text"
            value={newSessionName}
            onChange={(e) => setNewSessionName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleCreate()
              if (e.key === 'Escape') {
                setShowNewInput(false)
                setNewSessionName('')
              }
            }}
            placeholder="会话名称"
            autoFocus
          />
          <div className="session-create-actions">
            <button className="session-create-confirm" onClick={handleCreate}>创建</button>
            <button className="session-create-cancel" onClick={() => {
              setShowNewInput(false)
              setNewSessionName('')
            }}>取消</button>
          </div>
        </div>
      )}

      <div className="session-list">
        {loading ? (
          <div className="session-list-empty">加载中...</div>
        ) : sessions.length === 0 ? (
          <div className="session-list-empty">暂无会话</div>
        ) : (
          sessions.map(session => (
            <div
              key={session.id}
              className={`session-item ${currentSessionId === session.id ? 'active' : ''}`}
              onClick={() => {
                if (editingId !== session.id) onSessionSelect(session.id)
              }}
            >
              {editingId === session.id ? (
                <div className="session-edit">
                  <input
                    type="text"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') saveEdit()
                      if (e.key === 'Escape') cancelEdit()
                    }}
                    onClick={(e) => e.stopPropagation()}
                    autoFocus
                  />
                  <div className="session-edit-actions">
                    <button className="session-edit-confirm" onClick={saveEdit}>✓</button>
                    <button className="session-edit-cancel" onClick={cancelEdit}>✕</button>
                  </div>
                </div>
              ) : (
                <>
                  <span className="session-item-name">{session.name}</span>
                  <div className="session-actions">
                    <button onClick={(e) => startEdit(session, e)} title="重命名">✎</button>
                    <button className="session-action-delete" onClick={(e) => handleDelete(session.id, e)} title="删除">✕</button>
                  </div>
                </>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default SessionSidebar
