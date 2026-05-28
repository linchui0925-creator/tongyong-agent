import React, { useState, useEffect, useCallback, useRef } from 'react'
import {
  getSessions, createSession, deleteSession, stopTeam,
  getRoles, createRole, deleteRole, updateRole,
  runTeamStream, getMessages, getRoleTemplates,
  type TeamSession, type TeamRole, type RoleTemplatesResponse,
} from '../../api/team'
import { C } from './constants'
import { MessageList } from './MessageList'
import { SessionList } from './SessionList'
import { RoleList } from './RoleList'
import { MarketPanel } from './MarketPanel'

// ── Icons ─────────────────────────────────────────
const Icons = {
  play: <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>,
  x: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
}

// ── Status Bar ─────────────────────────────────────────
function StatusBar({ status, currentRound, totalRounds, messageCount, lastError }: {
  status: string; currentRound: number; totalRounds: number; messageCount: number; lastError: string
}) {
  if (status === 'idle') return null
  if (status === 'running') return (
    <div style={{
      background: '#EFF6FF', border: '1px solid #93C5FD',
      borderRadius: 8, padding: '6px 14px', display: 'flex', alignItems: 'center', gap: 8,
      animation: 'slideDown 0.3s ease',
    }}>
      <div style={{
        width: 12, height: 12, borderRadius: '50%', background: C.running,
        animation: 'pulse 1s infinite',
      }} />
      <span style={{ fontSize: 12, color: '#1E40AF', fontWeight: 500 }}>
        🔄 第 {currentRound}/{totalRounds} 轮进行中 · {messageCount} 条消息
      </span>
    </div>
  )
  if (status === 'completed') return (
    <div style={{
      background: '#F0FDF4', border: '1px solid #86EFAC',
      borderRadius: 8, padding: '6px 14px', display: 'flex', alignItems: 'center', gap: 8,
      animation: 'slideDown 0.3s ease',
    }}>
      <span style={{ fontSize: 13, color: '#15803D', fontWeight: 600 }}>✅ 协作完成 · {messageCount} 条消息</span>
    </div>
  )
  if (status === 'error') return (
    <div style={{
      background: '#FEF2F2', border: '1px solid #FECACA',
      borderRadius: 8, padding: '6px 14px', animation: 'slideDown 0.3s ease',
    }}>
      <span style={{ fontSize: 12, color: '#991B1B' }}>❌ 错误: {lastError}</span>
    </div>
  )
  return null
}

// ── Mode Selector ─────────────────────────────────────────
function ModeSelector({ mode, onChange }: { mode: string; onChange: (m: string) => void }) {
  const opts = [
    { key: 'pipeline', label: '🔗 图路由', desc: '按连接图自动路由' },
    { key: 'debate', label: '🎭 辩论', desc: '双方交替发言' },
  ]
  return (
    <div style={{ display: 'flex', gap: 6 }}>
      {opts.map(o => (
        <button key={o.key} onClick={() => onChange(o.key)} style={{
          flex: 1, padding: '6px 8px', borderRadius: 8, cursor: 'pointer',
          fontSize: 12, fontWeight: 600, border: 'none',
          background: mode === o.key ? C.accent : '#FFFFFF18',
          color: mode === o.key ? '#fff' : '#A0674A',
          transition: 'all 0.15s',
        }}>
          <div>{o.label}</div>
          <div style={{ fontSize: 10, fontWeight: 400, opacity: 0.8, marginTop: 1 }}>{o.desc}</div>
        </button>
      ))}
    </div>
  )
}

