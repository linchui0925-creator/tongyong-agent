/**
 * Skills API - 技能管理
 */

import axios from 'axios'

const API_BASE_URL = '/api/skills'

const api = axios.create({
    baseURL: API_BASE_URL,
    timeout: 60000, // 上传可能较慢
    headers: { 'Content-Type': 'application/json' }
})

export interface Skill {
    id: string
    name: string
    content: string
    category: string
    usage_count: number
    success_rate: number
    version: number
    trigger_conditions: string[]
    execution_steps: string[]
    // Phase 4 新增
    size_bytes?: number
    source_repo?: string
    skill_type?: 'system' | 'external'
    auto_load?: boolean
    quarantined?: boolean
    installed_at?: string
}

export interface SkillDetail {
    name: string
    category: string
    metadata: Record<string, any>
    body: string
    has_references: boolean
    has_templates: boolean
}

export interface UploadResult {
    success: boolean
    skill_name?: string
    message: string
    parsed_triggers: string[]
    parsed_steps: string[]
    warnings: string[]
}

export interface TriggerMatchResult {
    matched: boolean
    skill_name?: string
    skill_detail?: SkillDetail
    match_reason?: string
}

export interface SkillCategory {
    categories: string[]
}

// 获取技能列表
export async function listSkills(): Promise<{ skills: Skill[]; total: number }> {
    const response = await api.get('')
    return response.data
}

// 获取技能详情
export async function getSkill(name: string): Promise<SkillDetail> {
    const response = await api.get(`/${encodeURIComponent(name)}`)
    return response.data
}

// 删除技能
export async function deleteSkill(skillId: string): Promise<void> {
    await api.delete(`/${encodeURIComponent(skillId)}`)
}

// 修改 skill 类型/auto_load/quarantined（system/external 切换）
export async function patchSkillType(
    name: string,
    patch: { skill_type?: 'system' | 'external'; auto_load?: boolean; quarantined?: boolean }
): Promise<{ ok: boolean; name: string; changed: string[] }> {
    const response = await api.patch(`/${encodeURIComponent(name)}/type`, patch)
    return response.data
}

// 上传技能文件（支持 zip、md、txt、json、yaml 等）
export async function uploadSkill(
    file: File,
    category: string = 'general',
    name?: string
): Promise<UploadResult> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('category', category)
    if (name) formData.append('name', name)

    const response = await axios.postForm(`${API_BASE_URL}/upload`, formData, {
        timeout: 120000,
        headers: { 'Content-Type': 'multipart/form-data' }
    })
    return response.data
}

// 触发匹配：根据消息自动匹配 skill
export async function triggerSkill(
    message: string,
    sessionId?: string
): Promise<TriggerMatchResult> {
    const response = await api.post('/trigger', { message, session_id: sessionId })
    return response.data
}

// 获取可用分类
export async function listCategories(): Promise<SkillCategory> {
    const response = await api.get('/categories')
    return response.data
}

// Phase 4: 批量 PATCH（批量解除隔离 / 提升 / 降级）
export interface BatchTypePatchPayload {
    names: string[]
    skill_type?: 'system' | 'external'
    auto_load?: boolean
    quarantined?: boolean
}
export interface BatchTypePatchResult {
    ok: boolean
    total: number
    succeeded: number
    failed: number
    results: Array<{
        name: string
        ok: boolean
        changed?: string[]
        error?: string
    }>
}
export async function batchPatchSkillType(
    payload: BatchTypePatchPayload
): Promise<BatchTypePatchResult> {
    const response = await api.patch('/batch/type', payload)
    return response.data
}

// Phase 4+: token 估算（不调 LLM，本地粗估）
export interface TokenPreviewItem {
    name: string
    size_bytes: number
    estimated_tokens: number
    would_inject: boolean
}

export interface TokenPreviewResponse {
    items: TokenPreviewItem[]
    total_tokens: number
    system_prompt_would_inject: number
    method: string
}

export async function previewTokens(
    names: string[],
    hypothetical: boolean = false
): Promise<TokenPreviewResponse> {
    const response = await api.post('/preview-tokens', { names, hypothetical })
    return response.data
}