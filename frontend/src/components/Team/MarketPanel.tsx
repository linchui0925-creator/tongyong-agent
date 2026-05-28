import React, { useState, useEffect, useCallback, useRef } from 'react'
import {
  getMarketAgents, createMarketAgent, updateMarketAgent, deleteMarketAgent,
  importMarketAgent, getTools, getMarketSkills,
  type AgentTemplate, type ToolsResponse, type ToolInfo, type ToolsetInfo,
  type MarketplaceSkill,
} from '../../api/team'
import { uploadSkill } from '../../api/skills'
import { C } from './constants'

// ── Icons ─────────────────────────────────────────
const Icons = {
  x: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  plus: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
  edit: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>,
  trash: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>,
  import: <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>,
  upload: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>,
  check: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>,
  search: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  close: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
}

// ── Shared input style ─────────────────────────────────────────
const inputS: React.CSSProperties = {
  padding: '7px 10px', border: `1px solid ${C.border}`, borderRadius: 8,
  background: C.card, color: C.text, fontSize: 13, width: '100%',
  boxSizing: 'border-box', outline: 'none',
}

const labelS: React.CSSProperties = {
  fontSize: 12, fontWeight: 600, color: C.textLight, marginBottom: 4, display: 'block',
}

// ── Tag Input ─────────────────────────────────────────
function TagInput({ tags, onChange, placeholder }: {
  tags: string[]
  onChange: (t: string[]) => void
  placeholder?: string
}) {
  const [input, setInput] = useState('')

  const addTag = (v: string) => {
    const t = v.trim()
    if (t && !tags.includes(t)) {
      onChange([...tags, t])
    }
    setInput('')
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addTag(input)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {tags.map(t => (
          <span key={t} style={{
            display: 'flex', alignItems: 'center', gap: 3,
            background: C.accentLight, color: C.accent,
            borderRadius: 4, padding: '2px 6px', fontSize: 11, fontWeight: 600,
          }}>
            {t}
            <button onClick={() => onChange(tags.filter(x => x !== t))} style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: C.accent, padding: 0, fontSize: 13, lineHeight: 1,
            }}>{Icons.x}</button>
          </span>
        ))}
      </div>
      <input
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={handleKey}
        onBlur={() => { if (input) addTag(input) }}
        placeholder={placeholder || '输入后按 Enter 添加'}
        style={{ ...inputS, padding: '5px 8px', fontSize: 12 }}
      />
    </div>
  )
}

// ── Checkbox Group ─────────────────────────────────────────
function CheckboxGroup({ options, selected, onChange, columns = 1 }: {
  options: { value: string; label: string }[]
  selected: string[]
  onChange: (v: string[]) => void
  columns?: number
}) {
  const toggle = (v: string) => {
    onChange(selected.includes(v) ? selected.filter(x => x !== v) : [...selected, v])
  }

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: `repeat(${columns}, 1fr)`, gap: 4,
      maxHeight: 180, overflowY: 'auto', padding: '4px 0',
    }}>
      {options.map(o => (
        <label key={o.value} style={{
          display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
          padding: '3px 6px', borderRadius: 4, fontSize: 12,
          background: selected.includes(o.value) ? `${C.accent}15` : 'transparent',
          color: C.text,
        }}>
          <input type="checkbox" checked={selected.includes(o.value)}
            onChange={() => toggle(o.value)}
            style={{ accentColor: C.accent, margin: 0, cursor: 'pointer' }}
          />
          {o.label}
        </label>
      ))}
    </div>
  )
}

