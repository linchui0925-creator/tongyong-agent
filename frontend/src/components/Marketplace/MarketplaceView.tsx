/**
 * MarketplaceView - Skill 市场（外部 Tab）
 *
 * 功能：
 * - 源管理：列出/添加/删除 GitHub 仓库源 + 手动刷新
 * - 分类侧边栏（按 backend registry 聚合）
 * - 卡片列表（搜索 + 分类过滤）
 * - 详情 Modal（展示 source_url 跳转 GitHub）
 * - 下载（install）→ 落地后 quarantined=true，需用户在本地 Tab 激活
 *
 * 跟本地 Tab 的 SkillManagement 共享同一种深色风格
 */

import React, { useState, useEffect, useCallback } from 'react'
import {
    listMarketplaceSkills,
    listMarketplaceCategories,
    listMarketplaceSources,
    addMarketplaceSource,
    removeMarketplaceSource,
    refreshMarketplace,
    installMarketplaceSkill,
    reinstallMarketplaceSkill,
    MarketplaceSkill,
    MarketplaceCategory,
} from '../../api/marketplace'

// ── 样式 ──────────────────────────────────────────

const containerStyle: React.CSSProperties = {
    display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden',
}

const toolbarStyle: React.CSSProperties = {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px',
    padding: '12px 16px', borderBottom: '1px solid var(--border)',
    background: 'var(--bg-secondary)',
}

const sectionLabel: React.CSSProperties = {
    fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)',
    textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px',
}

const modalOverlay: React.CSSProperties = {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
}

const modalContent: React.CSSProperties = {
    background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--r-xl)',
    padding: '24px', maxWidth: '720px', width: '90%', maxHeight: '85vh', overflow: 'auto',
    boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
}

// ── 主组件 ────────────────────────────────────────

