/**
 * Multi-Agent Team API Client
 */

const API_BASE = '/api/team'

// ── Types ─────────────────────────────────────────

export interface ToolPermission {
  allowed_tools: string[]
  denied_tools: string[]
  max_tool_turns: number
}

export interface TeamSession {
  id: string
  name: string
  status: string
  config: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface TeamRole {
  name: string
  profile: string
  watch_actions: string[]
  action_types: string[]
  action_configs: Record<string, Record<string, unknown>>
  tool_permission: ToolPermission
  llm_provider: string
  llm_model: string
  opponent_name: string
  stance: string
  debate_side: string
  debate_position: string
  upstream_roles: string[]
  downstream_roles: string[]
  status: string
}

export interface ToolsetInfo {
  name: string
  tools: string[]
  available: boolean
}

export interface ToolInfo {
  name: string
  toolset: string
  description: string
  emoji: string
}

export interface ToolsResponse {
  toolsets: ToolsetInfo[]
  tools: ToolInfo[]
}

export interface RoleTemplate {
  name: string
  profile: string
  watch_actions: string[]
  action_types: string[]
}

export interface RoleTemplatesResponse {
  templates: Record<string, RoleTemplate>
}

export interface MessageItem {
  id: string
  role: string
  content: string
  created_at: string
  sequence: number | null
  cause_by: string
  sent_from: string
  send_to: string
}

// ── API Functions ─────────────────────────────────────────

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`API ${path} failed: ${res.status} — ${err}`)
  }
  return res.json()
}

// Sessions
export const createSession = (name: string, config?: Record<string, unknown>) =>
  request<TeamSession>('/sessions', {
    method: 'POST',
    body: JSON.stringify({ name, config: config || {} }),
  })

export const getSessions = () => request<TeamSession[]>('/sessions')

export const getSession = (id: string) => request<TeamSession>(`/sessions/${id}`)

export const deleteSession = (id: string) =>
  request<void>(`/sessions/${id}`, { method: 'DELETE' })

export const stopTeam = (sessionId: string) =>
  request<{ ok: boolean }>(`/sessions/${sessionId}/stop`, { method: 'POST' })

// Roles
export const createRole = (sessionId: string, role: Partial<TeamRole> & { name: string }) =>
  request<TeamRole>(`/sessions/${sessionId}/roles`, {
    method: 'POST',
    body: JSON.stringify(role),
  })

export const getRoles = (sessionId: string) =>
  request<TeamRole[]>(`/sessions/${sessionId}/roles`)

export const deleteRole = (sessionId: string, roleName: string) =>
  request<void>(`/sessions/${sessionId}/roles/${roleName}`, { method: 'DELETE' })