// ── Tool Permission Selector ─────────────────────────────────────────
function ToolPermissionSelector({ toolsets, tools, allowedTools, onChange }: {
  toolsets: ToolsetInfo[]
  tools: ToolInfo[]
  allowedTools: string[]
  onChange: (v: string[]) => void
}) {
  const toggleTool = (name: string) => {
    onChange(allowedTools.includes(name)
      ? allowedTools.filter(x => x !== name)
      : [...allowedTools, name])
  }

  const toggleToolset = (ts: ToolsetInfo) => {
    const allSelected = ts.tools.every(t => allowedTools.includes(t))
    if (allSelected) {
      onChange(allowedTools.filter(t => !ts.tools.includes(t)))
    } else {
      const merged = [...allowedTools]
      for (const t of ts.tools) {
        if (!merged.includes(t)) merged.push(t)
      }
      onChange(merged)
    }
  }

  if (toolsets.length === 0) {
    return <div style={{ fontSize: 12, color: C.textMuted }}>加载工具列表中...</div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {toolsets.map(ts => {
        const allSelected = ts.tools.length > 0 && ts.tools.every(t => allowedTools.includes(t))
        const someSelected = ts.tools.some(t => allowedTools.includes(t))

        return (
          <div key={ts.name} style={{
            border: `1px solid ${C.border}`, borderRadius: 8, overflow: 'hidden',
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '6px 10px', background: C.accentLight, cursor: 'pointer',
            }}
              onClick={() => toggleToolset(ts)}
            >
              <input type="checkbox" checked={allSelected}
                ref={el => { if (el) el.indeterminate = someSelected && !allSelected }}
                onChange={() => toggleToolset(ts)}
                style={{ accentColor: C.accent, margin: 0, cursor: 'pointer' }}
              />
              <span style={{ fontSize: 12, fontWeight: 600, color: C.accent, flex: 1 }}>
                {ts.name} {ts.available ? '' : '(不可用)'}
              </span>
              <span style={{ fontSize: 10, color: C.textMuted }}>
                {ts.tools.filter(t => allowedTools.includes(t)).length}/{ts.tools.length}
              </span>
            </div>
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2,
              padding: '4px 8px 6px 24px',
            }}>
              {ts.tools.map(toolName => {
                const toolInfo = tools.find(t => t.name === toolName)
                return (
                  <label key={toolName}
                    onClick={e => e.stopPropagation()}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer',
                      padding: '2px 4px', borderRadius: 3, fontSize: 11,
                      color: C.text,
                    }}>
                    <input type="checkbox" checked={allowedTools.includes(toolName)}
                      onChange={() => toggleTool(toolName)}
                      style={{ accentColor: C.accent, margin: 0, cursor: 'pointer' }}
                    />
                    <span>{toolInfo?.emoji || '🔧'}</span>
                    <span>{toolName}</span>
                  </label>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Editor Modal ─────────────────────────────────────────
const ACTION_TYPE_OPTIONS = [
  { value: 'llm_think', label: '🧠 llm_think' },
  { value: 'speak_aloud', label: '🗣️ speak_aloud' },
  { value: 'write_code', label: '💻 write_code' },
  { value: 'write_test', label: '🧪 write_test' },
  { value: 'write_review', label: '🔍 write_review' },
  { value: 'tool_call', label: '🛠️ tool_call' },
  { value: 'send_to', label: '📨 send_to' },
]

const WATCH_ACTION_OPTIONS = [
  { value: 'UserRequirement', label: '📋 UserRequirement' },
  { value: 'SpeakAloud', label: '🗣️ SpeakAloud' },
  { value: 'WriteCode', label: '💻 WriteCode' },
  { value: 'WriteTest', label: '🧪 WriteTest' },
  { value: 'WriteReview', label: '🔍 WriteReview' },
  { value: 'SendTo', label: '📨 SendTo' },
  { value: 'ToolCall', label: '🛠️ ToolCall' },
]

const LLM_PROVIDERS = ['deepseek', 'openai', 'claude', 'gemini', 'custom']

interface AgentFormData {
  name: string
  profile: string
  category: string
  tags: string[]
  watch_actions: string[]
  action_types: string[]
  allowed_tools: string[]
  max_tool_turns: number
  skills: string[]
  llm_provider: string
  llm_model: string
  opponent_name: string
  stance: string
}

function emptyForm(): AgentFormData {
  return {
    name: '', profile: '', category: '', tags: [],
    watch_actions: ['UserRequirement'], action_types: ['speak_aloud'],
    allowed_tools: [], max_tool_turns: 20,
    skills: [], llm_provider: 'deepseek', llm_model: '',
    opponent_name: '', stance: '',
  }
}

function formFromAgent(a: AgentTemplate): AgentFormData {
  return {
    name: a.name,
    profile: a.profile,
    category: a.category,
    tags: a.tags || [],
    watch_actions: a.watch_actions || [],
    action_types: a.action_types || [],
    allowed_tools: a.tool_permission?.allowed_tools || [],
    max_tool_turns: a.tool_permission?.max_tool_turns ?? 20,
    skills: a.skills || [],
    llm_provider: a.llm_provider || 'deepseek',
    llm_model: a.llm_model || '',
    opponent_name: a.opponent_name || '',
    stance: a.stance || '',
  }
}

function EditorModal({ agent, toolsData, allSkills, onSave, onClose }: {
  agent: AgentTemplate | null
  toolsData: ToolsResponse | null
  allSkills: MarketplaceSkill[]
  onSave: (data: AgentFormData, id?: string) => Promise<void>
  onClose: () => void
}) {
  const [form, setForm] = useState<AgentFormData>(agent ? formFromAgent(agent) : emptyForm())
  const [saving, setSaving] = useState(false)
  const [debateOpen, setDebateOpen] = useState(false)
  const [error, setError] = useState('')

  // 技能上传
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  const isEdit = !!agent

  const set = (k: keyof AgentFormData, v: any) => setForm(f => ({ ...f, [k]: v }))

  const handleSave = async () => {
    if (!form.name.trim()) {
      setError('请输入 Agent 名称')
      return
    }
    setSaving(true)
    setError('')
    try {
      await onSave(form, agent?.id)
      onClose()
    } catch (e: any) {
      setError(e.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      await uploadSkill(file, form.category || 'general')
      alert('技能上传成功！')
    } catch (err: any) {
      alert('技能上传失败: ' + (err.message || '未知错误'))
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.4)', display: 'flex',
      alignItems: 'center', justifyContent: 'center',
      animation: 'fadeIn 0.15s ease',
    }} onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{
        background: C.bg, borderRadius: 16, width: 700, maxHeight: '85vh',
        display: 'flex', flexDirection: 'column',
        boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
        animation: 'slideUp 0.2s ease',
      }}>
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '14px 20px', borderBottom: `1px solid ${C.border}`,
        }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: C.text }}>
            {isEdit ? '编辑 Agent' : '创建 Agent'}
          </span>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', cursor: 'pointer', color: C.textMuted, padding: 4,
          }}>{Icons.close}</button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 14 }}>

          {/* ── 基本信息 ── */}
          <div style={{ fontSize: 13, fontWeight: 700, color: C.accent }}>基本信息</div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <div>
              <label style={labelS}>名称 *</label>
              <input value={form.name}
                onChange={e => set('name', e.target.value)}
                placeholder="如 CodePro"
                style={{ ...inputS }} />
            </div>
            <div>
              <label style={labelS}>分类</label>
              <input value={form.category}
                onChange={e => set('category', e.target.value)}
                placeholder="如 development"
                style={{ ...inputS }} />
            </div>
          </div>

          <div>
            <label style={labelS}>资料 / 角色设定</label>
            <textarea value={form.profile}
              onChange={e => set('profile', e.target.value)}
              placeholder="描述这个 Agent 的角色和能力..."
              rows={3}
              style={{ ...inputS, resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.5 }} />
          </div>

          <div>
            <label style={labelS}>标签</label>
            <TagInput tags={form.tags}
              onChange={v => set('tags', v)}
              placeholder="输入标签后按 Enter" />
          </div>

          {/* ── 工具权限 ── */}
          <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.accent, marginBottom: 8 }}>工具权限</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
              <label style={{ ...labelS, marginBottom: 0, whiteSpace: 'nowrap' }}>最大工具调用轮数:</label>
              <input type="number" value={form.max_tool_turns}
                onChange={e => set('max_tool_turns', Math.max(1, parseInt(e.target.value) || 1))}
                min={1} max={100}
                style={{ ...inputS, width: 70, textAlign: 'center' }} />
            </div>
            {toolsData ? (
              <ToolPermissionSelector
                toolsets={toolsData.toolsets}
                tools={toolsData.tools}
                allowedTools={form.allowed_tools}
                onChange={v => set('allowed_tools', v)} />
            ) : (
              <div style={{ fontSize: 12, color: C.textMuted, padding: 8 }}>加载工具列表中...</div>
            )}
          </div>

          {/* ── 技能 ── */}
          <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: C.accent }}>技能</span>
              <button onClick={() => fileRef.current?.click()}
                disabled={uploading}
                style={{
                  background: C.accent, color: '#fff', border: 'none',
                  borderRadius: 6, padding: '4px 10px', cursor: 'pointer',
                  fontSize: 11, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4,
                }}>
                {Icons.upload} {uploading ? '上传中...' : '上传技能'}
              </button>
              <input ref={fileRef} type="file" accept=".md,.txt,.zip,.json,.yaml,.yml"
                onChange={handleFileUpload} style={{ display: 'none' }} />
            </div>
            {allSkills.length > 0 ? (
              <CheckboxGroup
                options={allSkills.map(s => ({ value: s.name, label: `${s.name}${s.category ? ` (${s.category})` : ''}` }))}
                selected={form.skills}
                onChange={v => set('skills', v)}
                columns={2}
              />
            ) : (
              <div style={{ fontSize: 12, color: C.textMuted }}>暂无可用技能，请上传</div>
            )}
          </div>

          {/* ── 动作配置 ── */}
          <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.accent, marginBottom: 4 }}>动作配置</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div>
                <label style={labelS}>动作类型</label>
                <CheckboxGroup
                  options={ACTION_TYPE_OPTIONS}
                  selected={form.action_types}
                  onChange={v => set('action_types', v)}
                  columns={1}
                />
              </div>
              <div>
                <label style={labelS}>监听动作</label>
                <CheckboxGroup
                  options={WATCH_ACTION_OPTIONS}
                  selected={form.watch_actions}
                  onChange={v => set('watch_actions', v)}
                  columns={1}
                />
              </div>
            </div>
          </div>

          {/* ── LLM 配置 ── */}
          <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: C.accent, marginBottom: 8 }}>LLM 配置</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div>
                <label style={labelS}>提供商</label>
                <select value={form.llm_provider}
                  onChange={e => set('llm_provider', e.target.value)}
                  style={{ ...inputS, cursor: 'pointer' }}>
                  {LLM_PROVIDERS.map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
              <div>
                <label style={labelS}>模型</label>
                <input value={form.llm_model}
                  onChange={e => set('llm_model', e.target.value)}
                  placeholder="留空使用默认模型"
                  style={{ ...inputS }} />
              </div>
            </div>
          </div>

          {/* ── 辩论配置 (折叠) ── */}
          <div style={{ borderTop: `1px solid ${C.border}`, paddingTop: 12 }}>
            <button onClick={() => setDebateOpen(v => !v)} style={{
              background: 'none', border: 'none', cursor: 'pointer', padding: 0,
              display: 'flex', alignItems: 'center', gap: 6,
              fontSize: 13, fontWeight: 700, color: C.accent,
            }}>
              <span style={{
                display: 'inline-block', transition: 'transform 0.15s',
                transform: debateOpen ? 'rotate(90deg)' : 'rotate(0)',
              }}>▶</span>
              辩论配置（可选）
            </button>
            {debateOpen && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 8 }}>
                <div>
                  <label style={labelS}>对手名</label>
                  <input value={form.opponent_name}
                    onChange={e => set('opponent_name', e.target.value)}
                    placeholder="如 Trump"
                    style={{ ...inputS }} />
                </div>
                <div>
                  <label style={labelS}>立场</label>
                  <input value={form.stance}
                    onChange={e => set('stance', e.target.value)}
                    placeholder="如 赞成 / 反对"
                    style={{ ...inputS }} />
                </div>
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <div style={{ color: C.error, fontSize: 12, background: '#FEF2F2', borderRadius: 6, padding: '6px 10px' }}>
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          display: 'flex', justifyContent: 'flex-end', gap: 8,
          padding: '12px 20px', borderTop: `1px solid ${C.border}`,
        }}>
          <button onClick={onClose} style={{
            padding: '8px 16px', borderRadius: 8, border: `1px solid ${C.border}`,
            background: C.card, color: C.text, cursor: 'pointer', fontSize: 13,
          }}>
            取消
          </button>
          <button onClick={handleSave} disabled={saving} style={{
            padding: '8px 20px', borderRadius: 8, border: 'none',
            background: C.accent, color: '#fff', cursor: saving ? 'not-allowed' : 'pointer',
            fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6,
            opacity: saving ? 0.6 : 1,
          }}>
            {saving ? '保存中...' : <>{Icons.check} {isEdit ? '保存' : '创建'}</>}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── MarketPanel (Main) ─────────────────────────────────────────
