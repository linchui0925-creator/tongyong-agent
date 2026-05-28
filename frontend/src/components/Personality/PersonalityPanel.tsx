/**
 * PersonalityPanel — Agent Personality & User Profile Editor
 * Edits Hermes MEMORY.md (agent personality) and USER.md (user profile) flat files.
 */
import { useState, useEffect, useCallback } from 'react'
import {
  getMemory,
  writeMemory,
  listMemoryEntries,
  addMemoryEntry,
  replaceMemoryEntry,
  deleteMemoryEntry,
  getUser,
  writeUser,
  listUserEntries,
  addUserEntry,
  replaceUserEntry,
  deleteUserEntry,
  getHermesStats,
  type MemoryFileData,
  type HermesStats,
} from '../../api/hermes'
import './PersonalityPanel.css'

type ProfileTab = 'agent' | 'user' | 'stats'

function PersonalityPanel() {
  const [tab, setTab] = useState<ProfileTab>('agent')
  const [showHelp, setShowHelp] = useState(false)

  return (
    <div className="personality-panel">
      <div className="personality-toolbar">
        <div className="personality-tabs">
          <button
            className={`personality-tab ${tab === 'agent' ? 'active' : ''}`}
            onClick={() => setTab('agent')}
          >
            Agent 人格
          </button>
          <button
            className={`personality-tab ${tab === 'user' ? 'active' : ''}`}
            onClick={() => setTab('user')}
          >
            用户画像
          </button>
          <button
            className={`personality-tab ${tab === 'stats' ? 'active' : ''}`}
            onClick={() => setTab('stats')}
          >
            统计
          </button>
        </div>
        <button className="btn btn-ghost" onClick={() => setShowHelp(!showHelp)} style={{ marginLeft: 'auto' }}>
          {showHelp ? '收起帮助' : '帮助'}
        </button>
      </div>

      {showHelp && (
        <div className="personality-help">
          <div className="personality-help-section">
            <strong>📋 什么是人格/用户画像？</strong>
            <p>Agent 人格定义了 AI 助手的性格、语气和行为准则；用户画像记录你的偏好、沟通风格和个人信息，让 Agent 更好地为你服务。</p>
          </div>
          <div className="personality-help-section">
            <strong>📖 使用说明</strong>
            <ul>
              <li><strong>Agent 人格</strong> — 添加描述来定义 Agent 的行为方式，如"你是一位专业的技术顾问"</li>
              <li><strong>用户画像</strong> — 添加关于你的信息，如语言偏好、专业领域、沟通风格等</li>
              <li><strong>编辑原文</strong> — 切换到原文编辑模式，直接编辑 Markdown 文件</li>
              <li><strong>统计</strong> — 查看 MEMORY.md 和 USER.md 的文件大小和条目数量</li>
              <li>每行文本为一条独立条目，可单独编辑或删除</li>
            </ul>
          </div>
        </div>
      )}

      <div className="personality-content">
        {tab === 'agent' && <MemoryEditor target="agent" />}
        {tab === 'user' && <MemoryEditor target="user" />}
        {tab === 'stats' && <StatsPanel />}
      </div>
    </div>
  )
}

// ── Shared Editor ──

interface EditorProps {
  target: 'agent' | 'user'
}

