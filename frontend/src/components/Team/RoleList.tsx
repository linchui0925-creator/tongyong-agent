import { useState } from 'react'
import type { TeamRole, RoleTemplatesResponse } from '../../api/team'
import { C, inputStyle } from './constants'

// ── Inline SVG Icons ─────────────────────────────────────────
const Icons = {
  x: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  plus: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  check: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20,6 9,17 4,12"/></svg>,
}

function Avatar({ name, size = 36 }: { name: string; size?: number }) {
  const n = name.toLowerCase()
  let emoji = '🤖'
  if (n.includes('coder') || n.includes('程序')) emoji = '👨‍💻'
  else if (n.includes('tester') || n.includes('测试')) emoji = '🧪'
  else if (n.includes('reviewer') || n.includes('审查')) emoji = '🔍'
  else if (n.includes('debate')) emoji = '🎭'

  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: `linear-gradient(135deg, ${C.accent} 0%, #8B5E3C 100%)`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: size * 0.4, flexShrink: 0,
    }}>
      {emoji}{name[0]?.toUpperCase()}
    </div>
  )
}

// ── Role Config Panel ─────────────────────────────────────────
function RoleConfigPanel({
  role, allRoles, onSave, onClose,
}: {
  role: TeamRole; allRoles: TeamRole[]
  onSave: (roleName: string, data: Partial<TeamRole> & { name: string }) => void
  onClose: () => void
}) {
  const [name, setName] = useState(role.name)
  const [profile, setProfile] = useState(role.profile || '')
  const [watchActions, setWatchActions] = useState(role.watch_actions.join(', '))
  const [actionTypes, setActionTypes] = useState(role.action_types.join(', '))
  const [upstream, setUpstream] = useState<string[]>(role.upstream_roles || [])
  const [downstream, setDownstream] = useState<string[]>(role.downstream_roles || [])
  const [llmProvider, setLlmProvider] = useState(role.llm_provider || 'deepseek')
  const [llmModel, setLlmModel] = useState(role.llm_model || '')

  const others = allRoles.filter(r => r.name !== role.name)

  const toggleUpstream = (n: string) => {
    setUpstream(prev => prev.includes(n) ? prev.filter(x => x !== n) : [...prev, n])
  }
  const toggleDownstream = (n: string) => {
    setDownstream(prev => prev.includes(n) ? prev.filter(x => x !== n) : [...prev, n])
  }

  const handleSave = () => {
    onSave(role.name, {
      name: name.trim(), profile,
      watch_actions: watchActions.split(',').map(s => s.trim()).filter(Boolean),
      action_types: actionTypes.split(',').map(s => s.trim()).filter(Boolean),
      upstream_roles: upstream, downstream_roles: downstream,
      llm_provider: llmProvider, llm_model: llmModel,
    })
  }

  return (
    <div style={{
      background: '#1E140D', borderRadius: 10, padding: 12,
      border: `1px solid ${C.accent}44`,
      display: 'flex', flexDirection: 'column', gap: 8,
      animation: 'slideDown 0.2s ease',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <Avatar name={role.name} size={24} />
        <span style={{ fontSize: 13, fontWeight: 700, color: '#fff' }}>配置: {role.name}</span>
        <button onClick={onClose} style={{
          marginLeft: 'auto', background: 'transparent', border: 'none',
          color: '#A0674A', cursor: 'pointer', fontSize: 14, padding: '2px 6px',
        }}>
          {Icons.x}
        </button>
      </div>

      <input value={name} onChange={e => setName(e.target.value)} placeholder="名称" style={{ ...inputStyle }} />
      <input value={profile} onChange={e => setProfile(e.target.value)} placeholder="身份描述（system prompt）" style={{ ...inputStyle }} />
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

      {/* Upstream */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: '#93C5FD', marginBottom: 4 }}>↑ 上游 Agent（数据/任务来源）</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {others.length === 0 ? (
            <span style={{ fontSize: 10, color: '#A0674A' }}>暂无其他 Agent</span>
          ) : others.map(o => (
            <label key={o.name} onClick={() => toggleUpstream(o.name)} style={{
              display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer',
              padding: '3px 8px', borderRadius: 6, fontSize: 11,
              background: upstream.includes(o.name) ? '#3B82F644' : '#FFFFFF12',
              color: upstream.includes(o.name) ? '#93C5FD' : '#A0674A',
              border: `1px solid ${upstream.includes(o.name) ? '#3B82F666' : 'transparent'}`,
              transition: 'all 0.1s',
            }}>
              <span style={{
                width: 10, height: 10, borderRadius: 3, display: 'flex',
                alignItems: 'center', justifyContent: 'center',
                background: upstream.includes(o.name) ? '#3B82F6' : 'transparent',
                border: `1px solid ${upstream.includes(o.name) ? '#3B82F6' : '#666'}`,
                fontSize: 8, color: '#fff',
              }}>
                {upstream.includes(o.name) ? '✓' : ''}
              </span>
              {o.name}
            </label>
          ))}
        </div>
      </div>

      {/* Downstream */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: '#FCD34D', marginBottom: 4 }}>↓ 下游 Agent（交付对象）</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {others.length === 0 ? (
            <span style={{ fontSize: 10, color: '#A0674A' }}>暂无其他 Agent</span>
          ) : others.map(o => (
            <label key={o.name} onClick={() => toggleDownstream(o.name)} style={{
              display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer',
              padding: '3px 8px', borderRadius: 6, fontSize: 11,
              background: downstream.includes(o.name) ? '#F59E0B44' : '#FFFFFF12',
              color: downstream.includes(o.name) ? '#FCD34D' : '#A0674A',
              border: `1px solid ${downstream.includes(o.name) ? '#F59E0B66' : 'transparent'}`,
              transition: 'all 0.1s',
            }}>
              <span style={{
                width: 10, height: 10, borderRadius: 3, display: 'flex',
                alignItems: 'center', justifyContent: 'center',
                background: downstream.includes(o.name) ? '#F59E0B' : 'transparent',
                border: `1px solid ${downstream.includes(o.name) ? '#F59E0B' : '#666'}`,
                fontSize: 8, color: '#fff',
              }}>
                {downstream.includes(o.name) ? '✓' : ''}
              </span>
              {o.name}
            </label>
          ))}
        </div>
      </div>

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
  roles, templates, onAdd, onDelete, onUpdate,
}: {
  roles: TeamRole[]; templates: RoleTemplatesResponse['templates']
  onAdd: (role: Partial<TeamRole> & { name: string; template?: string }) => void
  onDelete: (name: string) => void
  onUpdate: (roleName: string, data: Partial<TeamRole> & { name: string }) => void
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
        <span style={{ fontSize: 13, fontWeight: 600, color: '#D4A574' }}>🤖 Agents</span>
        <button onClick={() => { setShowForm(v => !v); setConfigRole(null) }} style={{
          background: showForm ? '#FFFFFF22' : C.accent, color: '#fff',
          border: 'none', borderRadius: 6, padding: '3px 10px', cursor: 'pointer', fontSize: 12, fontWeight: 600,
        }}>
          {showForm ? '取消' : `${Icons.plus} 添加`}
        </button>
      </div>

      {showForm && (
        <div style={{
          background: '#2A1F14', borderRadius: 10, padding: 12,
          display: 'flex', flexDirection: 'column', gap: 8,
          border: `1px solid ${C.accent}33`,
        }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {Object.keys(templates).map(k => (
              <button key={k} onClick={() => handleTemplate(k)} style={{
                background: form.template === k ? C.accent : '#FFFFFF18',
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
                padding: '8px 10px', background: '#2A1F14',
                borderRadius: configRole === r.name ? '8px 8px 0 0' : 8,
                border: `1px solid ${configRole === r.name ? C.accent + '66' : hoveredRole === r.name ? C.accent + '44' : 'transparent'}`,
                borderBottom: configRole === r.name ? 'none' : undefined,
                cursor: 'pointer', transition: 'border 0.15s',
              }}>
              <Avatar name={r.name} size={28} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#fff' }}>{r.name}</div>
                <div style={{ fontSize: 10, color: '#A0674A', marginTop: 1 }}>
                  {r.watch_actions?.join(', ') || '无监听'}
                </div>
                {(r.upstream_roles?.length > 0 || r.downstream_roles?.length > 0) && (
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
              />
            )}
          </div>
        ))}
        {roles.length === 0 && !showForm && (
          <div style={{ color: '#A0674A', fontSize: 12, textAlign: 'center', padding: 8 }}>
            暂无 Agent
          </div>
        )}
      </div>
    </div>
  )
}
