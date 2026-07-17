import { useState, useEffect } from 'react'
import type { TeamRole, RoleTemplatesResponse } from '../../api/team'
import { C, inputStyle } from './constants'

// ── Inline SVG Icons ─────────────────────────────────────────
const Icons = {
  x: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  plus: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  check: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20,6 9,17 4,12"/></svg>,
}

function Avatar({ name, size = 36, side }: { name: string; size?: number; side?: string }) {
  const n = (name || '').toLowerCase()
  let emoji = '🤖'
  if (n.includes('coder') || n.includes('程序')) emoji = '👨‍💻'
  else if (n.includes('tester') || n.includes('测试')) emoji = '🧪'
  else if (n.includes('reviewer') || n.includes('审查')) emoji = '🔍'
  else if (n.includes('debate')) emoji = '🎭'
  else if (side === 'positive') emoji = '🔵'
  else if (side === 'negative') emoji = '🔴'
  else if (side === 'judge') emoji = '⚖️'

  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: `linear-gradient(135deg, ${C.accent} 0%, #8B5E3C 100%)`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: size * 0.4, flexShrink: 0,
    }}>
      {emoji}{(name || '?')[0]?.toUpperCase() || '?'}
    </div>
  )
}

// ── Role Config Panel ─────────────────────────────────────────
function RoleConfigPanel({
  role, allRoles, onSave, onClose, sessionMode,
}: {
  role: TeamRole; allRoles: TeamRole[]
  onSave: (roleName: string, data: Partial<TeamRole> & { name: string }) => void
  onClose: () => void
  sessionMode?: string
}) {
  const [name, setName] = useState(role?.name || '')
  const [profile, setProfile] = useState(role?.profile || '')
  const [watchActions, setWatchActions] = useState((role?.watch_actions || []).join(', '))
  const [actionTypes, setActionTypes] = useState((role?.action_types || []).join(', '))
  const [upstream, setUpstream] = useState<string[]>(role?.upstream_roles || [])
  const [downstream, setDownstream] = useState<string[]>(role?.downstream_roles || [])
  const [llmProvider, setLlmProvider] = useState(role?.llm_provider || 'deepseek')
  const [llmModel, setLlmModel] = useState(role?.llm_model || '')
  // 辩论相关
  const [opponentName, setOpponentName] = useState(role?.opponent_name || '')
  const [stance, setStance] = useState(role?.stance || '')
  const [debateSide, setDebateSide] = useState(role?.debate_side || '')
  const [debatePosition, setDebatePosition] = useState(role?.debate_position || '')

  const others = allRoles.filter(r => r.name && r.name !== (role?.name || ''))
  const isDebateMode = sessionMode === 'debate'

  // 辩论模式：选择阵营/辩位时自动设置动作类型和监听动作
  useEffect(() => {
    if (isDebateMode && (debateSide || debatePosition)) {
      setWatchActions('UserRequirement, DebateSpeech')
      if (debateSide !== 'judge') {
        setActionTypes('debate_speech')
      } else {
        setActionTypes('debate_judge')
      }
    }
  }, [isDebateMode, debateSide, debatePosition])

  // Sync state when role prop changes (e.g., clicking different agent)
  useEffect(() => {
    setName(role?.name || '')
    setProfile(role?.profile || '')
    setWatchActions((role?.watch_actions || []).join(', '))
    setActionTypes((role?.action_types || []).join(', '))
    setUpstream(role?.upstream_roles || [])
    setDownstream(role?.downstream_roles || [])
    setLlmProvider(role?.llm_provider || 'deepseek')
    setLlmModel(role?.llm_model || '')
    setOpponentName(role?.opponent_name || '')
    setStance(role?.stance || '')
    setDebateSide(role?.debate_side || '')
    setDebatePosition(role?.debate_position || '')
  }, [role])

  const toggleUpstream = (n: string) => {
    setUpstream(prev => prev.includes(n) ? prev.filter(x => x !== n) : [...prev, n])
  }
  const toggleDownstream = (n: string) => {
    setDownstream(prev => prev.includes(n) ? prev.filter(x => x !== n) : [...prev, n])
  }

  const handleSave = () => {
    // 解析监听动作和动作类型为数组
    const parsedWatchActions = watchActions.split(',').map(s => s.trim()).filter(Boolean)
    const parsedActionTypes = actionTypes.split(',').map(s => s.trim()).filter(Boolean)

    // Use name state directly (not role.name) in case role changed during edit
    const roleName = name.trim() || role?.name || ''
    if (!roleName) return // Don't save if no name

    const data: Partial<TeamRole> & { name: string } = {
      name: roleName, profile,
      watch_actions: parsedWatchActions,
      action_types: parsedActionTypes,
      llm_provider: llmProvider, llm_model: llmModel,
    }
    if (isDebateMode) {
      // 辩论模式：保存辩论相关字段
      if (opponentName) data.opponent_name = opponentName
      if (stance) data.stance = stance
      if (debateSide) data.debate_side = debateSide
      if (debatePosition) data.debate_position = debatePosition
      // 辩论模式下自动设置监听动作和动作类型
      data.watch_actions = ['UserRequirement', 'DebateSpeech']
      data.action_types = debateSide === 'judge' ? ['debate_judge'] : ['debate_speech']
    } else {
      // 图路由模式：保存上下游关系
      data.upstream_roles = upstream
      data.downstream_roles = downstream
    }
    onSave(roleName, data)
  }

  return (
    <div style={{
      background: 'var(--bg-inset)', borderRadius: 10, padding: 16,
      border: `1px solid ${C.accent}44`,
      display: 'flex', flexDirection: 'column', gap: 10,
      animation: 'slideDown 0.2s ease',
      minWidth: 420,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <Avatar name={role?.name || ''} size={24} />
        <span style={{ fontSize: 13, fontWeight: 700, color: '#fff' }}>配置: {role?.name || ''}</span>
        <button onClick={onClose} style={{
          marginLeft: 'auto', background: 'transparent', border: 'none',
          color: 'var(--text-tertiary)', cursor: 'pointer', fontSize: 14, padding: '2px 6px',
        }}>
          {Icons.x}
        </button>
      </div>

      <input value={name} onChange={e => setName(e.target.value)} placeholder="名称" style={{ ...inputStyle }} />
      <textarea
        value={profile}
        onChange={e => setProfile(e.target.value)}
        placeholder="身份描述（system prompt）"
        rows={5}
        style={{
          ...inputStyle,
          minHeight: 100,
          resize: 'vertical',
          fontFamily: 'inherit',
          lineHeight: 1.5,
        }}
      />
      <div style={{ display: 'flex', gap: 6 }}>
        <input value={watchActions} onChange={e => setWatchActions(e.target.value)} placeholder="监听动作" style={{ ...inputStyle, flex: 1 }} />
        <input value={actionTypes} onChange={e => setActionTypes(e.target.value)} placeholder="动作类型" style={{ ...inputStyle, flex: 1 }} />
      </div>

      <div style={{ fontSize: 11, fontWeight: 600, color: '#86EFAC', marginBottom: 2 }}>LLM 配置</div>
      <div style={{ display: 'flex', gap: 6 }}>
        <select value={llmProvider} onChange={e => setLlmProvider(e.target.value)} style={{
          ...inputStyle, flex: 1, cursor: 'pointer', appearance: 'none', WebkitAppearance: 'none',
        }}>
          <option value="deepseek">DeepSeek</option>
          <option value="openai">OpenAI</option>
          <option value="tongyi">通义千问</option>
          <option value="anthropic">Anthropic</option>
          <option value="minimax">MiniMax</option>
        </select>
        <input value={llmModel} onChange={e => setLlmModel(e.target.value)} placeholder="模型（如 deepseek-v4-flash）" style={{ ...inputStyle, flex: 1 }} />
      </div>

      {isDebateMode ? (
        <>
          {/* 辩论模式：正方/反方 + 辩位选择 */}
          <div style={{ fontSize: 11, fontWeight: 600, color: '#FCD34D', marginBottom: 4 }}>🎭 辩论配置</div>
          <div style={{ display: 'flex', gap: 6 }}>
            <select value={debateSide} onChange={e => setDebateSide(e.target.value)} style={{
              ...inputStyle, flex: 1, cursor: 'pointer',
            }}>
              <option value="">选择阵营</option>
              <option value="positive">正方</option>
              <option value="negative">反方</option>
              <option value="judge">裁判</option>
            </select>
            <select value={debatePosition} onChange={e => setDebatePosition(e.target.value)} style={{
              ...inputStyle, flex: 1, cursor: 'pointer',
            }}>
              <option value="">选择辩位</option>
              <option value="first">一辩</option>
              <option value="second">二辩</option>
              <option value="third">三辩</option>
              <option value="fourth">四辩</option>
              <option value="judge">裁判</option>
            </select>
          </div>
          <input value={stance} onChange={e => setStance(e.target.value)}
            placeholder="立场描述（如：支持加速AI发展）" style={{ ...inputStyle }} />
          <div style={{ fontSize: 11, fontWeight: 600, color: '#86EFAC', marginBottom: 2 }}>⚔️ 对手</div>
          <select value={opponentName} onChange={e => setOpponentName(e.target.value)} style={{
            ...inputStyle, cursor: 'pointer',
          }}>
            <option value="">选择对手（自动设置）</option>
            {others.map(o => (
              <option key={o.name} value={o.name}>{o.name}</option>
            ))}
          </select>
        </>
      ) : (
        <>
          {/* 图路由模式：上下游关系 */}
          {/* Upstream */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#93C5FD', marginBottom: 4 }}>↑ 上游 Agent（数据/任务来源）</div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {others.length === 0 ? (
                <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>暂无其他 Agent</span>
              ) : (
                others.map(o => {
                  if (!o.name) return null
                  const isActive = upstream.includes(o.name)
                  return (
                    <label key={o.name} onClick={() => toggleUpstream(o.name)} style={{
                      display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer',
                      padding: '3px 8px', borderRadius: 6, fontSize: 11,
                      background: isActive ? '#3B82F644' : 'var(--border-light)',
                      color: isActive ? '#93C5FD' : 'var(--text-tertiary)',
                      border: `1px solid ${isActive ? '#3B82F666' : 'transparent'}`,
                      transition: 'all 0.1s',
                    }}>
                      <span style={{
                        width: 10, height: 10, borderRadius: 3, display: 'flex',
                        alignItems: 'center', justifyContent: 'center',
                        background: isActive ? '#3B82F6' : 'transparent',
                        border: `1px solid ${isActive ? '#3B82F6' : '#666'}`,
                        fontSize: 8, color: '#fff',
                      }}>
                        {isActive ? '✓' : ''}
                      </span>
                      {o.name}
                    </label>
                  )
                })
              )}
            </div>
          </div>

          {/* Downstream */}
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#FCD34D', marginBottom: 4 }}>↓ 下游 Agent（交付对象）</div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {others.length === 0 ? (
                <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>暂无其他 Agent</span>
              ) : (
                others.map(o => {
                  if (!o.name) return null
                  const isActive = downstream.includes(o.name)
                  return (
                    <label key={o.name} onClick={() => toggleDownstream(o.name)} style={{
                      display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer',
                      padding: '3px 8px', borderRadius: 6, fontSize: 11,
                      background: isActive ? '#F59E0B44' : 'var(--border-light)',
                      color: isActive ? '#FCD34D' : 'var(--text-tertiary)',
                      border: `1px solid ${isActive ? '#F59E0B66' : 'transparent'}`,
                      transition: 'all 0.1s',
                    }}>
                      <span style={{
                        width: 10, height: 10, borderRadius: 3, display: 'flex',
                        alignItems: 'center', justifyContent: 'center',
                        background: isActive ? '#F59E0B' : 'transparent',
                        border: `1px solid ${isActive ? '#F59E0B' : '#666'}`,
                        fontSize: 8, color: '#fff',
                      }}>
                        {isActive ? '✓' : ''}
                      </span>
                      {o.name}
                    </label>
                  )
                })
              )}
            </div>
          </div>
        </>
      )}

      <button onClick={handleSave} style={{
        background: C.accent, color: '#fff', border: 'none',
        borderRadius: 8, padding: '8px 0', cursor: 'pointer',
        fontSize: 13, fontWeight: 600, marginTop: 4,
      }}>
        {Icons.check} 保存配置
      </button>
    </div>
  )
}

