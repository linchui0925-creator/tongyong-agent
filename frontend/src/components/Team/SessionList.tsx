import { useState } from 'react'
import type { TeamSession } from '../../api/team'
import { C } from './constants'

// ── Inline SVG Icons ─────────────────────────────────────────
const Icons = {
  x: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  plus: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
}

export function SessionList({
  sessions, activeId, onSelect, onDelete, onCreate,
}: {
  sessions: TeamSession[]; activeId: string
  onSelect: (id: string) => void; onDelete: (id: string) => void
  onCreate: (name: string) => void
}) {
  const [newName, setNewName] = useState('')
  const [hovered, setHovered] = useState<string | null>(null)

  const handleCreate = () => {
    if (!newName.trim()) return
    onCreate(newName.trim())
    setNewName('')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          value={newName}
          onChange={e => setNewName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleCreate()}
          placeholder="新会话..."
          style={{
            flex: 1, padding: '7px 10px',
            border: `1px solid ${C.border}`, borderRadius: 8,
            background: C.card, color: C.text, fontSize: 13,
          }}
        />
        <button onClick={handleCreate} style={{
          background: C.accent, color: '#fff', border: 'none',
          borderRadius: 8, padding: '7px 12px', cursor: 'pointer',
          fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4,
        }}>
          {Icons.plus} 新建
        </button>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 180, overflowY: 'auto' }}>
        {sessions.map(s => (
          <div key={s.id}
            onClick={() => onSelect(s.id)}
            onMouseEnter={() => setHovered(s.id)}
            onMouseLeave={() => setHovered(null)}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '8px 10px', borderRadius: 8, cursor: 'pointer',
              background: activeId === s.id ? `${C.accent}22` : hovered === s.id ? `${C.accent}11` : 'transparent',
              border: activeId === s.id ? `1px solid ${C.accent}44` : '1px solid transparent',
              transition: 'all 0.15s',
            }}>
            <span style={{ fontSize: 13, color: activeId === s.id ? C.accent : '#fff', flex: 1, fontWeight: activeId === s.id ? 600 : 400 }}>
              {s.name}
            </span>
            <span style={{
              fontSize: 10, color: 'var(--text-tertiary)',
              background: 'var(--bg-hover)', borderRadius: 4, padding: '1px 5px',
            }}>
              {s.status === 'idle' ? '空闲' : s.status}
            </span>
            {hovered === s.id && (
              <button onClick={e => { e.stopPropagation(); onDelete(s.id) }} style={{
                background: 'transparent', border: 'none', color: '#EF4444',
                cursor: 'pointer', fontSize: 14, padding: 0, lineHeight: 1,
              }}>
                {Icons.x}
              </button>
            )}
          </div>
        ))}
        {sessions.length === 0 && (
          <div style={{ color: 'var(--text-tertiary)', fontSize: 12, textAlign: 'center', padding: 12 }}>
            暂无会话
          </div>
        )}
      </div>
    </div>
  )
}