export const updateRole = (sessionId: string, roleName: string, data: Partial<TeamRole> & { name: string }) =>
  request<TeamRole>(`/sessions/${sessionId}/roles/${roleName}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })

// Run
export interface RunTeamParams {
  idea: string
  n_round?: number
  send_to?: string
}

export const runTeamStream = (
  sessionId: string,
  params: RunTeamParams,
  onMessage: (msg: MessageItem) => void,
  onDone: (rounds: number) => void,
  onError: (err: string) => void,
) => {
  const url = `${API_BASE}/sessions/${sessionId}/run/stream?` +
    `idea=${encodeURIComponent(params.idea)}` +
    `&n_round=${params.n_round ?? 5}` +
    `&send_to=${params.send_to ?? ''}`

  const es = new EventSource(url)

  // event: message — Agent 发言
  es.addEventListener('message', (e: MessageEvent) => {
    let data: any
    try {
      data = JSON.parse(e.data)
    } catch {
      return
    }
    if (data.type === 'message') {
      onMessage({
        id: data.id,
        role: data.role,
        content: data.content,
        created_at: data.created_at,
        sequence: data.sequence,
        cause_by: data.cause_by,
        sent_from: data.sent_from,
        send_to: data.send_to,
      })
    }
  })

  // event: done — 协作完成
  es.addEventListener('done', (e: MessageEvent) => {
    let data: any
    try {
      data = JSON.parse(e.data)
    } catch {
      return
    }
    onDone(data.rounds)
    es.close()
  })

  // event: error (SSE 自定义) + 原生连接错误
  // SSE event:error → MessageEvent(有 .data)；连接断开 → Event(无 .data)
  es.addEventListener('error', (e: Event | MessageEvent) => {
    if ('data' in e) {
      // 后端推送的自定义错误
      try {
        const data = JSON.parse((e as MessageEvent).data)
        onError(data.message || '未知错误')
      } catch {
        onError('未知错误')
      }
      es.close()
    } else {
      // 原生连接断开：延后执行，让排队的 done 事件先处理
      setTimeout(() => {
        if (es.readyState !== EventSource.CLOSED) {
          onError('连接中断')
        }
        es.close()
      }, 100)
    }
  })

  return () => es.close()
}

export const runTeam = (sessionId: string, params: RunTeamParams) =>
  request<{ session_id: string; status: string; rounds: number; messages: MessageItem[] }>(
    `/sessions/${sessionId}/run`,
    {
      method: 'POST',
      body: JSON.stringify(params),
    }
  )

// Messages
export const getMessages = (sessionId: string) =>
  request<{ messages: MessageItem[] }>(`/sessions/${sessionId}/messages`).then(r => r.messages)

export const sendMessage = (sessionId: string, content: string, sendTo = '') =>
  request<MessageItem>(`/sessions/${sessionId}/messages/send`, {
    method: 'POST',
    body: JSON.stringify({ content, send_to: sendTo }),
  })

// Tools & Templates
export const getTools = () => request<ToolsResponse>('/tools')

export const getRoleTemplates = () => request<RoleTemplatesResponse>('/roles/templates')

// ── Connections ─────────────────────────────────────────

export interface Connection {
  id: string
  session_id: string
  from_role: string
  to_role: string
  match_cause: string
}

export const createConnection = (sessionId: string, fromRole: string, toRole: string, matchCause = '') =>
  request<Connection>(`/sessions/${sessionId}/connections`, {
    method: 'POST',
    body: JSON.stringify({ from_role: fromRole, to_role: toRole, match_cause: matchCause }),
  })

export const getConnections = (sessionId: string) =>
  request<Connection[]>(`/sessions/${sessionId}/connections`)

export const deleteConnection = (sessionId: string, fromRole: string, toRole: string) =>
  request<void>(`/sessions/${sessionId}/connections?from_role=${encodeURIComponent(fromRole)}&to_role=${encodeURIComponent(toRole)}`, {
    method: 'DELETE',
  })

// ── Agent Marketplace ─────────────────────────────────────────

export interface AgentTemplate {
  id: string
  name: string
  profile: string
  category: string
  tags: string[]
  watch_actions: string[]
  action_types: string[]
  action_configs: Record<string, Record<string, unknown>>
  tool_permission: ToolPermission
  llm_provider: string
  llm_model: string
  opponent_name: string
  stance: string
  skills: string[]
  created_at: string
  updated_at: string
}

export interface MarketplaceSkill {
  name: string
  description: string
  category: string
}

export const createMarketAgent = (data: Partial<AgentTemplate>) =>
  request<AgentTemplate>('/marketplace', {
    method: 'POST',
    body: JSON.stringify(data),
  })

export const getMarketAgents = () =>
  request<AgentTemplate[]>('/marketplace')

export const getMarketAgent = (id: string) =>
  request<AgentTemplate>(`/marketplace/${id}`)

export const updateMarketAgent = (id: string, data: Partial<AgentTemplate>) =>
  request<AgentTemplate>(`/marketplace/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })

export const deleteMarketAgent = (id: string) =>
  request<void>(`/marketplace/${id}`, { method: 'DELETE' })

export const importMarketAgent = (agentId: string, sessionId: string, nameOverride?: string) =>
  request<TeamRole>(`/marketplace/${agentId}/import`, {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, name_override: nameOverride }),
  })

export const getMarketCategories = () =>
  request<string[]>('/marketplace/categories')

export const getMarketSkills = () =>
  request<{ skills: MarketplaceSkill[] }>('/marketplace/skills/list')