export const MarketplaceView: React.FC<{ onInstalled?: () => void }> = ({ onInstalled }) => {
    const [skills, setSkills] = useState<MarketplaceSkill[]>([])
    const [categories, setCategories] = useState<MarketplaceCategory[]>([])
    const [sources, setSources] = useState<string[]>([])
    const [search, setSearch] = useState('')
    const [activeCategory, setActiveCategory] = useState<string>('')
    const [activeSource, setActiveSource] = useState<string>('')
    const [loading, setLoading] = useState(false)
    const [refreshing, setRefreshing] = useState(false)
    const [error, setError] = useState('')
    const [showAddSource, setShowAddSource] = useState(false)
    const [newSource, setNewSource] = useState('')
    const [adding, setAdding] = useState(false)
    const [selected, setSelected] = useState<MarketplaceSkill | null>(null)
    const [installing, setInstalling] = useState<string | null>(null)
    const [installResult, setInstallResult] = useState<string>('')

    // ── 数据加载 ──────────────────────────────────

    const loadAll = useCallback(async () => {
        setLoading(true)
        setError('')
        try {
            const [listRes, catsRes, srcRes] = await Promise.all([
                listMarketplaceSkills({
                    search: search || undefined,
                    category: activeCategory || undefined,
                    source: activeSource || undefined,
                    page_size: 100,
                }),
                listMarketplaceCategories(),
                listMarketplaceSources(),
            ])
            setSkills(listRes.skills || [])
            setCategories(catsRes.categories || [])
            setSources(srcRes.sources || [])
        } catch (e: any) {
            setError(e?.response?.data?.detail || e?.message || '加载失败')
        } finally {
            setLoading(false)
        }
    }, [search, activeCategory, activeSource])

    useEffect(() => {
        loadAll()
    }, [loadAll])

    // ── 源管理 ────────────────────────────────────

    const handleAddSource = async () => {
        if (!newSource.trim()) return
        setAdding(true)
        setError('')
        try {
            const result = await addMarketplaceSource(newSource.trim())
            if (!result.ok) {
                setError(result.error || '添加失败')
                return
            }
            setShowAddSource(false)
            setNewSource('')
            await loadAll()
        } catch (e: any) {
            setError(e?.response?.data?.detail || e?.message || '添加失败')
        } finally {
            setAdding(false)
        }
    }

    const handleRemoveSource = async (src: string) => {
        if (!confirm(`确定移除源 ${src} 吗？\n（已下载到本地的 skill 不会删除）`)) return
        try {
            await removeMarketplaceSource(src)
            if (activeSource === src) setActiveSource('')
            await loadAll()
        } catch (e: any) {
            setError(e?.response?.data?.detail || e?.message || '移除失败')
        }
    }

    const handleRefresh = async () => {
        setRefreshing(true)
        setError('')
        try {
            await refreshMarketplace({ force: true })
            await loadAll()
        } catch (e: any) {
            setError(e?.response?.data?.detail || e?.message || '刷新失败')
        } finally {
            setRefreshing(false)
        }
    }

    // ── 安装 ──────────────────────────────────────

    const handleInstall = async (skill: MarketplaceSkill) => {
        // Phase 4 续 C: 配套文件 confirm 提示
        const fc = skill.file_count ?? 0
        const msg = fc > 0
            ? `确定要下载并安装 "${skill.name}" 吗？\n\n` +
              `• 主文件: SKILL.md (${skill.size_bytes} B)\n` +
              `• 配套文件: ${fc} 个 (${(skill.total_size_bytes ?? skill.size_bytes) - skill.size_bytes} B)\n` +
              `• 落地路径: ~/.hermes/profiles/<profile>/skills/<category>/<name>/\n\n` +
              `安装后默认 quarantined=true，需在「本地」Tab 手动解除。`
            : `确定要下载并安装 "${skill.name}" 吗？\n（仅 1 个 SKILL.md，无配套文件）\n\n安装后默认 quarantined=true。`
        if (!confirm(msg)) return
        setInstalling(skill.name)
        setInstallResult('')
        try {
            const result = await installMarketplaceSkill(skill.name, skill.source)
            const total = result.total_files ?? 0
            const skipped = (result.files_skipped || []).length
            const failed = (result.files_failed || []).length
            const parts = [`✅ 已安装: ${result.path}`]
            if (total > 0) {
                parts.push(`下载 ${total} 个配套文件`)
                if (skipped > 0) parts.push(`跳过 ${skipped}`)
                if (failed > 0) parts.push(`失败 ${failed}`)
            }
            parts.push('（quarantined=true，待激活）')
            setInstallResult(parts.join(' · '))
            // 刷新列表，更新 installed 状态
            await loadAll()
            onInstalled?.()
        } catch (e: any) {
            setInstallResult(`❌ 安装失败: ${e?.response?.data?.detail || e?.message}`)
        } finally {
            setInstalling(null)
        }
    }

    const handleReinstall = async (skill: MarketplaceSkill) => {
        const fc = skill.file_count ?? 0
        const msg = fc > 0
            ? `确定要从 ${skill.source_repo} 重新下载 "${skill.name}" 吗？\n\n` +
              `将下载 ${fc} 个配套文件，原 skill 目录会自动备份。`
            : `确定要从 ${skill.source_repo} 重新下载 "${skill.name}" 吗？\n原文件将自动备份。`
        if (!confirm(msg)) return
        setInstalling(skill.name)
        setInstallResult('')
        try {
            const result = await reinstallMarketplaceSkill(skill.name, skill.source)
            const warn = result.security_warnings?.length
                ? `\n⚠️ 安全警告: ${result.security_warnings.join('; ')}`
                : ''
            // Phase 4 续 C: 显示配套文件下载结果
            const total = (result as any).total_files ?? 0
            const parts: string[] = [`🔄 重装完成`]
            if (result.backup) parts.push(`(备份: ${(result.backup as string).split('/').pop()})`)
            if (total > 0) parts.push(`下载 ${total} 个配套文件`)
            setInstallResult(parts.join(' · ') + warn)
            await loadAll()
            onInstalled?.()
        } catch (e: any) {
            setInstallResult(`❌ 重装失败: ${e?.response?.data?.detail || e?.message}`)
        } finally {
            setInstalling(null)
        }
    }

    // ── 渲染 ──────────────────────────────────────

    return (
        <div style={containerStyle}>
            {/* Toolbar */}
            <div style={toolbarStyle}>
                <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.8px' }}>
                    Skill 市场
                </span>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <button className="btn btn-primary" onClick={() => setShowAddSource(true)}>
                        + 添加源
                    </button>
                    <button
                        className="btn btn-ghost"
                        onClick={handleRefresh}
                        disabled={refreshing || sources.length === 0}
                        title={sources.length === 0 ? '请先添加源' : '强制刷新所有源'}
                    >
                        {refreshing ? '刷新中...' : '🔄 刷新'}
                    </button>
                    <input
                        type="text" placeholder="搜索 skill..." value={search}
                        onChange={e => setSearch(e.target.value)} className="input" style={{ width: '200px' }}
                    />
                </div>
            </div>

            {/* 错误提示 */}
            {error && (
                <div style={{
                    padding: '8px 16px', background: 'var(--danger-subtle)', color: 'var(--danger)',
                    fontSize: '13px', borderBottom: '1px solid var(--border)',
                }}>
                    ⚠️ {error}
                </div>
            )}
            {installResult && (
                <div style={{
                    padding: '8px 16px', background: 'var(--success-subtle)', color: 'var(--success)',
                    fontSize: '13px', borderBottom: '1px solid var(--border)',
                }}>
                    {installResult}
                </div>
            )}

            {/* 主体：源管理条 + 侧栏 + 卡片列表 */}
            <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
                {/* 侧栏：源 + 分类 */}
                <div style={{
                    width: '220px', borderRight: '1px solid var(--border)',
                    background: 'var(--bg-secondary)', overflow: 'auto', padding: '12px 0',
                }}>
                    <div style={{ padding: '0 16px', marginBottom: '16px' }}>
                        <div style={sectionLabel}>仓库源（{sources.length}）</div>
                        {sources.length === 0 ? (
                            <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                                暂无源，点击右上角"+ 添加源"开始
                            </div>
                        ) : (
                            sources.map(src => (
                                <div key={src} style={{
                                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                    padding: '6px 8px', borderRadius: 'var(--r-md)', cursor: 'pointer',
                                    background: activeSource === src ? 'var(--bg-hover)' : 'transparent',
                                    marginBottom: '2px',
                                }}>
                                    <span
                                        onClick={() => setActiveSource(activeSource === src ? '' : src)}
                                        style={{ fontSize: '12px', color: 'var(--text-secondary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                                        title={src}
                                    >
                                        {src}
                                    </span>
                                    <button
                                        className="btn btn-ghost" style={{ fontSize: '11px', padding: '0 4px' }}
                                        onClick={() => handleRemoveSource(src)}
                                        title="移除"
                                    >×</button>
                                </div>
                            ))
                        )}
                    </div>

                    <div style={{ padding: '0 16px' }}>
                        <div style={sectionLabel}>分类</div>
                        <div
                            onClick={() => setActiveCategory('')}
                            style={{
                                padding: '6px 8px', fontSize: '12px', cursor: 'pointer',
                                borderRadius: 'var(--r-md)', marginBottom: '2px',
                                background: activeCategory === '' ? 'var(--bg-hover)' : 'transparent',
                                color: activeCategory === '' ? 'var(--accent)' : 'var(--text-secondary)',
                            }}
                        >全部 ({categories.reduce((s, c) => s + c.count, 0)})</div>
                        {categories.map(c => (
                            <div
                                key={c.name}
                                onClick={() => setActiveCategory(activeCategory === c.name ? '' : c.name)}
                                style={{
                                    padding: '6px 8px', fontSize: '12px', cursor: 'pointer',
                                    borderRadius: 'var(--r-md)', marginBottom: '2px',
                                    background: activeCategory === c.name ? 'var(--bg-hover)' : 'transparent',
                                    color: activeCategory === c.name ? 'var(--accent)' : 'var(--text-secondary)',
                                }}
                            >
                                {c.name} ({c.count})
                            </div>
                        ))}
                    </div>
                </div>

                {/* 主区：卡片列表 */}
                <div style={{ flex: 1, overflow: 'auto', padding: '16px' }}>
                    {loading ? (
                        <div className="empty-state">加载中...</div>
                    ) : sources.length === 0 ? (
                        <div className="empty-state">
                            <div style={{ fontSize: '48px', marginBottom: '12px' }}>🌐</div>
                            <div style={{ fontSize: '14px', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                                还没有添加任何源
                            </div>
                            <div style={{ fontSize: '12px', color: 'var(--text-muted)', maxWidth: '400px', textAlign: 'center' }}>
                                点击右上角"+ 添加源"，输入 GitHub 仓库（如 <code>owner/repo</code>）即可拉取该仓库中的所有 SKILL.md。
                                下载后默认 quarantined=true，需要在「本地」Tab 手动激活。
                            </div>
                        </div>
                    ) : skills.length === 0 ? (
                        <div className="empty-state">
                            {(search || activeCategory || activeSource)
                                ? '没有匹配的 skill — 试试清空筛选'
                                : '该源下还没有发现 skill — 点击"🔄 刷新"拉取最新内容'}
                        </div>
                    ) : (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '12px' }}>
                            {skills.map(skill => (
                                <div
                                    key={`${skill.source}::${skill.name}`}
                                    onClick={() => setSelected(skill)}
                                    style={{
                                        background: 'var(--bg-card)', border: '1px solid var(--border)',
                                        borderRadius: 'var(--r-lg)', padding: '14px', cursor: 'pointer',
                                        transition: 'border-color 0.12s ease, transform 0.1s ease',
                                    }}
                                    onMouseEnter={e => {
                                        e.currentTarget.style.borderColor = 'var(--accent)'
                                        e.currentTarget.style.transform = 'translateY(-1px)'
                                    }}
                                    onMouseLeave={e => {
                                        e.currentTarget.style.borderColor = 'var(--border)'
                                        e.currentTarget.style.transform = 'translateY(0)'
                                    }}
                                >
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0, flexWrap: 'wrap' }}>
                                            <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>{skill.name}</span>
                                            {/* Phase 4+: 已装徽章 */}
                                            {skill.installed && (
                                                <span style={{
                                                    fontSize: '9px', color: 'var(--success, #22c55e)',
                                                    background: 'var(--success-subtle, rgba(34,197,94,0.1))',
                                                    padding: '1px 5px', borderRadius: 'var(--r-sm)',
                                                    fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.3px',
                                                    border: '1px solid var(--success, rgba(34,197,94,0.3))',
                                                }} title={skill.local_quarantined ? '已下载（隔离中）' : '已激活'}>
                                                    {skill.local_quarantined ? '🔒 已下载' : '✓ 已装'}
                                                </span>
                                            )}
                                            {/* Phase 4 续 C: 配套文件数徽章 */}
                                            {(skill.file_count ?? 0) > 0 && (
                                                <span style={{
                                                    fontSize: '9px', color: 'var(--text-secondary)',
                                                    background: 'var(--bg-tertiary)',
                                                    padding: '1px 5px', borderRadius: 'var(--r-sm)',
                                                    fontWeight: 600,
                                                    border: '1px solid var(--border)',
                                                }} title={`${skill.file_count} 个配套文件, 约 ${Math.round(((skill.total_size_bytes ?? skill.size_bytes) - skill.size_bytes) / 1024)} KB`}>
                                                    📎 +{skill.file_count}
                                                </span>
                                            )}
                                        </div>
                                        <span style={{
                                            fontSize: '10px', color: 'var(--text-muted)',
                                            background: 'var(--bg-tertiary)', padding: '2px 6px', borderRadius: 'var(--r-sm)',
                                        }}>{skill.category}</span>
                                    </div>
                                    <div style={{
                                        fontSize: '12px', color: 'var(--text-tertiary)', lineHeight: 1.5,
                                        marginBottom: '10px', minHeight: '36px',
                                        display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                                        overflow: 'hidden',
                                    }}>
                                        {skill.description || '（无描述）'}
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                                        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', flex: 1 }}>
                                            {skill.tags.slice(0, 2).map((t, i) => (
                                                <span key={i} style={{
                                                    fontSize: '10px', color: 'var(--accent)',
                                                    background: 'var(--accent-subtle)', padding: '1px 5px', borderRadius: 'var(--r-sm)',
                                                }}>{t}</span>
                                            ))}
                                        </div>
                                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>v{skill.version}</span>
                                    </div>
                                    <div style={{ marginTop: '10px', fontSize: '11px', color: 'var(--text-muted)' }}>
                                        📦 {skill.source_repo}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {/* 添加源 Modal */}
            {showAddSource && (
                <div style={modalOverlay} onClick={() => setShowAddSource(false)}>
                    <div style={modalContent} onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
                            <span style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)' }}>添加 GitHub 源</span>
                            <button className="btn btn-ghost" onClick={() => setShowAddSource(false)}>✕</button>
                        </div>
                        <div style={sectionLabel}>仓库地址</div>
                        <input
                            type="text" placeholder="owner/repo（如 Anthropic/skills）"
                            value={newSource} onChange={e => setNewSource(e.target.value)}
                            className="input" style={{ width: '100%', marginBottom: '12px' }}
                            onKeyDown={e => { if (e.key === 'Enter') handleAddSource() }}
                        />
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '16px', lineHeight: 1.6 }}>
                            • 仓库中所有 <code>SKILL.md</code> 文件会被扫描<br />
                            • 第一次添加会立即拉取（可能需要 10-30 秒）<br />
                            • 之后会缓存 24h，或手动"🔄 刷新"强制更新
                        </div>
                        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                            <button className="btn btn-ghost" onClick={() => setShowAddSource(false)}>取消</button>
                            <button
                                className="btn btn-primary"
                                onClick={handleAddSource}
                                disabled={adding || !newSource.trim()}
                            >
                                {adding ? '添加中...' : '添加并刷新'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* 详情 + 安装 Modal */}
            {selected && (
                <div style={modalOverlay} onClick={() => setSelected(null)}>
                    <div style={modalContent} onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                            <div>
                                <div style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text-primary)' }}>{selected.name}</div>
                                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                                    {selected.category} · v{selected.version} · {selected.size_bytes} bytes
                                </div>
                            </div>
                            <button className="btn btn-ghost" onClick={() => setSelected(null)}>✕</button>
                        </div>

                        <div style={sectionLabel}>简介</div>
                        <div style={{
                            fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6,
                            marginBottom: '16px', padding: '12px',
                            background: 'var(--bg-inset)', borderRadius: 'var(--r-md)',
                        }}>
                            {selected.description || '（无描述）'}
                        </div>

                        {selected.tags.length > 0 && (
                            <>
                                <div style={sectionLabel}>标签</div>
                                <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginBottom: '16px' }}>
                                    {selected.tags.map((t, i) => (
                                        <span key={i} style={{
                                            fontSize: '11px', color: 'var(--accent)',
                                            background: 'var(--accent-subtle)', padding: '2px 8px', borderRadius: 'var(--r-sm)',
                                        }}>{t}</span>
                                    ))}
                                </div>
                            </>
                        )}

                        <div style={sectionLabel}>来源</div>
                        <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '16px', lineHeight: 1.5 }}>
                            <div>仓库: <code>{selected.source_repo}</code></div>
                            <div>路径: <code>{selected.source_path}</code></div>
                            <div style={{ marginTop: '4px' }}>
                                <a href={selected.source_url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)' }}>
                                    在 GitHub 上查看 →
                                </a>
                            </div>
                        </div>

                        {/* Phase 4 续 C: 配套文件清单预览 */}
                        {selected.files && selected.files.length > 0 && (() => {
                            const skillMdPath = selected.source_path
                            const extraFiles = selected.files.filter(f => f.path !== skillMdPath)
                            const totalExtra = extraFiles.length
                            const totalBytes = extraFiles.reduce((s, f) => s + (f.size || 0), 0)
                            const fmtBytes = (n: number) => n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`
                            // 按目录分组
                            const groups: Record<string, { path: string; size: number }[]> = {}
                            for (const f of extraFiles) {
                                // 取 path 相对 skill 目录的父目录, 如 "forms.md" → "" (根), "references/x.md" → "references"
                                const relParts = f.path.split('/')
                                relParts.pop()  // 去文件名
                                // 去掉 skill 所在目录 (path 的前 N 段)
                                const skillParts = (skillMdPath || '').split('/')
                                skillParts.pop()  // 去掉 SKILL.md
                                const dirParts = relParts.slice(skillParts.length)
                                const dir = dirParts.join('/') || '(skill 根目录)'
                                if (!groups[dir]) groups[dir] = []
                                groups[dir].push({ path: f.path.split('/').pop() || f.path, size: f.size })
                            }
                            return (
                                <>
                                    <div style={sectionLabel}>
                                        配套文件 ({totalExtra} 个 · {fmtBytes(totalBytes)})
                                    </div>
                                    <div style={{
                                        fontSize: '12px',
                                        background: 'var(--bg-inset)',
                                        border: '1px solid var(--border)',
                                        borderRadius: 'var(--r-md)',
                                        padding: '8px 12px',
                                        marginBottom: '16px',
                                        maxHeight: '180px',
                                        overflowY: 'auto',
                                    }}>
                                        {Object.entries(groups).map(([dir, files]) => (
                                            <div key={dir} style={{ marginBottom: dir === '(skill 根目录)' ? 0 : '6px' }}>
                                                {dir !== '(skill 根目录)' && (
                                                    <div style={{
                                                        fontSize: '10px', fontWeight: 600, color: 'var(--text-muted)',
                                                        textTransform: 'uppercase', letterSpacing: '0.5px',
                                                        marginBottom: '2px', marginTop: '4px',
                                                    }}>
                                                        📁 {dir}/
                                                    </div>
                                                )}
                                                {files.map((f, i) => (
                                                    <div key={i} style={{
                                                        display: 'flex', justifyContent: 'space-between',
                                                        color: 'var(--text-secondary)', paddingLeft: dir === '(skill 根目录)' ? 0 : '12px',
                                                        lineHeight: 1.7, fontSize: '12px',
                                                    }}>
                                                        <span>📄 {f.path}</span>
                                                        <span style={{ color: 'var(--text-muted)', fontFamily: 'monospace' }}>{fmtBytes(f.size)}</span>
                                                    </div>
                                                ))}
                                            </div>
                                        ))}
                                    </div>
                                </>
                            )
                        })()}

                        {/* Phase 4+: 本地状态 */}
                        {selected.installed && (
                            <div style={{
                                padding: '10px 12px',
                                background: 'var(--success-subtle, rgba(34,197,94,0.1))',
                                border: '1px solid var(--success, rgba(34,197,94,0.4))',
                                borderRadius: 'var(--r-md)',
                                fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: 1.6,
                            }}>
                                <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--success)', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                                    ✓ 本地已安装
                                </div>
                                <div>类型: {selected.local_skill_type === 'system' ? '🔒 系统' : '📦 外部'}</div>
                                <div>状态: {selected.local_quarantined ? '🔒 隔离中（需要去「本地」Tab 解除）' : '✅ 已激活'}</div>
                            </div>
                        )}

                        <div style={{
                            padding: '10px 12px', background: 'var(--warning-subtle)',
                            border: '1px solid var(--accent-border)', borderRadius: 'var(--r-md)',
                            fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: 1.5,
                        }}>
                            {!selected.installed
                                ? '⚠️ 安装后默认 quarantined=true，不会出现在 agent 索引中。\n切换到「本地」Tab，手动把 quarantined 关掉才能用。'
                                : selected.local_quarantined
                                    ? '⚠️ 该 skill 已下载但仍处于隔离状态，去「本地」Tab 解除后才能用。'
                                    : '✅ 该 skill 已激活，会被 agent 使用。'}
                        </div>

                        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                            <button className="btn btn-ghost" onClick={() => setSelected(null)}>关闭</button>
                            {selected.installed ? (
                                <button
                                    className="btn btn-primary"
                                    onClick={() => handleReinstall(selected)}
                                    disabled={installing === selected.name}
                                >
                                    {installing === selected.name ? '重装中...' : '🔄 重装'}
                                </button>
                            ) : (
                                <button
                                    className="btn btn-primary"
                                    onClick={() => handleInstall(selected)}
                                    disabled={installing === selected.name}
                                >
                                    {installing === selected.name ? '下载中...' : '📥 下载并安装'}
                                </button>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default MarketplaceView
