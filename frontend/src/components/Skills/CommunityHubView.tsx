/**
 * CommunityHubView — W5-1 Skill Community Hub (spec §5.10 §14)
 *
 * 5 个 panel:
 * 1. Hub Status (S8)
 * 2. Browse Layers (S8)
 * 3. Filters (S9)
 * 4. Skill Grid — 4 种卡片状态 (S9)
 * 5. Detail Modal + Install 流 (S10)
 */

import React, { useEffect, useState, useCallback, useMemo } from 'react'
import { hubApi, HubInfo, BrowseLayer } from '../../api/hub'

// ── 样式 ──────────────────────────────────────────

const panel: React.CSSProperties = {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--r-lg)',
    padding: '16px',
    marginBottom: '12px',
}

const panelTitle: React.CSSProperties = {
    fontSize: '12px', fontWeight: 600, color: 'var(--text-tertiary)',
    textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '10px',
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
}

const buttonStyle = (variant: 'primary' | 'ghost' | 'warning' = 'ghost', disabled = false): React.CSSProperties => ({
    padding: '6px 12px', fontSize: '12px', fontWeight: 500,
    border: variant === 'primary' ? '1px solid var(--accent)' :
            variant === 'warning' ? '1px solid var(--warning)' : '1px solid var(--border)',
    background: variant === 'primary' ? 'var(--accent)' :
                variant === 'warning' ? 'var(--warning)' : 'transparent',
    color: variant === 'primary' || variant === 'warning' ? 'white' : 'var(--text-primary)',
    borderRadius: 'var(--r-md)', cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.5 : 1, transition: 'opacity 0.12s',
})

const inputStyle: React.CSSProperties = {
    padding: '6px 10px', fontSize: '12px',
    background: 'var(--bg-elevated)', border: '1px solid var(--border)',
    borderRadius: 'var(--r-md)', color: 'var(--text-primary)', outline: 'none',
}

const cardStyle: React.CSSProperties = {
    background: 'var(--bg-card)', border: '1px solid var(--border)',
    borderRadius: '12px', padding: '14px', display: 'flex',
    flexDirection: 'column', gap: '8px', transition: 'all 0.15s',
    cursor: 'pointer',
}

const kbdStyle: React.CSSProperties = {
    padding: '1px 5px', fontSize: '10px',
    border: '1px solid var(--border)', borderRadius: '3px',
    background: 'var(--bg-elevated)', color: 'var(--text-tertiary)',
    fontFamily: 'var(--font-mono)',
}

// ── 类型 ──────────────────────────────────────────

/** 4 种卡片状态 — 由 catalog/install 状态综合决定 */
type CardStatus = 'available' | 'installed' | 'updated' | 'browse-only'

interface HubSkill {
    name: string
    description: string
    source: string
    source_repo: string
    source_url: string
    category: string
    version: string
    /** 是否本地已装 (从 /api/hub/diff + 客户端本地索引对比得出) */
    installed: boolean
    /** 是否 mapping 缺失 (browse-only, 不能 install) */
    has_mapping: boolean
    /** 配套文件数 */
    file_count: number
    /** 字节 */
    size_bytes: number
}

// ── 主壳 ──────────────────────────────────────────