// ── Role List ─────────────────────────────────────────
export function RoleList({
  roles, templates, onAdd, onDelete, onUpdate, sessionMode,
}: {
  roles: TeamRole[]; templates: RoleTemplatesResponse['templates']
  onAdd: (role: Partial<TeamRole> & { name: string; template?: string }) => void
  onDelete: (name: string) => void
  onUpdate: (roleName: string, data: Partial<TeamRole> & { name: string }) => void
  sessionMode?: string
}) {
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    name: '', profile: '', watch_actions: '', action_types: '', template: '',
  })
  const [hoveredRole, setHoveredRole] = useState<string | null>(null)
  const [configRole, setConfigRole] = useState<string | null>(null)

  const handleAdd = () => {
    if (!form.name.trim()) return
    onAdd({
      name: form.name.trim(), profile: form.profile,
      watch_actions: form.watch_actions.split(',').map(s => s.trim()).filter(Boolean),
      action_types: form.action_types.split(',').map(s => s.trim()).filter(Boolean),
      template: form.template || undefined,
    })
    setForm({ name: '', profile: '', watch_actions: '', action_types: '', template: '' })
    setShowForm(false)
  }

  const handleTemplate = (key: string) => {
    const t = templates[key]
    if (!t) return
    setForm(f => ({
      ...f, template: key, name: t.name || key, profile: t.profile,
      watch_actions: t.watch_actions?.join(', ') || '',
      action_types: t.action_types?.join(', ') || '',
    }))
  }

  const handleConfigSave = (roleName: string, data: Partial<TeamRole> & { name: string }) => {
    onUpdate(roleName, data)
    setConfigRole(null)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent)' }}>🤖 Agents</span>
        <button onClick={() => { setShowForm(v => !v); setConfigRole(null) }} style={{
          background: showForm ? '#FFFFFF22' : C.accent, color: '#fff',
          border: 'none', borderRadius: 6, padding: '3px 10px', cursor: 'pointer', fontSize: 12, fontWeight: 600,
        }}>
          {showForm ? '取消' : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>{Icons.plus} 添加</span>}
        </button>
      </div>

      {showForm && (
        <div style={{
          background: 'var(--bg-inset)', borderRadius: 10, padding: 12,
          display: 'flex', flexDirection: 'column', gap: 8,
          border: `1px solid ${C.accent}33`,
        }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {Object.keys(templates).map(k => (
              <button key={k} onClick={() => handleTemplate(k)} style={{
                background: form.template === k ? C.accent : 'var(--bg-hover)',
                color: '#fff', border: 'none', borderRadius: 6,
                padding: '3px 10px', cursor: 'pointer', fontSize: 12,
              }}>
                {k}
              </button>
            ))}
          </div>
          <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
            placeholder="Agent 名称" style={{ ...inputStyle }} />
          <input value={form.watch_actions} onChange={e => setForm(f => ({ ...f, watch_actions: e.target.value }))}
            placeholder="监听动作（如 UserRequirement）" style={{ ...inputStyle }} />
          <input value={form.action_types} onChange={e => setForm(f => ({ ...f, action_types: e.target.value }))}
            placeholder="动作类型（如 write_code）" style={{ ...inputStyle }} />
          <button onClick={handleAdd} style={{
            background: C.success, color: '#fff', border: 'none',
            borderRadius: 8, padding: '8px 0', cursor: 'pointer', fontSize: 13, fontWeight: 600,
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
          }}>
            {Icons.check} 确认添加
          </button>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {roles.map(r => (
          <div key={r.name}>
            <div
              onClick={() => { setConfigRole(configRole === r.name ? null : r.name); setShowForm(false) }}
              onMouseEnter={() => setHoveredRole(r.name)}
              onMouseLeave={() => setHoveredRole(null)}
              style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 10px', background: 'var(--bg-inset)',
                borderRadius: configRole === r.name ? '8px 8px 0 0' : 8,
                // W4-6 2026-06-09 修 React 警告: 别用 borderWidth + borderStyle 这种
                //   shorthand, 它跟 borderBottom* longhand 冲突, React 会算
                //   "updating a style property during rerender"。 拆成 4 longhand
                //   + 4 borderBottom longhand, transition 只盯 borderColor
                borderTopWidth: 1, borderTopStyle: 'solid',
                borderLeftWidth: 1, borderLeftStyle: 'solid',
                borderRightWidth: 1, borderRightStyle: 'solid',
                // active: 4 边都高亮; hover: 4 边浅色; inactive: 透明
                borderTopColor: configRole === r.name ? C.accent + '66' : hoveredRole === r.name ? C.accent + '44' : 'transparent',
                borderLeftColor: configRole === r.name ? C.accent + '66' : hoveredRole === r.name ? C.accent + '44' : 'transparent',
                borderRightColor: configRole === r.name ? C.accent + '66' : hoveredRole === r.name ? C.accent + '44' : 'transparent',
                borderBottomWidth: configRole === r.name ? 0 : 1,
                borderBottomStyle: configRole === r.name ? 'none' : 'solid',
                borderBottomColor: 'transparent',
                cursor: 'pointer', transition: 'borderColor 0.15s',
              }}>
              <Avatar name={(r as any).name || ''} size={28} side={r.debate_side} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#fff' }}>{r.name}</div>
                {sessionMode === 'debate' && r.debate_side ? (
                  <div style={{ display: 'flex', gap: 4, marginTop: 2, flexWrap: 'wrap' }}>
                    <span style={{
                      background: r.debate_side === 'positive' ? '#3B82F644' : r.debate_side === 'negative' ? '#EF444444' : '#9333EA44',
                      color: r.debate_side === 'positive' ? '#93C5FD' : r.debate_side === 'negative' ? '#FCA5A5' : '#C084FC',
                      borderRadius: 4, padding: '1px 5px', fontSize: 9,
                    }}>
                      {r.debate_side === 'positive' ? '正方' : r.debate_side === 'negative' ? '反方' : '裁判'}
                    </span>
                    {r.debate_position && r.debate_position !== 'judge' && (
                      <span style={{
                        background: '#FCD34D44', color: '#FCD34D',
                        borderRadius: 4, padding: '1px 5px', fontSize: 9,
                      }}>
                        {r.debate_position === 'first' ? '一辩' : r.debate_position === 'second' ? '二辩' : r.debate_position === 'third' ? '三辩' : '四辩'}
                      </span>
                    )}
                  </div>
                ) : (
                  <div style={{ fontSize: 10, color: 'var(--text-tertiary)', marginTop: 1 }}>
                    {(r.watch_actions || []).join(', ') || '无监听'}
                  </div>
                )}
                {(r.upstream_roles?.length > 0 || r.downstream_roles?.length > 0) && sessionMode !== 'debate' && (
                  <div style={{ display: 'flex', gap: 6, marginTop: 3, flexWrap: 'wrap' }}>
                    {r.upstream_roles?.map(u => (
                      <span key={u} style={{
                        background: '#3B82F633', color: '#93C5FD',
                        borderRadius: 4, padding: '1px 5px', fontSize: 9,
                      }}>↑ {u}</span>
                    ))}
                    {r.downstream_roles?.map(d => (
                      <span key={d} style={{
                        background: '#F59E0B33', color: '#FCD34D',
                        borderRadius: 4, padding: '1px 5px', fontSize: 9,
                      }}>↓ {d}</span>
                    ))}
                  </div>
                )}
              </div>
              <span style={{ fontSize: 10, color: C.textMuted }}>⚙</span>
              {hoveredRole === r.name && (
                <button onClick={e => { e.stopPropagation(); onDelete(r.name) }} style={{
                  background: 'transparent', border: 'none', color: '#EF4444',
                  cursor: 'pointer', fontSize: 14, padding: 0,
                }}>
                  {Icons.x}
                </button>
              )}
            </div>
            {configRole === r.name && (
              <RoleConfigPanel
                role={r} allRoles={roles}
                onSave={handleConfigSave} onClose={() => setConfigRole(null)}
                sessionMode={sessionMode}
              />
            )}
          </div>
        ))}
        {roles.length === 0 && !showForm && (
          <div style={{ color: 'var(--text-tertiary)', fontSize: 12, textAlign: 'center', padding: 8 }}>
            暂无 Agent
          </div>
        )}
      </div>
    </div>
  )
}
