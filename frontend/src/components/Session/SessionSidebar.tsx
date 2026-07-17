import { useState, useEffect, type MouseEvent } from 'react'
import { getSessions, deleteSession, updateSession } from '../../api/memory'
import type { Session } from '../../types'
import './SessionSidebar.css'

interface SessionSidebarProps {
  currentSessionId: string | null
  onSessionSelect: (sessionId: string) => void
  /** 默认折叠时展示的最近会话条数 */
  collapsedCount?: number
  /** 外部触发刷新的信号（值变化即重新拉取） */
  reloadSignal?: number
}

const PINNED_SESSION_STORAGE_KEY = 'tongyong-agent:pinned-sessions'

const IconClock = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 7v5l3 2" />
    <circle cx="12" cy="12" r="8" />
  </svg>
)

const IconPin = ({ pinned }: { pinned?: boolean }) => (
  <svg viewBox="0 0 24 24" aria-hidden="true" className={pinned ? 'is-pinned' : ''}>
    <path d="M14 3l7 7-3 1-3 5-2 2-1-1 2-2-5-3-1-3 5-3 1-3z" />
    <path d="M10 13 4 19" />
  </svg>
)

const IconEdit = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4 20h4l10.5-10.5a1.8 1.8 0 0 0 0-2.5l-1.5-1.5a1.8 1.8 0 0 0-2.5 0L4 16v4Z" />
    <path d="m13.5 6.5 4 4" />
  </svg>
)

const IconTrash = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M4 7h16" />
    <path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7" />
    <path d="M7 7l1 12h8l1-12" />
    <path d="M10 11v5" />
    <path d="M14 11v5" />
  </svg>
)

const IconCheck = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="m5 12 4 4 10-10" />
  </svg>
)

const IconClose = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="m6 6 12 12" />
    <path d="m18 6-12 12" />
  </svg>
)

function SessionSidebar({
  currentSessionId,
  onSessionSelect,
  collapsedCount = 5,
  reloadSignal = 0,
}: SessionSidebarProps) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [pinnedSessionIds, setPinnedSessionIds] = useState<string[]>([])

  const persistPinnedSessionIds = (next: string[]) => {
    setPinnedSessionIds(next)
    try {
      window.localStorage.setItem(PINNED_SESSION_STORAGE_KEY, JSON.stringify(next))
    } catch (error) {
      console.error('保存置顶会话失败:', error)
    }
  }

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
  }, [reloadSignal])

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(PINNED_SESSION_STORAGE_KEY)
      setPinnedSessionIds(raw ? JSON.parse(raw) : [])
    } catch {
      setPinnedSessionIds([])
    }
  }, [])

  const togglePin = (sessionId: string, e: MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation()
    const next = pinnedSessionIds.includes(sessionId)
      ? pinnedSessionIds.filter(id => id !== sessionId)
      : [sessionId, ...pinnedSessionIds]
    persistPinnedSessionIds(next)
  }

  const handleDelete = async (sessionId: string, e: MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation()
    if (!confirm('确定要删除这个会话吗？')) return
    // 乐观更新: 立即从列表移除, 不等接口往返, 避免"刷新后才消失"
    const prevSessions = sessions
    const remaining = prevSessions.filter(s => s.id !== sessionId)
    setSessions(remaining)
    if (currentSessionId === sessionId) {
      onSessionSelect(remaining[0]?.id || '')
    }
    try {
      await deleteSession(sessionId)
    } catch (error) {
      console.error('删除会话失败, 回滚:', error)
      setSessions(prevSessions)
    }
  }

  const startEdit = (session: Session, e: MouseEvent<HTMLButtonElement>) => {
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

  const sortedSessions = [...sessions].sort((a, b) => {
    const aPinned = pinnedSessionIds.includes(a.id)
    const bPinned = pinnedSessionIds.includes(b.id)
    if (aPinned !== bPinned) return aPinned ? -1 : 1
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  })
  const visible = expanded ? sortedSessions : sortedSessions.slice(0, collapsedCount)
  const hasMore = sortedSessions.length > collapsedCount

  return (
    <div className="session-sidebar">
      <div className="session-header">
        <div className="session-header-label">
          <IconClock />
          <span className="session-header-title">历史会话</span>
        </div>
      </div>

      <div className="session-list">
        {loading ? (
          <div className="session-list-empty">加载中...</div>
        ) : sessions.length === 0 ? (
          <div className="session-list-empty">暂无会话</div>
        ) : (
          <>
            {visible.map(session => {
              const isPinned = pinnedSessionIds.includes(session.id)
              return (
                <div
                  key={session.id}
                  className={`session-item cursor-target ${currentSessionId === session.id ? 'active' : ''}`}
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
                        <button className="session-edit-confirm" onClick={saveEdit} aria-label="保存">
                          <IconCheck />
                        </button>
                        <button className="session-edit-cancel" onClick={cancelEdit} aria-label="取消">
                          <IconClose />
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <span className="session-item-name">{session.name}</span>
                      <div className="session-actions">
                        <button className={isPinned ? 'is-pinned' : ''} onClick={(e) => togglePin(session.id, e)} title={isPinned ? '取消置顶' : '置顶'} aria-label={isPinned ? '取消置顶' : '置顶'}>
                          <IconPin pinned={isPinned} />
                        </button>
                        <button onClick={(e) => startEdit(session, e)} title="重命名" aria-label="重命名">
                          <IconEdit />
                        </button>
                        <button className="session-action-delete" onClick={(e) => handleDelete(session.id, e)} title="删除" aria-label="删除">
                          <IconTrash />
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )
            })}
            {hasMore && (
              <button
                className="session-expand-btn cursor-target session-expand-btn--below"
                onClick={() => setExpanded(v => !v)}
                aria-label={expanded ? '收起会话列表' : '展开会话列表'}
              >
                {expanded ? '收起显示' : '展开显示'}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default SessionSidebar