export const CommunityHubView: React.FC = () => {
    const [info, setInfo] = useState<HubInfo | null>(null)
    const [layers, setLayers] = useState<BrowseLayer[]>([])
    const [skills, setSkills] = useState<HubSkill[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [syncTriggering, setSyncTriggering] = useState(false)

    // Filters
    const [search, setSearch] = useState('')
    const [statusFilter, setStatusFilter] = useState<'all' | CardStatus>('all')
    const [sourceFilter, setSourceFilter] = useState<string>('all')

    // Detail modal
    const [detailSkill, setDetailSkill] = useState<HubSkill | null>(null)

    const refresh = useCallback(async () => {
        setLoading(true)
        setError(null)
        try {
            const [i, l, d] = await Promise.all([
                hubApi.info(),
                hubApi.listBrowseLayers(),
                hubApi.diff(),
            ])
            setInfo(i)
            setLayers(l.layers)
            // 把后端 diff 输出转成 HubSkill[]
            // 后端 /api/hub/diff 返回 MarketplaceSkill 列表 (source 来自 registry)
            // mapping 是否存在由 info.slug_mappings_count 总数判断; 单卡 has_mapping 需要查 mapping
            const mappingData = await hubApi.listMappings()
            const mappingKeys = new Set(Object.keys(mappingData.mappings))
            setSkills((d.skills || []).map((s: any) => ({
                name: s.name,
                description: s.description || '',
                source: s.source || '',
                source_repo: s.source_repo || '',
                source_url: s.source_url || '',
                category: s.category || 'general',
                version: s.version || '0.0.0',
                installed: !!s.installed,
                // marketplace 出来的 skill 默认有 source_repo, 视为有 mapping
                has_mapping: !!s.source_repo || mappingKeys.has(s.name),
                file_count: s.file_count || 0,
                size_bytes: s.size_bytes || 0,
            })))
        } catch (e: any) {
            setError(e?.response?.data?.detail || e?.message || '加载失败')
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => { refresh() }, [refresh])

    const handleSyncNow = async () => {
        setSyncTriggering(true)
        try {
            await hubApi.triggerSync(true)
            setTimeout(refresh, 3000)
        } catch (e: any) {
            setError(e?.response?.data?.detail || 'Sync 触发失败')
        } finally {
            setTimeout(() => setSyncTriggering(false), 1000)
        }
    }

    // 过滤 + 状态计算
    const filteredSkills = useMemo(() => {
        const searchLower = search.toLowerCase()
        return skills
            .filter(s => {
                if (searchLower) {
                    const hay = `${s.name} ${s.description} ${s.source_repo}`.toLowerCase()
                    if (!hay.includes(searchLower)) return false
                }
                if (sourceFilter !== 'all' && s.source_repo !== sourceFilter) return false
                if (statusFilter !== 'all') {
                    const status = computeStatus(s)
                    if (status !== statusFilter) return false
                }
                return true
            })
    }, [skills, search, sourceFilter, statusFilter])

    const sourcesList = useMemo(() => {
        const set = new Set(skills.map(s => s.source_repo).filter(Boolean))
        return ['all', ...Array.from(set).sort()]
    }, [skills])

    return (
        <div style={{
            height: '100%', overflow: 'auto', padding: '16px',
            background: 'var(--bg-secondary)',
        }}>
            {error && (
                <div style={{
                    ...panel, borderColor: 'var(--error)', color: 'var(--error)',
                    marginBottom: '12px', fontSize: '13px',
                }}>
                    ⚠️ {error}
                    <button onClick={() => setError(null)} style={{
                        ...buttonStyle(), marginLeft: '12px', fontSize: '11px',
                    }}>Dismiss</button>
                </div>
            )}

            {/* 1. Hub Status */}
            <div style={panel}>
                <div style={panelTitle}>
                    <span>Hub Status</span>
                    <button onClick={handleSyncNow} disabled={syncTriggering}
                        style={buttonStyle('primary', syncTriggering)}>
                        {syncTriggering ? '⟳ 触发中…' : '🔄 Sync Now'}
                    </button>
                </div>
                {info && (
                    <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                        <div>🟢 <b>{info.sources_total}</b> sources ({info.sources_enabled} enabled)
                            {' · '}<b>{info.sources_enabled > 0 ? skills.length : 0}</b> skills catalog
                            {' · '}<b>{info.slug_mappings_count}</b> slug mappings</div>
                        <div style={{ marginTop: '4px' }}>
                            Last sync: {info.scheduler.last_sync_at
                                ? new Date(info.scheduler.last_sync_at).toLocaleString()
                                : '(never)'}
                            {info.scheduler.last_sync_status && (
                                <span style={{ color: info.scheduler.last_sync_status === 'ok'
                                    ? 'var(--success)' : 'var(--error)' }}>
                                    {' '}— {info.scheduler.last_sync_status}
                                </span>
                            )}
                        </div>
                        {info.scheduler.last_sync_error && (
                            <div style={{ color: 'var(--error)', marginTop: '4px', fontSize: '12px' }}>
                                ⚠️ {info.scheduler.last_sync_error}
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* 2. Browse Layers */}
            <div style={panel}>
                <div style={panelTitle}>
                    <span>Browse Layers</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {layers.map(bl => (
                        <BrowseLayerRow key={bl.id} layer={bl} onChange={refresh} />
                    ))}
                </div>
            </div>

            {/* 3. Filters */}
            <div style={panel}>
                <div style={panelTitle}>
                    <span>Filters</span>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                    <input
                        type="text" placeholder="🔍 Search skills..." value={search}
                        onChange={e => setSearch(e.target.value)}
                        style={{ ...inputStyle, flex: '1 1 200px', minWidth: '160px' }}
                    />
                    <select value={statusFilter} onChange={e => setStatusFilter(e.target.value as any)}
                        style={inputStyle}>
                        <option value="all">All Status</option>
                        <option value="available">Available</option>
                        <option value="installed">Installed</option>
                        <option value="updated">Updated</option>
                        <option value="browse-only">Browse-Only</option>
                    </select>
                    <select value={sourceFilter} onChange={e => setSourceFilter(e.target.value)}
                        style={inputStyle}>
                        {sourcesList.map(src => (
                            <option key={src} value={src}>
                                {src === 'all' ? 'All Sources' : src}
                            </option>
                        ))}
                    </select>
                </div>
            </div>

            {/* 4. Skill Grid */}
            <div style={panel}>
                <div style={panelTitle}>
                    <span>Community Skills ({filteredSkills.length})</span>
                </div>
                {loading && skills.length === 0 ? (
                    <div style={{
                        padding: '32px 16px', textAlign: 'center',
                        color: 'var(--text-tertiary)', fontSize: '13px',
                    }}>
                        加载中…
                    </div>
                ) : filteredSkills.length === 0 ? (
                    <div style={{
                        padding: '32px 16px', textAlign: 'center',
                        color: 'var(--text-tertiary)', fontSize: '13px',
                    }}>
                        ✨ No skills indexed yet — click "Sync Now" or enable Browse Layers
                    </div>
                ) : (
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
                        gap: '12px',
                    }}>
                        {filteredSkills.map((s, index) => (
                            <SkillCard
                                key={`${s.name}-${s.source_repo || 'unknown'}-${s.version || '0.0.0'}-${index}`}
                                skill={s}
                                onOpen={setDetailSkill}
                            />
                        ))}
                    </div>
                )}
            </div>

            {/* Footer: 快捷键提示 */}
            <div style={{
                fontSize: '11px', color: 'var(--text-tertiary)', textAlign: 'center',
                padding: '12px 0', display: 'flex', justifyContent: 'center', gap: '12px',
            }}>
                <span><kbd style={kbdStyle}>/</kbd> 搜索</span>
                <span><kbd style={kbdStyle}>i</kbd> 在卡片上 install</span>
                <span><kbd style={kbdStyle}>Esc</kbd> 关模态</span>
            </div>

            {/* 5. Detail Modal (S10) */}
            {detailSkill && (
                <SkillDetailModal skill={detailSkill} onClose={() => setDetailSkill(null)} />
            )}
        </div>
    )
}

// ── 状态计算 ──────────────────────────────────────────

function computeStatus(s: HubSkill): CardStatus {
    if (!s.has_mapping) return 'browse-only'
    if (s.installed) return 'installed'
    // TODO: 'updated' 需要 version diff, 暂降级为 available
    return 'available'
}

// ── Browse Layer Row ──────────────────────────────────

const BrowseLayerRow: React.FC<{ layer: BrowseLayer; onChange: () => void }> = ({ layer, onChange }) => {
    const [busy, setBusy] = useState(false)
    const handleToggle = async () => {
        setBusy(true)
        try {
            await hubApi.toggleBrowseLayer(layer.id, !layer.enabled)
            onChange()
        } catch (e) { /* best-effort */ }
        finally { setBusy(false) }
    }
    return (
        <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '8px 12px', borderRadius: 'var(--r-md)',
            background: 'var(--bg-elevated)',
        }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{
                    width: 8, height: 8, borderRadius: '50%',
                    background: layer.enabled ? 'var(--success)' : 'var(--text-muted)',
                }} />
                <span style={{ fontSize: '13px', fontWeight: 500 }}>{layer.base_url}</span>
                {layer.last_sync_at && (
                    <span style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                        · last sync {new Date(layer.last_sync_at).toLocaleString()}
                    </span>
                )}
            </div>
            <button
                onClick={handleToggle}
                disabled={busy}
                style={buttonStyle(layer.enabled ? 'primary' : 'ghost', busy)}
            >
                {busy ? '…' : layer.enabled ? '✓ enabled' : 'off'}
            </button>
        </div>
    )
}

// ── Skill Card (4 种状态) ────────────────────────────

const statusBadge = (status: CardStatus): { label: string; bg: string; color: string; border: string } => {
    switch (status) {
        case 'installed': return { label: '✓ Installed', bg: 'var(--success-bg)', color: 'var(--success)', border: '1px solid var(--success)' }
        case 'updated': return { label: '⬆ Updated', bg: 'var(--warning-bg)', color: 'var(--warning)', border: '1px solid var(--warning)' }
        case 'browse-only': return { label: '.lol only', bg: 'transparent', color: 'var(--text-muted)', border: '1px dashed var(--border)' }
        case 'available':
        default: return { label: 'available', bg: 'var(--bg-elevated)', color: 'var(--text-secondary)', border: '1px solid var(--border)' }
    }
}

const SkillCard: React.FC<{ skill: HubSkill; onOpen: (s: HubSkill) => void }> = ({ skill, onOpen }) => {
    const status = computeStatus(skill)
    const badge = statusBadge(status)

    return (
        <div style={cardStyle} onClick={() => onOpen(skill)}
            onMouseEnter={e => {
                (e.currentTarget as HTMLDivElement).style.transform = 'translateY(-2px)'
                ;(e.currentTarget as HTMLDivElement).style.boxShadow = '0 4px 16px var(--shadow)'
            }}
            onMouseLeave={e => {
                (e.currentTarget as HTMLDivElement).style.transform = ''
                ;(e.currentTarget as HTMLDivElement).style.boxShadow = ''
            }}
        >
            {/* Header: name + status badge */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px' }}>
                <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '14px', fontWeight: 600,
                    color: 'var(--text-primary)',
                }}>{skill.name}</span>
                <span style={{
                    fontSize: '10px', fontWeight: 500, padding: '2px 6px',
                    borderRadius: 'var(--r-sm)',
                    background: badge.bg, color: badge.color, border: badge.border,
                }}>{badge.label}</span>
            </div>
            {/* Source */}
            <div style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                📦 {skill.source_repo || '(no source yet)'}
            </div>
            {/* Description */}
            <div style={{
                fontSize: '12px', color: 'var(--text-secondary)',
                minHeight: '36px', lineHeight: '1.4',
                display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
            }}>
                {skill.description || '(no description)'}
            </div>
            {/* Stats */}
            <div style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                {skill.file_count > 0 && <span>{skill.file_count} files · </span>}
                {(skill.size_bytes / 1024).toFixed(1)} KB
            </div>
            {/* Action — 4 种状态对应不同按钮 */}
            <CardAction skill={skill} status={status} onOpen={onOpen} />
        </div>
    )
}

const CardAction: React.FC<{ skill: HubSkill; status: CardStatus; onOpen: (s: HubSkill) => void }> = ({ skill, status, onOpen }) => {
    const handleClick = (e: React.MouseEvent) => {
        e.stopPropagation()
        onOpen(skill)
    }
    if (status === 'browse-only') {
        return (
            <a href={`https://skillhub.lol/skills/${skill.name}`} target="_blank" rel="noreferrer"
                onClick={e => e.stopPropagation()}
                style={{ ...buttonStyle(), textAlign: 'center', textDecoration: 'none' }}>
                ↗ View on skillhub.lol
            </a>
        )
    }
    if (status === 'installed') {
        return (
            <div style={{ display: 'flex', gap: '6px' }}>
                <button onClick={handleClick} style={{ ...buttonStyle(), flex: 1 }}>🔄 Reinstall</button>
            </div>
        )
    }
    // available / updated
    return (
        <button onClick={handleClick}
            style={buttonStyle(status === 'updated' ? 'warning' : 'primary')}>
            {status === 'updated' ? '⬆ Update' : '⬇ Install'}
        </button>
    )
}

// ── Detail Modal (S10) ────────────────────────────────

const SkillDetailModal: React.FC<{ skill: HubSkill; onClose: () => void }> = ({ skill, onClose }) => {
    const [installing, setInstalling] = useState(false)
    const [installResult, setInstallResult] = useState<{ kind: 'success' | 'no-source' | 'security' | 'error'; message: string } | null>(null)
    const [confirmStep, setConfirmStep] = useState(false)

    const handleInstall = async () => {
        setInstalling(true)
        try {
            const r = await hubApi.install(skill.name)
            setInstallResult({ kind: 'success', message: r.instructions || '已下载 (quarantined). 去 Local Tab 解 quarantine.' })
        } catch (e: any) {
            const detail = e?.response?.data?.detail
            if (typeof detail === 'object' && detail?.error === 'no_source_mapping') {
                setInstallResult({ kind: 'no-source', message: '无 source repo 映射. Click ↗ View 或 contribute mapping.' })
            } else if (typeof detail === 'object' && (detail?.error || '').includes('安全')) {
                setInstallResult({ kind: 'security', message: detail.error })
            } else {
                setInstallResult({ kind: 'error', message: e?.message || 'Install 失败' })
            }
        } finally {
            setInstalling(false)
            setConfirmStep(false)
        }
    }

    return (
        <div role="dialog" aria-modal="true"
            onClick={onClose}
            style={{
                position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
                display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
            }}>
            <div onClick={e => e.stopPropagation()}
                style={{
                    background: 'var(--bg-card)', border: '1px solid var(--border)',
                    borderRadius: 'var(--r-xl)', padding: '24px',
                    maxWidth: '600px', width: '90%', maxHeight: '85vh', overflow: 'auto',
                    boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
                }}>
                {/* Header */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                    <h2 style={{ margin: 0, fontSize: '18px', fontFamily: 'var(--font-mono)' }}>{skill.name}</h2>
                    <button onClick={onClose} style={{
                        ...buttonStyle(), fontSize: '16px', lineHeight: 1, padding: '4px 10px',
                    }}>×</button>
                </div>

                {/* Source info */}
                <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '12px', lineHeight: '1.8' }}>
                    <div>📦 <b>Source:</b> {skill.source_repo || '(no source)'}</div>
                    <div>📁 <b>Path:</b> {skill.source_repo ? 'SKILL.md' : '—'}</div>
                    <div>📊 <b>Category:</b> {skill.category}</div>
                    <div>📦 <b>Version:</b> {skill.version}</div>
                </div>

                {/* Description */}
                <div style={{ marginBottom: '12px' }}>
                    <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-tertiary)',
                        textTransform: 'uppercase', marginBottom: '6px' }}>Description</div>
                    <div style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: '1.5' }}>
                        {skill.description || '(no description)'}
                    </div>
                </div>

                {/* Install result toast */}
                {installResult && (
                    <div style={{
                        padding: '12px', borderRadius: 'var(--r-md)',
                        background: installResult.kind === 'success' ? 'var(--success-bg)' :
                                    installResult.kind === 'security' ? 'var(--error-bg)' : 'var(--warning-bg)',
                        color: installResult.kind === 'success' ? 'var(--success)' :
                               installResult.kind === 'security' ? 'var(--error)' : 'var(--warning)',
                        fontSize: '12px', marginBottom: '12px',
                        border: `1px solid currentColor`,
                    }}>
                        {installResult.kind === 'success' && '✓ '}
                        {installResult.kind === 'no-source' && '⚠️ '}
                        {installResult.kind === 'security' && '🚫 '}
                        {installResult.kind === 'error' && '❌ '}
                        {installResult.message}
                    </div>
                )}

                {/* Actions */}
                <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                    <button onClick={onClose} style={buttonStyle()}>Close</button>
                    {skill.source_url && (
                        <a href={skill.source_url} target="_blank" rel="noreferrer"
                            style={{ ...buttonStyle(), textDecoration: 'none' }}>
                            ↗ GitHub
                        </a>
                    )}
                    {computeStatus(skill) !== 'browse-only' && (
                        <button
                            onClick={() => setConfirmStep(true)}
                            disabled={installing || installResult?.kind === 'success'}
                            style={buttonStyle('primary', installing)}
                        >
                            {installing ? '下载中…' : '⬇ Install'}
                        </button>
                    )}
                </div>

                {/* 二次确认 toast */}
                {confirmStep && (
                    <div style={{
                        marginTop: '16px', padding: '12px',
                        background: 'var(--warning-bg)', border: '1px solid var(--warning)',
                        borderRadius: 'var(--r-md)',
                    }}>
                        <div style={{ fontSize: '13px', color: 'var(--warning)', marginBottom: '8px' }}>
                            Install <b>{skill.name}</b>?
                            <div style={{ fontSize: '11px', marginTop: '4px', color: 'var(--text-secondary)' }}>
                                Will be quarantined. Activate in <b>Local</b> tab after install.
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                            <button onClick={() => setConfirmStep(false)}
                                style={buttonStyle()}>取消</button>
                            <button onClick={handleInstall} disabled={installing}
                                style={buttonStyle('primary', installing)}>
                                {installing ? '下载中…' : '确认'}
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