// ── Main Component ─────────────────────────────────────────
export const TeamPanel: React.FC = () => {
  const [sessions, setSessions] = useState<TeamSession[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string>('')
  const [roles, setRoles] = useState<TeamRole[]>([])
  const [messages, setMessages] = useState<any[]>([])
  const [templates, setTemplates] = useState<RoleTemplatesResponse['templates']>({})
  const [idea, setIdea] = useState('')
  const [rounds, setRounds] = useState(5)
  const [timeout, setTimeout_] = useState(0)
  const [running, setRunning] = useState(false)
  const [loadingSessions, setLoadingSessions] = useState(true)
  const [currentRound, setCurrentRound] = useState(0)
  const [runStatus, setRunStatus] = useState<'idle' | 'running' | 'completed' | 'error'>('idle')
  const [lastError, setLastError] = useState('')
  const [sessionMode, setSessionMode] = useState('pipeline')
  const [configMode, setConfigMode] = useState('pipeline')
  const [sidebarTab, setSidebarTab] = useState<'sessions' | 'market'>('sessions')
  const cleanupRef = useRef<(() => void) | null>(null)
  const mountedRef = useRef(true)

  const loadSessions = useCallback(async () => {
    try {
      const data = await getSessions()
      setSessions(data)
      if (data.length > 0 && !activeSessionId) setActiveSessionId(data[0].id)
    } catch (e) { console.error('loadSessions failed:', e) }
    finally { setLoadingSessions(false) }
  }, [activeSessionId])

  useEffect(() => { loadSessions() }, [loadSessions])

  useEffect(() => {
    if (!activeSessionId) return
    getRoles(activeSessionId).then(setRoles).catch(console.error)
    getMessages(activeSessionId).then(setMessages).catch(console.error)
    const session = sessions.find(s => s.id === activeSessionId)
    const mode = session?.config?.mode as string | undefined
    const to = session?.config?.timeout as number | undefined
    if (mode) setSessionMode(mode)
    if (to) setTimeout_(to)
  }, [activeSessionId, sessions])

  useEffect(() => {
    getRoleTemplates().then(d => setTemplates(d.templates)).catch(console.error)
  }, [])

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false; cleanupRef.current?.(); cleanupRef.current = null }
  }, [])

  // Global animation styles (injected once)
  useEffect(() => {
    const id = 'team-panel-styles'
    if (document.getElementById(id)) return
    const style = document.createElement('style')
    style.id = id
    style.textContent = [
      '@keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }',
      '@keyframes slideDown { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }',
      '@keyframes bounce { 0%, 80%, 100% { transform: translateY(0); } 40% { transform: translateY(-6px); } }',
      '@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }',
      '@keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }',
    ].join('\n')
    document.head.appendChild(style)
    return () => style.remove()
  }, [])

  const handleCreateSession = async (name: string) => {
    try {
      const s = await createSession(name, { mode: configMode, timeout })
      setSessions(prev => [...prev, s])
      setActiveSessionId(s.id)
      setSessionMode(configMode)
    } catch (e) { console.error('createSession failed:', e) }
  }

  const handleDeleteSession = async (id: string) => {
    try {
      await deleteSession(id)
      setSessions(prev => prev.filter(s => s.id !== id))
      if (activeSessionId === id) {
        const remaining = sessions.find(s => s.id !== id)
        setActiveSessionId(remaining?.id || '')
      }
    } catch (e) { console.error('deleteSession failed:', e) }
  }

  const handleAddRole = async (role: Partial<TeamRole> & { name: string; template?: string }) => {
    if (!activeSessionId) return
    try { const r = await createRole(activeSessionId, role); setRoles(prev => [...prev, r]) }
    catch (e) { console.error('createRole failed:', e) }
  }

  const handleDeleteRole = async (name: string) => {
    if (!activeSessionId) return
    try { await deleteRole(activeSessionId, name); setRoles(prev => prev.filter(r => r.name !== name)) }
    catch (e) { console.error('deleteRole failed:', e) }
  }

  const handleUpdateRole = async (roleName: string, data: Partial<TeamRole> & { name: string }) => {
    if (!activeSessionId) return
    try { const updated = await updateRole(activeSessionId, roleName, data); setRoles(prev => prev.map(r => r.name === roleName ? updated : r)) }
    catch (e) { console.error('updateRole failed:', e) }
  }

  const handleStop = async () => {
    if (!activeSessionId) return
    setRunStatus('idle'); setRunning(false)
    try { await stopTeam(activeSessionId) } catch (e) { console.error('stopTeam failed:', e) }
    cleanupRef.current?.(); cleanupRef.current = null
  }

  const handleRun = async () => {
    if (!idea.trim() || !activeSessionId) return
    setRunning(true); setMessages([]); setCurrentRound(0); setRunStatus('running'); setLastError('')
    mountedRef.current = true
    try {
      let settled = false
      await new Promise<void>((resolve, reject) => {
        const cleanup = runTeamStream(
          activeSessionId,
          { idea: idea.trim(), n_round: rounds },
          (msg) => {
            if (!mountedRef.current) return
            setMessages(prev => [...prev, msg])
            const roundMatch = msg.content.match(/\[Round (\d+)\]/)
            if (roundMatch) setCurrentRound(parseInt(roundMatch[1]))
          },
          (totalRounds) => {
            if (settled || !mountedRef.current) return
            settled = true; setCurrentRound(totalRounds); setRunStatus('completed'); resolve()
          },
          (err) => {
            if (settled || !mountedRef.current) return
            settled = true; setRunStatus('error'); setLastError(err)
            console.error('runTeamStream error:', err); reject(new Error(err))
          },
        )
        cleanupRef.current = cleanup
      })
    } catch (e) {
      setRunStatus('error'); setLastError(String(e))
    } finally {
      setRunning(false); cleanupRef.current = null
    }
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      overflow: 'hidden', gap: 0, background: C.bg,
    }}>
      {/* Header */}
      <div style={{
        padding: '12px 20px',
        background: `linear-gradient(135deg, ${C.sidebarBg} 0%, #2A1F14 100%)`,
        display: 'flex', alignItems: 'center', gap: 10,
        borderBottom: `2px solid ${C.accent}`,
      }}>
        <div style={{ fontSize: 20 }}>🔥</div>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#fff' }}>Multi-Agent Team</div>
          <div style={{ fontSize: 11, color: '#A0674A' }}>智能协作 · 实时对话</div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 11, color: '#A0674A' }}>模式</span>
          <ModeSelector mode={configMode} onChange={setConfigMode} />
        </div>
      </div>

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* ── Left Sidebar ── */}
        <div style={{
          width: 264, flexShrink: 0, background: C.sidebarBg,
          display: 'flex', flexDirection: 'column', gap: 0, overflow: 'hidden',
        }}>
          <div style={{ display: 'flex', borderBottom: '1px solid #FFFFFF12' }}>
            {(['sessions', 'market'] as const).map(tab => (
              <button key={tab} onClick={() => setSidebarTab(tab)} style={{
                flex: 1, padding: '8px 0', cursor: 'pointer', fontSize: 11, fontWeight: 700,
                background: sidebarTab === tab ? '#2A1F14' : 'transparent',
                color: sidebarTab === tab ? '#D4A574' : '#A0674A',
                border: 'none', borderBottom: sidebarTab === tab ? `2px solid ${C.accent}` : '2px solid transparent',
                transition: 'all 0.15s', letterSpacing: 1, textTransform: 'uppercase',
              }}>
                {tab === 'sessions' ? '会话' : '市场'}
              </button>
            ))}
          </div>

          {sidebarTab === 'sessions' ? (
            <>
              <div style={{ padding: '12px 12px 8px' }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#A0674A', letterSpacing: 1, marginBottom: 8, textTransform: 'uppercase' }}>
                  会话
                </div>
                {loadingSessions ? (
                  <div style={{ color: '#A0674A', fontSize: 13, padding: 8 }}>加载中...</div>
                ) : (
                  <SessionList
                    sessions={sessions} activeId={activeSessionId}
                    onSelect={setActiveSessionId} onDelete={handleDeleteSession} onCreate={handleCreateSession}
                  />
                )}
              </div>
              <div style={{ height: 1, background: '#FFFFFF12', margin: '4px 12px' }} />
              {activeSessionId && (
                <div style={{ padding: '8px 12px', flex: 1, overflow: 'auto' }}>
                  <RoleList
                    roles={roles} templates={templates}
                    onAdd={handleAddRole} onDelete={handleDeleteRole} onUpdate={handleUpdateRole}
                  />
                </div>
              )}
            </>
          ) : (
            <div style={{ padding: '12px', flex: 1, overflow: 'auto' }}>
              <MarketPanel
                sessionId={activeSessionId}
                onImportSuccess={async () => {
                  if (activeSessionId) {
                    try { setRoles(await getRoles(activeSessionId)) } catch { /* ignore */ }
                  }
                }}
              />
            </div>
          )}
        </div>

        {/* ── Main Area ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: C.chatBg }}>
          {/* Task Input */}
          <div style={{
            background: '#fff', borderBottom: `1px solid ${C.border}`,
            padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10,
          }}>
            <StatusBar
              status={runStatus} currentRound={currentRound}
              totalRounds={rounds} messageCount={messages.length} lastError={lastError}
            />
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
              <textarea
                value={idea} onChange={e => setIdea(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !running) { e.preventDefault(); handleRun() } }}
                placeholder={`输入任务需求... (Enter 快捷执行，Shift+Enter 换行)\n模式: ${sessionMode === 'debate' ? '🎭 辩论' : '🔬 流水线'}`}
                rows={2}
                style={{
                  flex: 1, padding: '10px 14px',
                  border: `1.5px solid ${runStatus === 'running' ? C.sendBtn : C.border}`,
                  borderRadius: 12, background: '#fff', color: C.text, fontSize: 13, lineHeight: 1.6,
                  resize: 'none', fontFamily: 'inherit',
                  boxShadow: runStatus === 'running' ? `0 0 0 3px ${C.sendBtn}22` : 'none',
                  transition: 'border 0.2s, box-shadow 0.2s',
                }}
                disabled={!activeSessionId || roles.length === 0}
              />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {sessionMode === 'debate' ? (
                  <input type="number" value={rounds}
                    onChange={e => setRounds(Math.max(1, Math.min(50, parseInt(e.target.value) || 5)))}
                    min={1} max={50} title="轮数"
                    style={{
                      width: 56, padding: '8px 6px', textAlign: 'center',
                      border: `1px solid ${C.border}`, borderRadius: 8,
                      background: C.card, color: C.text, fontSize: 13,
                    }}
                  />
                ) : (
                  <input type="number" value={timeout}
                    onChange={e => setTimeout_(Math.max(0, parseInt(e.target.value) || 0))}
                    min={0} title="超时(秒,0=不限)" placeholder="超时"
                    style={{
                      width: 56, padding: '8px 6px', textAlign: 'center',
                      border: `1px solid ${C.border}`, borderRadius: 8,
                      background: C.card, color: C.text, fontSize: 11,
                    }}
                  />
                )}
                <button onClick={handleRun}
                  disabled={running || !activeSessionId || roles.length === 0 || !idea.trim()}
                  style={{
                    padding: '10px 16px', borderRadius: 10, cursor: running ? 'not-allowed' : 'pointer',
                    fontSize: 13, fontWeight: 700, border: 'none',
                    background: running ? '#9CA3AF' : C.sendBtn, color: '#fff',
                    display: 'flex', alignItems: 'center', gap: 6,
                    opacity: (!activeSessionId || roles.length === 0 || !idea.trim()) ? 0.5 : 1,
                    transition: 'all 0.2s',
                    boxShadow: running ? 'none' : `0 4px 12px ${C.sendBtn}44`,
                  }}
                >
                  {Icons.play} {running ? '运行中' : '执行'}
                </button>
                {running && (
                  <button onClick={handleStop} style={{
                    padding: '10px 16px', borderRadius: 10, cursor: 'pointer',
                    fontSize: 13, fontWeight: 700, border: 'none',
                    background: C.error, color: '#fff',
                    display: 'flex', alignItems: 'center', gap: 6,
                    boxShadow: `0 4px 12px ${C.error}44`,
                  }}>
                    {Icons.x} 终止
                  </button>
                )}
              </div>
            </div>
            {roles.length === 0 && activeSessionId && (
              <div style={{
                fontSize: 12, color: C.textMuted, background: C.amberBg,
                borderRadius: 6, padding: '5px 10px', border: `1px solid ${C.amber}33`,
              }}>
                💡 在左侧添加至少一个 Agent 后即可开始协作
              </div>
            )}
          </div>

          {/* Chat Messages */}
          <MessageList messages={messages} isRunning={running} />
        </div>
      </div>
    </div>
  )
}
