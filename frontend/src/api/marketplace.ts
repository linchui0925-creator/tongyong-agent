/**
 * Skill 市场 API 客户端
 *
 * 对应后端 /api/marketplace/*（注意：跟 /api/multi_agent/marketplace/* 区分）
 * - /api/marketplace/*  ← 本文件管 SKILL.md 资源
 * - /api/multi_agent/marketplace/*  ← Agent 模板市场（team.ts 里的那套）
 */

import axios from 'axios'

const API_BASE_URL = '/api/marketplace'

const api = axios.create({
    baseURL: API_BASE_URL,
    timeout: 60000,
    headers: { 'Content-Type': 'application/json' }
})

// ── 类型 ──────────────────────────────────────────

/** 单个配套文件元数据（来自 GitHub tree API） */
export interface SkillFileMeta {
    path: string              // 仓库内路径, 如 "skills/pdf/forms.md"
    size: number              // 字节
    sha: string               // blob sha
    type: string              // 通常 "blob"
}

export interface MarketplaceSkill {
    name: string
    description: string
    category: string
    version: string
    tags: string[]
    source: string
    source_repo: string
    source_path: string
    source_url: string
    size_bytes: number
    // Phase 4+: 本地是否已装（后端 /skills 端点补的）
    installed?: boolean
    local_quarantined?: boolean | null
    local_skill_type?: string | null
    // Phase 4 续 C: 配套文件元数据（references/templates/scripts/LICENSE 等）
    files?: SkillFileMeta[]
    /** 配套文件数（不含 SKILL.md 本体） */
    file_count?: number
    /** 总字节（SKILL.md + 配套文件） */
    total_size_bytes?: number
}

export interface MarketplaceCategory {
    name: string
    count: number
}

export interface MarketplaceSource {
    owner: string
    repo: string
    skill_count?: number
    last_fetch?: string
}

export interface InstallResult {
    ok: boolean
    path: string
    abs_path: string
    quarantined: boolean
    skill_type: string
    /** 实际下载成功的配套文件 */
    files?: { path: string; size: number }[]
    /** 跳过的文件（不安全路径 / 二进制 / 超阈值） */
    files_skipped?: string[]
    /** 拉取失败的文件 */
    files_failed?: string[]
    /** 下载的配套文件数 */
    total_files?: number
}

export interface RefreshResult {
    ok: boolean
    count?: number
    filtered?: number
    skipped?: boolean
    reason?: string
    error?: string
}

// ── 列表 / 详情 / 分类 ────────────────────────────

export async function listMarketplaceSkills(params: {
    category?: string
    search?: string
    source?: string
    page?: number
    page_size?: number
} = {}): Promise<{ skills: MarketplaceSkill[]; total: number; page: number; page_size: number }> {
    const response = await api.get('/skills', { params })
    return response.data
}

export async function getMarketplaceSkill(
    name: string,
    source?: string
): Promise<MarketplaceSkill> {
    const response = await api.get(`/skills/${encodeURIComponent(name)}`, {
        params: source ? { source } : {}
    })
    return response.data
}

export async function listMarketplaceCategories(): Promise<{ categories: MarketplaceCategory[] }> {
    const response = await api.get('/categories')
    return response.data
}

// ── 源管理 ───────────────────────────────────────

export async function listMarketplaceSources(): Promise<{ sources: string[] }> {
    const response = await api.get('/sources')
    return response.data
}

export async function addMarketplaceSource(owner_repo: string): Promise<{
    ok: boolean
    source: string
    count?: number
    filtered?: number
    error?: string
}> {
    const response = await api.post('/sources', { owner_repo })
    return response.data
}

export async function removeMarketplaceSource(owner_repo: string): Promise<{
    ok: boolean
    removed: string
}> {
    const response = await api.delete(`/sources/${encodeURIComponent(owner_repo)}`)
    return response.data
}

// ── 刷新 ─────────────────────────────────────────

export async function refreshMarketplace(payload: {
    owner_repo?: string
    force?: boolean
} = {}): Promise<RefreshResult | Record<string, RefreshResult>> {
    const response = await api.post('/refresh', payload)
    return response.data
}

// ── 安装 ─────────────────────────────────────────

export async function installMarketplaceSkill(
    name: string,
    source: string,
    profile?: string
): Promise<InstallResult> {
    const response = await api.post(`/skills/${encodeURIComponent(name)}/install`, {
        source,
        profile
    })
    return response.data
}

// Phase 4: 重装已存在的 marketplace skill（强制覆盖 + 备份 + 扫描）
export interface ReinstallResult {
    ok: boolean
    name: string
    source: string
    abs_path: string
    backup: string
    security_warnings: string[]
    refreshed_at: string
}
export async function reinstallMarketplaceSkill(
    name: string,
    source: string
): Promise<ReinstallResult> {
    const response = await api.post(`/skills/${encodeURIComponent(name)}/reinstall`, {
        source
    })
    return response.data
}
