/**
 * Community Hub API 客户端
 *
 * 对应后端 /api/hub/* (W5-1 spec §5.9)
 * - 不依赖 marketplace.ts (市场 vs 社区 hub 是两个并行系统)
 * - browse layer (skillhub.lol/.cn) 是 active mapping miner, 不是装饰
 * - install 必须用户主动触发
 */

import axios from 'axios'

const API_BASE_URL = '/api/hub'

const api = axios.create({
    baseURL: API_BASE_URL,
    timeout: 30000,
    headers: { 'Content-Type': 'application/json' }
})

// ── 类型 ──────────────────────────────────────────

export interface HubSource {
    owner: string
    repo: string
    description?: string
    kind: 'default' | 'user' | 'scraped'
    enabled: boolean
    added_at: string
    added_by: string
    scraped_from: string | null
    last_sync_at?: string | null
    last_sync_status?: string | null
}

export interface BrowseLayer {
    id: string
    base_url: string
    enabled: boolean
    user_enabled_at: string | null
    last_sync_at: string | null
    rate_limit_per_sec: number
    scraped_count: number
}

export interface SlugMapping {
    source: string       // 'owner/repo'
    path: string         // 在 repo 内相对路径, 通常 'SKILL.md'
    scraped_from: string | null
    scraped_at: string
    confidence: 'high' | 'medium' | 'low' | 'user_supplied'
}

export interface HubInfo {
    ok: boolean
    config_path: string
    sources_total: number
    sources_enabled: number
    browse_layers: Pick<BrowseLayer, 'id' | 'enabled' | 'last_sync_at' | 'scraped_count'>[]
    slug_mappings_count: number
    scheduler: {
        running: boolean
        last_sync_at: string | null
        last_sync_status: string | null
        last_sync_count: number | null
        last_sync_error: string | null
        sync_count: number
        interval_seconds: number
    }
    schema: number
    updated_at: string | null
}

export interface HubSearchResult {
    id: string
    skill_id: string
    name: string
    source: string
    installs: number
}

export interface HubSearchResponse {
    ok: boolean
    query: string
    skills: HubSearchResult[]
    total: number
}

// ── API ──────────────────────────────────────────

export const hubApi = {
    /** Hub 状态概览 — 给前端 Hub Status card */
    info: async (): Promise<HubInfo> => {
        const r = await api.get<HubInfo>('/info')
        return r.data
    },

    /** 列出 GitHub sources */
    listSources: async (): Promise<{ sources: HubSource[]; total: number }> => {
        const r = await api.get('/sources')
        return r.data
    },

    /** 添加 user source */
    addSource: async (ownerRepo: string) => {
        const r = await api.post('/sources', { owner_repo: ownerRepo })
        return r.data
    },

    /** 移除 source */
    removeSource: async (ownerRepo: string) => {
        const r = await api.delete(`/sources/${ownerRepo}`)
        return r.data
    },

    /** toggle enabled */
    toggleSource: async (ownerRepo: string) => {
        const r = await api.post(`/sources/${ownerRepo}/toggle`)
        return r.data
    },

    /** 触发 catalog sync (background) */
    triggerSync: async (force = false) => {
        const r = await api.post('/sync', { force })
        return r.data
    },

    /** 列出 browse layers */
    listBrowseLayers: async (): Promise<{ layers: BrowseLayer[]; total: number }> => {
        const r = await api.get('/browse-layers')
        return r.data
    },

    /** toggle browse layer */
    toggleBrowseLayer: async (layerId: string, enabled?: boolean) => {
        const r = await api.post(`/browse-layers/${layerId}/toggle`,
            enabled !== undefined ? { enabled } : {})
        return r.data
    },

    /** 实时搜索 Community Skills */
    search: async (q: string, limit = 10): Promise<HubSearchResponse> => {
        const r = await api.get('/search', { params: { q, limit } })
        return r.data
    },

    /** install — 唯一 install path (用户主动触发) */
    install: async (slug: string, source?: string) => {
        const r = await api.post('/install', { slug, ...(source ? { source } : {}) })
        return r.data
    },

    /** 列出 slug mappings */
    listMappings: async (): Promise<{ mappings: Record<string, SlugMapping>; total: number }> => {
        const r = await api.get('/slug-mapping')
        return r.data
    },

    /** 用户补 mapping */
    addMapping: async (slug: string, source: string, path = 'SKILL.md') => {
        const r = await api.post('/slug-mapping', { slug, source, path })
        return r.data
    },

    /** diff (跨源聚合 catalog) */
    diff: async (source?: string) => {
        const r = await api.get('/diff', { params: source ? { source } : {} })
        return r.data
    },
}