export function MarketPanel({ sessionId, onImportSuccess }: {
  sessionId: string
  onImportSuccess?: () => void
}) {
  const [agents, setAgents] = useState<AgentTemplate[]>([])
  const [toolsData, setToolsData] = useState<ToolsResponse | null>(null)
  const [allSkills, setAllSkills] = useState<MarketplaceSkill[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [editAgent, setEditAgent] = useState<AgentTemplate | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)

  const fetchAll = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [a, t, s] = await Promise.all([
        getMarketAgents(),
        getTools(),
        getMarketSkills(),
      ])
      setAgents(a)
      setToolsData(t)
      setAllSkills(s.skills || [])
    } catch (e: any) {
      setError(e.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  // Load tools & skills lazily when modal opens (if not loaded)
  const ensureToolsAndSkills = useCallback(async () => {
    if (!toolsData) {
      try {
        const t = await getTools()
        setToolsData(t)
      } catch { /* ignore */ }
    }
    if (allSkills.length === 0) {
      try {
        const s = await getMarketSkills()
        setAllSkills(s.skills || [])
      } catch { /* ignore */ }
    }
  }, [toolsData, allSkills])

  const handleCreate = async (data: AgentFormData) => {
    const result = await createMarketAgent({
      name: data.name,
      profile: data.profile,
      category: data.category,
      tags: data.tags,
      watch_actions: data.watch_actions,
      action_types: data.action_types,
      tool_permission: {
        allowed_tools: data.allowed_tools,
        denied_tools: [],
        max_tool_turns: data.max_tool_turns,
      },
      skills: data.skills,
      llm_provider: data.llm_provider,
      llm_model: data.llm_model,
      opponent_name: data.opponent_name,
      stance: data.stance,
    })
    setAgents(prev => [...prev, result])
  }

  const handleUpdate = async (data: AgentFormData, id?: string) => {
    if (!id) return
    const result = await updateMarketAgent(id, {
      name: data.name,
      profile: data.profile,
      category: data.category,
      tags: data.tags,
      watch_actions: data.watch_actions,
      action_types: data.action_types,
      tool_permission: {
        allowed_tools: data.allowed_tools,
        denied_tools: [],
        max_tool_turns: data.max_tool_turns,
      },
      skills: data.skills,
      llm_provider: data.llm_provider,
      llm_model: data.llm_model,
      opponent_name: data.opponent_name,
      stance: data.stance,
    })
    setAgents(prev => prev.map(a => a.id === id ? result : a))
  }

  const handleDelete = async (id: string) => {
    if (!window.confirm('确认删除此 Agent？')) return
    setDeleting(id)
    try {
      await deleteMarketAgent(id)
      setAgents(prev => prev.filter(a => a.id !== id))
    } catch (e: any) {
      alert('删除失败: ' + (e.message || '未知错误'))
    } finally {
      setDeleting(null)
    }
  }

  const handleImport = async (agentId: string) => {
    if (!sessionId) {
      alert('请先选择或创建一个会话')
      return
    }
    try {
      await importMarketAgent(agentId, sessionId)
      onImportSuccess?.()
    } catch (e: any) {
      alert('导入失败: ' + (e.message || '未知错误'))
    }
  }

  // Filter agents by search
  const filtered = agents.filter(a => {
    if (!search.trim()) return true
    const q = search.toLowerCase()
    return a.name.toLowerCase().includes(q) ||
      a.profile.toLowerCase().includes(q) ||
      a.tags?.some(t => t.toLowerCase().includes(q)) ||
      a.category?.toLowerCase().includes(q)
  })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: '#D4A574' }}>📦 Agent 市场</span>
        <button onClick={() => { ensureToolsAndSkills(); setShowCreate(true) }} style={{
          background: C.accent, color: '#fff', border: 'none', borderRadius: 6,
          padding: '3px 10px', cursor: 'pointer', fontSize: 12, fontWeight: 600,
          display: 'flex', alignItems: 'center', gap: 4,
        }}>
          {Icons.plus} 新建
        </button>
      </div>

      {/* Search */}
      <div style={{ position: 'relative' }}>
        <span style={{ position: 'absolute', left: 8, top: 7, color: C.textMuted }}>{Icons.search}</span>
        <input value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="搜索 Agent..."
          style={{
            ...inputS, paddingLeft: 26, fontSize: 12,
            background: '#2A1F14', color: '#fff', border: `1px solid ${C.accent}33`,
            width: '100%',
          }}
        />
      </div>

      {/* Content */}
      <div style={{
        display: 'flex', flexDirection: 'column', gap: 6,
        maxHeight: 320, overflowY: 'auto',
      }}>
        {loading ? (
          <div style={{ color: '#A0674A', fontSize: 12, textAlign: 'center', padding: 12 }}>
            加载中...
          </div>
        ) : error ? (
          <div style={{ fontSize: 12, color: C.error, textAlign: 'center', padding: 12 }}>
            {error}
            <button onClick={fetchAll} style={{
              display: 'block', margin: '6px auto 0',
              background: 'none', border: `1px solid ${C.error}`, borderRadius: 4,
              color: C.error, cursor: 'pointer', fontSize: 11, padding: '2px 10px',
            }}>重试</button>
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ color: '#A0674A', fontSize: 12, textAlign: 'center', padding: 12 }}>
            {search ? '无匹配 Agent' : '市场暂无 Agent\n点击上方"新建"创建'}
          </div>
        ) : (
          filtered.map(a => {
            const skillCount = a.skills?.length || 0
            const tagCount = a.tags?.length || 0
            return (
              <div key={a.id} style={{
                background: '#2A1F14', borderRadius: 8, padding: '8px 10px',
                border: `1px solid ${C.accent}22`,
                transition: 'border 0.15s',
              }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                  <div style={{
                    width: 28, height: 28, borderRadius: '50%',
                    background: `linear-gradient(135deg, ${C.accent} 0%, #8B5E3C 100%)`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 13, flexShrink: 0, color: '#fff', fontWeight: 700,
                  }}>
                    {a.name[0]?.toUpperCase()}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#fff' }}>
                      {a.name}
                    </div>
                    <div style={{ fontSize: 10, color: '#A0674A', marginTop: 1, lineHeight: 1.4 }}>
                      {a.profile ? (a.profile.length > 60 ? a.profile.slice(0, 60) + '...' : a.profile) : '无资料'}
                    </div>
                    <div style={{ display: 'flex', gap: 4, marginTop: 4, flexWrap: 'wrap' }}>
                      {a.category && (
                        <span style={{
                          background: `${C.accent}22`, color: C.accent,
                          fontSize: 9, padding: '1px 5px', borderRadius: 3, fontWeight: 600,
                        }}>
                          {a.category}
                        </span>
                      )}
                      {skillCount > 0 && (
                        <span style={{
                          background: '#65A30D22', color: '#65A30D',
                          fontSize: 9, padding: '1px 5px', borderRadius: 3,
                        }}>
                          {skillCount} 技能
                        </span>
                      )}
                      {tagCount > 0 && (
                        <span style={{
                          background: '#A0674A22', color: '#A0674A',
                          fontSize: 9, padding: '1px 5px', borderRadius: 3,
                        }}>
                          {tagCount} 标签
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div style={{ display: 'flex', gap: 4, marginTop: 6, justifyContent: 'flex-end' }}>
                  {/* Import */}
                  <button onClick={() => handleImport(a.id)}
                    title="导入到当前会话"
                    style={{
                      background: C.success, color: '#fff', border: 'none',
                      borderRadius: 4, padding: '3px 8px', cursor: 'pointer',
                      fontSize: 10, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 3,
                    }}>
                    {Icons.import} 导入
                  </button>
                  {/* Edit */}
                  <button onClick={() => { ensureToolsAndSkills(); setEditAgent(a) }}
                    title="编辑"
                    style={{
                      background: `${C.accent}33`, color: C.accent, border: 'none',
                      borderRadius: 4, padding: '3px 8px', cursor: 'pointer',
                      fontSize: 10, display: 'flex', alignItems: 'center',
                    }}>
                    {Icons.edit}
                  </button>
                  {/* Delete */}
                  <button onClick={() => handleDelete(a.id)}
                    disabled={deleting === a.id}
                    title="删除"
                    style={{
                      background: '#DC262611', color: C.error, border: 'none',
                      borderRadius: 4, padding: '3px 8px', cursor: 'pointer',
                      fontSize: 10, display: 'flex', alignItems: 'center',
                    }}>
                    {Icons.trash}
                  </button>
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* Create Modal */}
      {showCreate && (
        <EditorModal
          agent={null}
          toolsData={toolsData}
          allSkills={allSkills}
          onSave={handleCreate}
          onClose={() => setShowCreate(false)}
        />
      )}

      {/* Edit Modal */}
      {editAgent && (
        <EditorModal
          agent={editAgent}
          toolsData={toolsData}
          allSkills={allSkills}
          onSave={(data, _id) => handleUpdate(data, editAgent.id)}
          onClose={() => setEditAgent(null)}
        />
      )}

      {/* Animations */}
      <style>{`
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes slideUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
      `}</style>
    </div>
  )
}