function MemoryEditor({ target }: EditorProps) {
  const [data, setData] = useState<MemoryFileData | null>(null)
  const [entries, setEntries] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [newEntry, setNewEntry] = useState('')
  const [editingIdx, setEditingIdx] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')
  const [showRaw, setShowRaw] = useState(false)
  const [rawContent, setRawContent] = useState('')

  const isAgent = target === 'agent'
  const label = isAgent ? 'Agent 人格' : '用户画像'
  const maxChars = isAgent ? 2200 : 1375

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [file, entryList] = await Promise.all([
        isAgent ? getMemory() : getUser(),
        isAgent ? listMemoryEntries() : listUserEntries(),
      ])
      setData(file)
      setEntries(entryList.entries || [])
    } catch (e: any) {
      setError(e.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [isAgent])

  useEffect(() => { load() }, [load])

  const handleAdd = async () => {
    const text = newEntry.trim()
    if (!text) return
    try {
      if (isAgent) {
        await addMemoryEntry(text)
      } else {
        await addUserEntry(text)
      }
      setNewEntry('')
      await load()
    } catch (e: any) {
      setError(e.message || '添加失败')
    }
  }

  const handleEdit = async (idx: number) => {
    const text = editValue.trim()
    if (!text || !data) return
    const oldEntry = entries[idx]
    try {
      if (isAgent) {
        await replaceMemoryEntry(oldEntry, text)
      } else {
        await replaceUserEntry(oldEntry, text)
      }
      setEditingIdx(null)
      setEditValue('')
      await load()
    } catch (e: any) {
      setError(e.message || '更新失败')
    }
  }

  const handleDelete = async (entry: string) => {
    try {
      if (isAgent) {
        await deleteMemoryEntry(entry)
      } else {
        await deleteUserEntry(entry)
      }
      await load()
    } catch (e: any) {
      setError(e.message || '删除失败')
    }
  }

  const handleSaveRaw = async () => {
    try {
      if (isAgent) {
        await writeMemory(rawContent)
      } else {
        await writeUser(rawContent)
      }
      setShowRaw(false)
      await load()
    } catch (e: any) {
      setError(e.message || '保存失败')
    }
  }

  const openRaw = () => {
    setRawContent(data?.content || '')
    setShowRaw(true)
  }

  if (loading) {
    return <div className="personality-loading">加载中...</div>
  }

  return (
    <div className="peditor">
      {error && (
        <div className="peditor-error">
          <span>{error}</span>
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      {/* Header */}
      <div className="peditor-header">
        <div className="peditor-title">
          <span>{label}</span>
          <span className="peditor-count">
            {entries.length} 条 · {data?.stats.char_count ?? 0}/{maxChars} 字符
          </span>
        </div>
        <div className="peditor-actions">
          <button className="btn btn-ghost" onClick={openRaw}>
            编辑原文
          </button>
          <button className="btn btn-ghost" onClick={load}>
            刷新
          </button>
        </div>
      </div>

      {/* Add form */}
      <div className="peditor-add">
        <input
          className="input"
          type="text"
          placeholder="添加新条目..."
          value={newEntry}
          onChange={(e) => setNewEntry(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
        />
        <button className="btn btn-primary" onClick={handleAdd} disabled={!newEntry.trim()}>
          添加
        </button>
      </div>

      {/* Entry list */}
      <div className="peditor-list">
        {entries.length === 0 ? (
          <div className="peditor-empty">
            {isAgent ? '暂无 Agent 人格设定，添加一条描述来定义 Agent 的行为方式。' : '暂无用户画像数据，添加用户偏好、沟通风格等信息。'}
          </div>
        ) : (
          entries.map((entry, idx) => (
            <div key={idx} className="peditor-item">
              {editingIdx === idx ? (
                <div className="peditor-edit">
                  <input
                    className="input"
                    type="text"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleEdit(idx)
                      if (e.key === 'Escape') setEditingIdx(null)
                    }}
                    autoFocus
                  />
                  <div className="peditor-edit-actions">
                    <button className="btn btn-primary" onClick={() => handleEdit(idx)}>保存</button>
                    <button className="btn btn-secondary" onClick={() => setEditingIdx(null)}>取消</button>
                  </div>
                </div>
              ) : (
                <>
                  <span className="peditor-item-text">{entry}</span>
                  <div className="peditor-item-actions">
                    <button
                      className="btn btn-ghost"
                      onClick={() => { setEditingIdx(idx); setEditValue(entry) }}
                      title="编辑"
                    >
                      ✎
                    </button>
                    <button
                      className="btn btn-ghost"
                      onClick={() => handleDelete(entry)}
                      title="删除"
                    >
                      ✕
                    </button>
                  </div>
                </>
              )}
            </div>
          ))
        )}
      </div>

      {/* Raw editor modal */}
      {showRaw && (
        <div className="modal-overlay" onClick={() => setShowRaw(false)}>
          <div className="modal-content peditor-raw-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-title">编辑原文 — {label}</div>
            <textarea
              className="input peditor-raw-textarea"
              value={rawContent}
              onChange={(e) => setRawContent(e.target.value)}
              rows={12}
            />
            <div className="peditor-raw-info">
              {rawContent.length}/{maxChars} 字符
            </div>
            <div className="modal-actions">
              <button className="btn btn-primary" onClick={handleSaveRaw}>保存</button>
              <button className="btn btn-secondary" onClick={() => setShowRaw(false)}>取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Stats Panel ──

function StatsPanel() {
  const [stats, setStats] = useState<HermesStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getHermesStats()
      .then(setStats)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="personality-loading">加载中...</div>
  if (!stats) return <div className="personality-loading">无法获取统计信息</div>

  const rows = [
    { label: 'MEMORY.md', entries: stats.memory.entry_count, chars: stats.memory.char_count, max: stats.memory.max_chars },
    { label: 'USER.md', entries: stats.user.entry_count, chars: stats.user.char_count, max: stats.user.max_chars },
  ]

  return (
    <div className="pstats">
      {rows.map((r) => (
        <div key={r.label} className="pstats-card">
          <div className="pstats-card-header">{r.label}</div>
          <div className="pstats-card-body">
            <div className="pstats-stat">
              <span className="pstats-stat-value">{r.entries}</span>
              <span className="pstats-stat-label">条目</span>
            </div>
            <div className="pstats-stat">
              <span className="pstats-stat-value">{r.chars}/{r.max}</span>
              <span className="pstats-stat-label">字符</span>
            </div>
            <div className="pstats-bar">
              <div
                className="pstats-bar-fill"
                style={{ width: `${Math.min((r.chars / r.max) * 100, 100)}%` }}
              />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default PersonalityPanel
