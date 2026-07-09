/**
 * SkillManagement - 技能管理主壳
 *
 * 两个子 Tab：
 * - A. 本地 Skill 管理（原 SkillManagement 行为 + 类型列/提升-降级按钮 + Phase 4 多选/隔离区/配额）
 * - B. Skill 市场（MarketplaceView）——已含已装徽章 + 重装按钮
 *
 * A/B 共享：上传/详情/删除/类型切换 走 /api/skills
 *           市场浏览/下载/重装 走 /api/marketplace
 *
 * Phase 4 新增：
 * - 本地 Tab：多选 checkbox + 批量解除/提升/降级 + 隔离区筛选 + 卡片配额显示
 * - 市场 Tab：已装 skill 徽章 + 重装按钮
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
    listSkills, deleteSkill, uploadSkill, listCategories, triggerSkill,
    patchSkillType, batchPatchSkillType, previewTokens,
    Skill, UploadResult, TokenPreviewResponse
} from '../../api/skills';
import { reinstallMarketplaceSkill } from '../../api/marketplace';
import { MarketplaceView } from '../Marketplace/MarketplaceView';
import CozeSkillsMarket from './CozeSkillsMarket';
import { CommunityHubView } from './CommunityHubView';

// ── 共享样式 ──────────────────────────────────────

const SUB_TAB_BAR: React.CSSProperties = {
    display: 'flex', borderBottom: '1px solid var(--border)',
    background: 'var(--bg-secondary)', padding: '0 16px', gap: '0',
};

const subTabStyle = (active: boolean): React.CSSProperties => ({
    padding: '10px 16px', fontSize: '13px', fontWeight: active ? 600 : 500,
    color: active ? 'var(--accent)' : 'var(--text-tertiary)',
    borderBottom: active ? '2px solid var(--accent)' : '2px solid transparent',
    cursor: 'pointer', transition: 'all 0.12s ease', marginBottom: '-1px',
    background: 'transparent', border: 'none', borderRadius: 0,
});

const TOOLBAR: React.CSSProperties = {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px',
    padding: '12px 16px', borderBottom: '1px solid var(--border)', background: 'var(--bg-surface)',
};

const sectionLabel: React.CSSProperties = {
    fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)',
    textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px',
};

const modalOverlay: React.CSSProperties = {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
};

const modalContent: React.CSSProperties = {
    background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--r-xl)',
    padding: '24px', maxWidth: '580px', width: '90%', maxHeight: '85vh', overflow: 'auto',
    boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
};

interface SkillDetail {
    name: string;
    category: string;
    metadata: Record<string, any>;
    body: string;
    has_references: boolean;
    has_templates: boolean;
}

// Phase 4: 本地 Tab 内部筛选模式
type LocalFilter = 'all' | 'quarantined' | 'system' | 'external';

// Phase 4: 格式化字节数
function formatBytes(b?: number): string {
    if (!b || b < 1024) return b ? `${b} B` : '—';
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${(b / 1024 / 1024).toFixed(2)} MB`;
}

// ── 本地 Skill 管理（A 子 Tab） ────────────────────

const LocalSkillsView: React.FC = () => {
    const [skills, setSkills] = useState<Skill[]>([]);
    const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);
    const [skillDetail, setSkillDetail] = useState<SkillDetail | null>(null);
    const [loading, setLoading] = useState(false);
    const [filter, setFilter] = useState('');
    const [localFilter, setLocalFilter] = useState<LocalFilter>('all');
    const [showHelp, setShowHelp] = useState(false);
    const [showUpload, setShowUpload] = useState(false);
    const [uploadFile, setUploadFile] = useState<File | null>(null);
    const [uploadCategory, setUploadCategory] = useState('general');
    const [uploadName, setUploadName] = useState('');
    const [uploadPreview, setUploadPreview] = useState<UploadResult | null>(null);
    const [uploading, setUploading] = useState(false);
    const [uploadError, setUploadError] = useState('');
    const [uploadDragOver, setUploadDragOver] = useState(false);
    const [categories, setCategories] = useState<string[]>(['general']);
    const [typeActionLoading, setTypeActionLoading] = useState<string | null>(null);
    // Phase 4: 多选状态
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [batchLoading, setBatchLoading] = useState(false);

    const fetchSkills = useCallback(async () => {
        setLoading(true);
        try {
            const result = await listSkills();
            setSkills(result.skills || []);
        } catch (error) {
            console.error('获取技能列表失败:', error);
        } finally {
            setLoading(false);
        }
    }, []);

    const fetchCategories = useCallback(async () => {
        try {
            const result = await listCategories();
            if (result.categories) setCategories(result.categories);
        } catch (error) {
            console.error('获取分类失败:', error);
        }
    }, []);

    useEffect(() => {
        fetchSkills();
        fetchCategories();
    }, [fetchSkills, fetchCategories]);

    // 三层过滤：搜索关键字 → 类型筛选 → 多选不在过滤里
    const filteredSkills = skills.filter(skill => {
        // 1. 文本过滤
        if (filter) {
            const q = filter.toLowerCase();
            const hit = skill.name.toLowerCase().includes(q) ||
                skill.content.toLowerCase().includes(q);
            if (!hit) return false;
        }
        // 2. 类型筛选
        if (localFilter === 'quarantined' && !skill.quarantined) return false;
        if (localFilter === 'system' && (skill.skill_type !== 'system' || skill.quarantined)) return false;
        if (localFilter === 'external' && (skill.skill_type !== 'external' || skill.quarantined)) return false;
        return true;
    });

    const handleDelete = async (skillId: string) => {
        if (!confirm('确定要删除此技能吗？')) return;
        try {
            await deleteSkill(skillId);
            setSelected(prev => { const n = new Set(prev); n.delete(skillId); return n; });
            fetchSkills();
            if (selectedSkill?.id === skillId) setSelectedSkill(null);
        } catch (error) {
            console.error('删除技能失败:', error);
        }
    };

    const viewDetail = async (skill: Skill) => {
        setSelectedSkill(skill);
        try {
            const detail = await triggerSkill(skill.name);
            setSkillDetail(detail.skill_detail || null);
        } catch {
            setSkillDetail(null);
        }
    };

    // Phase 4: 多选切换
    const toggleSelect = (name: string) => {
        setSelected(prev => {
            const n = new Set(prev);
            if (n.has(name)) n.delete(name); else n.add(name);
            return n;
        });
    };

    const toggleSelectAll = () => {
        if (selected.size === filteredSkills.length) {
            setSelected(new Set());
        } else {
            setSelected(new Set(filteredSkills.map(s => s.name)));
        }
    };

    // Phase 4: 批量操作
    const handleBatch = async (
        action: 'unquarantine' | 'promote' | 'demote' | 'delete'
    ) => {
        const names = Array.from(selected);
        if (names.length === 0) return;

        // Phase 4+: promote 走 token 预览 modal（先把名字暂存，弹 modal）
        if (action === 'promote') {
            setPromotePreviewNames(names);
            return;
        }

        let confirmMsg = '';
        let payload: any = { names: names };
        if (action === 'unquarantine') {
            confirmMsg = `确定要批量解除 ${names.length} 个 skill 的隔离吗？`;
            payload.quarantined = false;
        } else if (action === 'demote') {
            confirmMsg = `确定要批量降级 ${names.length} 个 skill 为外部吗？`;
            payload = { names, skill_type: 'external', auto_load: false };
        } else {
            confirmMsg = `确定要批量删除 ${names.length} 个 skill 吗？此操作不可逆。`;
        }

        if (!confirm(confirmMsg)) return;
        setBatchLoading(true);
        try {
            if (action === 'delete') {
                // 逐个删除（删除 API 暂未支持批量）
                for (const name of names) {
                    try { await deleteSkill(name); } catch (e) { console.error(e); }
                }
            } else {
                await batchPatchSkillType(payload);
            }
            setSelected(new Set());
            fetchSkills();
        } catch (error) {
            console.error('批量操作失败:', error);
        } finally {
            setBatchLoading(false);
        }
    };

    // Phase 4+: token 预览 modal 状态
    const [promotePreviewNames, setPromotePreviewNames] = useState<string[] | null>(null);
    const [promotePreview, setPromotePreview] = useState<TokenPreviewResponse | null>(null);
    const [promoteLoading, setPromoteLoading] = useState(false);

    useEffect(() => {
        if (!promotePreviewNames) {
            setPromotePreview(null);
            return;
        }
        setPromoteLoading(true);
        previewTokens(promotePreviewNames, true)
            .then(setPromotePreview)
            .catch(e => console.error('token 预览失败:', e))
            .finally(() => setPromoteLoading(false));
    }, [promotePreviewNames]);

    const confirmPromote = async () => {
        if (!promotePreviewNames) return;
        setPromoteLoading(true);
        try {
            await batchPatchSkillType({
                names: promotePreviewNames,
                skill_type: 'system',
                auto_load: true,
                quarantined: false,
            });
            setSelected(new Set());
            fetchSkills();
            setPromotePreviewNames(null);
        } catch (error) {
            console.error('批量提升失败:', error);
        } finally {
            setPromoteLoading(false);
        }
    };

    const handleFileSelect = (file: File) => {
        setUploadFile(file);
        setUploadError('');
        setUploadPreview(null);
        if (!uploadName) {
            const base = file.name.replace(/\.[^.]+$/, '');
            setUploadName(base.toLowerCase().replace(/[^a-z0-9-]/g, '-'));
        }
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        setUploadDragOver(false);
        const file = e.dataTransfer.files[0];
        if (file) handleFileSelect(file);
    };

    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault();
        setUploadDragOver(true);
    };

    const handleDragLeave = () => setUploadDragOver(false);

    const handleUpload = async () => {
        if (!uploadFile) return;
        setUploading(true);
        setUploadError('');
        try {
            const result = await uploadSkill(uploadFile, uploadCategory, uploadName);
            setUploadPreview(result);
            if (result.success) {
                fetchSkills();
            }
        } catch (error: any) {
            setUploadError(error.response?.data?.detail || '上传失败');
        } finally {
            setUploading(false);
        }
    };

    const toggleSkillType = async (skill: Skill) => {
        const isSystem = skill.skill_type === 'system';
        const action = isSystem ? '降级为外部' : '提升为系统';
        if (!confirm(`确定要"${action}" skill "${skill.name}" 吗？`)) return;
        setTypeActionLoading(skill.name);
        try {
            await patchSkillType(skill.id, {
                skill_type: isSystem ? 'external' : 'system',
                auto_load: !isSystem,
            });
            fetchSkills();
        } catch (error) {
            console.error('切换类型失败:', error);
        } finally {
            setTypeActionLoading(null);
        }
    };

    const toggleQuarantined = async (skill: Skill) => {
        setTypeActionLoading(skill.name);
        try {
            await patchSkillType(skill.id, { quarantined: !skill.quarantined });
            fetchSkills();
        } catch (error) {
            console.error('解除隔离失败:', error);
        } finally {
            setTypeActionLoading(null);
        }
    };

    // Phase 4: 重装市场 skill（带 source_repo 的才能重装）
    const handleReinstall = async (skill: Skill) => {
        if (!skill.source_repo) {
            alert('该 skill 没有来源仓库信息，无法重装');
            return;
        }
        if (!confirm(`确定要从 ${skill.source_repo} 重新下载 "${skill.name}" 吗？\n原文件将自动备份。`)) return;
        setTypeActionLoading(skill.name);
        try {
            const result = await reinstallMarketplaceSkill(skill.name, skill.source_repo);
            if (result.security_warnings?.length > 0) {
                alert(`重装完成，但检测到安全风险：\n${result.security_warnings.join('\n')}\n\n请检查后手动解除隔离。`);
            }
            fetchSkills();
        } catch (error: any) {
            console.error('重装失败:', error);
            alert('重装失败：' + (error.response?.data?.detail || error.message));
        } finally {
            setTypeActionLoading(null);
        }
    };

    const renderTypeBadge = (skill: Skill) => {
        const st = skill.skill_type || 'external';
        if (skill.quarantined) {
            return <span style={{ fontSize: '10px', color: 'var(--warning)', background: 'var(--warning-subtle)', padding: '1px 6px', borderRadius: 'var(--r-sm)' }}>🔒 隔离中</span>;
        }
        if (st === 'system') {
            return <span style={{ fontSize: '10px', color: 'var(--accent)', background: 'var(--accent-subtle)', padding: '1px 6px', borderRadius: 'var(--r-sm)' }}>🔒 系统</span>;
        }
        return <span style={{ fontSize: '10px', color: 'var(--text-tertiary)', background: 'var(--bg-tertiary)', padding: '1px 6px', borderRadius: 'var(--r-sm)' }}>📦 外部</span>;
    };

    // Phase 4: 类型筛选 chip 渲染
    const renderLocalFilterChip = (key: LocalFilter, label: string, count: number) => {
        const active = localFilter === key;
        return (
            <button
                key={key}
                onClick={() => setLocalFilter(key)}
                style={{
                    padding: '4px 10px', fontSize: '12px', fontWeight: active ? 600 : 500,
                    background: active ? 'var(--accent)' : 'var(--bg-elevated)',
                    color: active ? '#fff' : 'var(--text-secondary)',
                    border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
                    borderRadius: 'var(--r-sm)', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', gap: '4px',
                    transition: 'all 0.12s ease',
                }}
            >
                {label}
                <span style={{
                    fontSize: '10px', opacity: 0.8,
                    background: active ? 'rgba(255,255,255,0.2)' : 'var(--bg-tertiary)',
                    padding: '0 5px', borderRadius: '8px',
                }}>{count}</span>
            </button>
        );
    };

    // Phase 4: 统计各筛选条数
    const countByFilter = {
        all: skills.length,
        quarantined: skills.filter(s => s.quarantined).length,
        system: skills.filter(s => s.skill_type === 'system' && !s.quarantined).length,
        external: skills.filter(s => s.skill_type !== 'system' && !s.quarantined).length,
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
            {/* Toolbar */}
            <div style={TOOLBAR}>
                <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.8px' }}>
                    技能库
                </span>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <button className="btn btn-primary" onClick={() => setShowUpload(true)}>
                        + 上传 Skill
                    </button>
                    <button className="btn btn-ghost" onClick={() => setShowHelp(!showHelp)}>
                        {showHelp ? '收起帮助' : '帮助'}
                    </button>
                    <input
                        type="text" placeholder="搜索技能..." value={filter}
                        onChange={(e) => setFilter(e.target.value)} className="input" style={{ width: '200px' }}
                    />
                    <button className="btn btn-ghost" onClick={fetchSkills}>刷新</button>
                </div>
            </div>

            {/* Phase 4: 类型筛选行 */}
            <div style={{
                display: 'flex', gap: '6px', padding: '8px 16px',
                borderBottom: '1px solid var(--border)', background: 'var(--bg-surface)',
                alignItems: 'center', flexWrap: 'wrap',
            }}>
                {renderLocalFilterChip('all', '全部', countByFilter.all)}
                {renderLocalFilterChip('quarantined', '🔒 隔离区', countByFilter.quarantined)}
                {renderLocalFilterChip('system', '系统', countByFilter.system)}
                {renderLocalFilterChip('external', '外部', countByFilter.external)}

                {selected.size > 0 && (
                    <div style={{ marginLeft: 'auto', display: 'flex', gap: '6px', alignItems: 'center' }}>
                        <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>已选 {selected.size}</span>
                        <button
                            className="btn btn-ghost" style={{ fontSize: '11px', padding: '3px 8px' }}
                            onClick={() => handleBatch('unquarantine')}
                            disabled={batchLoading}
                        >🔓 批量解除隔离</button>
                        <button
                            className="btn btn-ghost" style={{ fontSize: '11px', padding: '3px 8px' }}
                            onClick={() => handleBatch('promote')}
                            disabled={batchLoading}
                        >⬆️ 批量提升</button>
                        <button
                            className="btn btn-ghost" style={{ fontSize: '11px', padding: '3px 8px' }}
                            onClick={() => handleBatch('demote')}
                            disabled={batchLoading}
                        >⬇️ 批量降级</button>
                        <button
                            className="btn btn-ghost" style={{ fontSize: '11px', padding: '3px 8px', color: 'var(--danger)' }}
                            onClick={() => handleBatch('delete')}
                            disabled={batchLoading}
                        >🗑️ 批量删除</button>
                        <button
                            className="btn btn-ghost" style={{ fontSize: '11px', padding: '3px 8px' }}
                            onClick={() => setSelected(new Set())}
                        >取消</button>
                    </div>
                )}
            </div>

            {/* Help */}
            {showHelp && (
                <div style={{
                    padding: '12px 16px', borderBottom: '1px solid var(--border)',
                    background: 'var(--bg-secondary)', fontSize: '13px', lineHeight: 1.6,
                    color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '12px',
                }}>
                    <div>
                        <strong style={{ color: 'var(--text-primary)', display: 'block', marginBottom: '4px' }}>📋 什么是 Skill？</strong>
                        <p style={{ margin: 0 }}>Skill 是 Agent 可执行的功能模块，包含触发条件、执行步骤和使用统计。</p>
                    </div>
                    <div>
                        <strong style={{ color: 'var(--text-primary)', display: 'block', marginBottom: '4px' }}>🔒 System vs 📦 External</strong>
                        <ul style={{ margin: 0, paddingLeft: '20px' }}>
                            <li style={{ marginBottom: '4px' }}><strong>System skill</strong>：每次 agent 启动自动注入完整内容到 system prompt（消耗 token，但不需要按需 skill_view）</li>
                            <li style={{ marginBottom: '4px' }}><strong>External skill</strong>：按需调用 <code>skill_view(name)</code> 加载，节省 token</li>
                            <li><strong>隔离中</strong>：从市场下载的 skill 默认状态，需要在卡片上手动解除</li>
                        </ul>
                    </div>
                    <div>
                        <strong style={{ color: 'var(--text-primary)', display: 'block', marginBottom: '4px' }}>🆕 Phase 4 增强</strong>
                        <ul style={{ margin: 0, paddingLeft: '20px' }}>
                            <li>点击卡片左侧 checkbox 进行多选，可批量解除隔离/提升/降级/删除</li>
                            <li>"隔离区" 筛选只显示从市场下载待审查的 skill</li>
                            <li>卡片底部显示文件大小，从市场下载的 skill 可点 "🔄 重装" 同步上游更新</li>
                        </ul>
                    </div>
                </div>
            )}

            {/* List */}
            <div style={{ flex: 1, overflow: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {loading ? (
                    <div className="empty-state">加载中...</div>
                ) : filteredSkills.length === 0 ? (
                    <div className="empty-state">暂无技能 — 点击右上角「上传 Skill」添加，或切到「市场」Tab 下载</div>
                ) : (
                    <>
                        {/* Phase 4: 全选行 */}
                        {filteredSkills.length > 0 && (
                            <div style={{
                                display: 'flex', alignItems: 'center', gap: '8px',
                                padding: '4px 8px', fontSize: '12px', color: 'var(--text-muted)',
                            }}>
                                <input
                                    type="checkbox"
                                    checked={selected.size > 0 && selected.size === filteredSkills.length}
                                    ref={el => { if (el) el.indeterminate = selected.size > 0 && selected.size < filteredSkills.length; }}
                                    onChange={toggleSelectAll}
                                />
                                <span>
                                    {selected.size > 0 ? `已选 ${selected.size} / ${filteredSkills.length}` : `全选 ${filteredSkills.length} 项`}
                                </span>
                            </div>
                        )}

                        {filteredSkills.map(skill => {
                            const isSelected = selected.has(skill.name);
                            return (
                                <div
                                    key={skill.id}
                                    onClick={() => viewDetail(skill)}
                                    style={{
                                        background: 'var(--bg-card)',
                                        border: `1px solid ${isSelected ? 'var(--accent)' : 'var(--border)'}`,
                                        borderRadius: 'var(--r-lg)', padding: '16px', cursor: 'pointer',
                                        transition: 'border-color 0.12s ease',
                                        boxShadow: isSelected ? '0 0 0 1px var(--accent)' : 'none',
                                    }}
                                    onMouseEnter={e => { if (!isSelected) e.currentTarget.style.borderColor = 'var(--border-hover)'; }}
                                    onMouseLeave={e => { if (!isSelected) e.currentTarget.style.borderColor = 'var(--border)'; }}
                                >
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                                        {/* Phase 4: checkbox */}
                                        <input
                                            type="checkbox"
                                            checked={isSelected}
                                            onClick={e => e.stopPropagation()}
                                            onChange={() => toggleSelect(skill.name)}
                                            style={{ cursor: 'pointer' }}
                                        />
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, minWidth: 0 }}>
                                            <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>{skill.name}</span>
                                            <span style={{
                                                fontSize: '11px', color: 'var(--text-muted)', background: 'var(--bg-elevated)',
                                                padding: '1px 6px', borderRadius: 'var(--r-sm)',
                                            }}>{skill.category}</span>
                                            {renderTypeBadge(skill)}
                                            {skill.source_repo && (
                                                <span style={{
                                                    fontSize: '10px', color: 'var(--text-tertiary)',
                                                    background: 'var(--bg-tertiary)', padding: '1px 6px', borderRadius: 'var(--r-sm)',
                                                }} title={`来源: ${skill.source_repo}`}>📦 {skill.source_repo}</span>
                                            )}
                                        </div>
                                        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                                            <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>使用 {skill.usage_count} 次</span>
                                            <span style={{ fontSize: '12px', color: skill.success_rate > 80 ? 'var(--success)' : 'var(--text-tertiary)' }}>{skill.success_rate.toFixed(0)}%</span>
                                            <span style={{ fontSize: '11px', color: 'var(--text-muted)', background: 'var(--bg-elevated)', padding: '1px 6px', borderRadius: 'var(--r-sm)' }}>v{skill.version}</span>
                                        </div>
                                    </div>
                                    <div style={{ fontSize: '13px', color: 'var(--text-tertiary)', lineHeight: 1.5, marginBottom: '8px' }}>
                                        {skill.content.substring(0, 120)}...
                                    </div>
                                    {skill.trigger_conditions.length > 0 && (
                                        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', marginBottom: '8px' }}>
                                            {skill.trigger_conditions.slice(0, 3).map((t, i) => (
                                                <span key={i} style={{ fontSize: '11px', color: 'var(--accent)', background: 'rgba(59,130,246,0.1)', padding: '1px 6px', borderRadius: 'var(--r-sm)' }}>{t}</span>
                                            ))}
                                        </div>
                                    )}
                                    {/* 操作行 */}
                                    <div
                                        onClick={e => e.stopPropagation()}
                                        style={{ display: 'flex', gap: '6px', paddingTop: '8px', borderTop: '1px solid var(--border-light)', alignItems: 'center' }}
                                    >
                                        {skill.quarantined ? (
                                            <button
                                                className="btn btn-ghost" style={{ fontSize: '11px', padding: '3px 8px', color: 'var(--warning)' }}
                                                onClick={() => toggleQuarantined(skill)}
                                                disabled={typeActionLoading === skill.name}
                                            >
                                                {typeActionLoading === skill.name ? '处理中...' : '🔓 解除隔离'}
                                            </button>
                                        ) : (
                                            <button
                                                className="btn btn-ghost" style={{ fontSize: '11px', padding: '3px 8px' }}
                                                onClick={() => toggleSkillType(skill)}
                                                disabled={typeActionLoading === skill.name}
                                            >
                                                {typeActionLoading === skill.name ? '处理中...' :
                                                    skill.skill_type === 'system' ? '⬇️ 降为外部' : '⬆️ 提升为系统'}
                                            </button>
                                        )}

                                        {/* Phase 4: 重装按钮（仅对市场来源 skill） */}
                                        {skill.source_repo && (
                                            <button
                                                className="btn btn-ghost" style={{ fontSize: '11px', padding: '3px 8px' }}
                                                onClick={() => handleReinstall(skill)}
                                                disabled={typeActionLoading === skill.name}
                                                title={`从 ${skill.source_repo} 重新下载`}
                                            >
                                                {typeActionLoading === skill.name ? '重装中...' : '🔄 重装'}
                                            </button>
                                        )}

                                        {/* Phase 4: 配额显示 */}
                                        <span style={{
                                            fontSize: '11px', color: 'var(--text-muted)',
                                            background: 'var(--bg-elevated)', padding: '1px 6px', borderRadius: 'var(--r-sm)',
                                        }}>📦 {formatBytes(skill.size_bytes)}</span>

                                        <button
                                            className="btn btn-ghost" style={{ fontSize: '11px', padding: '3px 8px', color: 'var(--danger)', marginLeft: 'auto' }}
                                            onClick={(e) => { e.stopPropagation(); handleDelete(skill.id); }}
                                        >删除</button>
                                    </div>
                                </div>
                            );
                        })}
                    </>
                )}
            </div>

            {/* Upload Modal */}
            {showUpload && (
                <div style={modalOverlay} onClick={() => setShowUpload(false)}>
                    <div style={modalContent} onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
                            <span style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)' }}>上传 Skill</span>
                            <button className="btn btn-ghost" onClick={() => setShowUpload(false)}>✕</button>
                        </div>

                        <div
                            onDrop={handleDrop} onDragOver={handleDragOver} onDragLeave={handleDragLeave}
                            style={{
                                border: `2px dashed ${uploadDragOver ? 'var(--accent)' : uploadFile ? 'var(--success)' : 'var(--border)'}`,
                                borderRadius: 'var(--r-lg)', padding: '32px', textAlign: 'center',
                                background: uploadDragOver ? 'rgba(59,130,246,0.05)' : 'var(--bg-secondary)',
                                transition: 'all 0.15s ease', marginBottom: '16px',
                                cursor: 'pointer',
                            }}
                            onClick={() => document.getElementById('skill-file-input')?.click()}
                        >
                            {uploadFile ? (
                                <div>
                                    <div style={{ fontSize: '24px', marginBottom: '8px' }}>📦</div>
                                    <div style={{ fontSize: '14px', color: 'var(--text-primary)', fontWeight: 600 }}>{uploadFile.name}</div>
                                    <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                                        {(uploadFile.size / 1024).toFixed(1)} KB — 点击重新选择
                                    </div>
                                </div>
                            ) : (
                                <div>
                                    <div style={{ fontSize: '24px', marginBottom: '8px' }}>📁</div>
                                    <div style={{ fontSize: '14px', color: 'var(--text-primary)', fontWeight: 600 }}>拖拽文件到这里，或点击选择</div>
                                    <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                                        支持: zip, md, txt, json, yaml, py, js, ts, go, sh...
                                    </div>
                                </div>
                            )}
                        </div>
                        <input
                            id="skill-file-input" type="file" accept=".zip,.md,.txt,.json,.yaml,.yml,.py,.js,.ts,.tsx,.go,.rs,.sh,.html,.css,.sql"
                            style={{ display: 'none' }}
                            onChange={e => { const f = e.target.files?.[0]; if (f) handleFileSelect(f); }}
                        />

                        <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
                            <div style={{ flex: 1 }}>
                                <div style={sectionLabel}>分类</div>
                                <select
                                    className="input" value={uploadCategory} onChange={e => setUploadCategory(e.target.value)}
                                    style={{ width: '100%' }}
                                >
                                    {categories.map(c => <option key={c} value={c}>{c}</option>)}
                                </select>
                            </div>
                            <div style={{ flex: 1 }}>
                                <div style={sectionLabel}>Skill 名称（可选）</div>
                                <input
                                    type="text" placeholder="自动从文件名提取" value={uploadName}
                                    onChange={e => setUploadName(e.target.value)} className="input" style={{ width: '100%' }}
                                />
                            </div>
                        </div>

                        {uploadPreview && (
                            <div style={{
                                background: uploadPreview.success ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
                                border: `1px solid ${uploadPreview.success ? 'var(--success)' : 'var(--danger)'}`,
                                borderRadius: 'var(--r-lg)', padding: '16px', marginBottom: '16px',
                            }}>
                                <div style={{ fontSize: '14px', fontWeight: 600, color: uploadPreview.success ? 'var(--success)' : 'var(--danger)', marginBottom: '8px' }}>
                                    {uploadPreview.success ? `✅ ${uploadPreview.message}` : `❌ ${uploadPreview.message}`}
                                </div>
                                {uploadPreview.warnings.length > 0 && (
                                    <div style={{ fontSize: '12px', color: 'var(--warning)', marginTop: '4px' }}>
                                        警告: {uploadPreview.warnings.join('; ')}
                                    </div>
                                )}
                            </div>
                        )}

                        {uploadError && (
                            <div style={{ color: 'var(--danger)', fontSize: '13px', marginBottom: '16px' }}>{uploadError}</div>
                        )}

                        <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                            <button className="btn btn-ghost" onClick={() => { setShowUpload(false); setUploadFile(null); setUploadError(''); setUploadPreview(null); }}>
                                取消
                            </button>
                            <button className="btn btn-primary" onClick={handleUpload} disabled={!uploadFile || uploading}>
                                {uploading ? '上传中...' : uploadPreview?.success ? '完成' : '上传'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Detail Modal */}
            {selectedSkill && (
                <div style={modalOverlay} onClick={() => setSelectedSkill(null)}>
                    <div style={{ ...modalContent, maxWidth: '720px' }} onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)' }}>{selectedSkill.name}</div>
                                <span style={{ fontSize: '12px', color: 'var(--text-muted)', background: 'var(--bg-elevated)', padding: '1px 8px', borderRadius: 'var(--r-sm)' }}>{selectedSkill.category}</span>
                                <span style={{ marginLeft: '8px' }}>{renderTypeBadge(selectedSkill)}</span>
                            </div>
                            <button className="btn btn-ghost" onClick={() => setSelectedSkill(null)}>✕</button>
                        </div>

                        {skillDetail && (
                            <div style={{ marginBottom: '16px' }}>
                                {skillDetail.metadata && Object.keys(skillDetail.metadata).length > 0 && (
                                    <div style={{ marginBottom: '12px' }}>
                                        <div style={sectionLabel}>Frontmatter</div>
                                        <pre style={{
                                            background: 'var(--bg-elevated)', padding: '10px',
                                            borderRadius: 'var(--r-sm)', fontSize: '12px',
                                            color: 'var(--text-secondary)', overflow: 'auto',
                                            maxHeight: '120px',
                                        }}>{JSON.stringify(skillDetail.metadata, null, 2)}</pre>
                                    </div>
                                )}
                                <div style={sectionLabel}>正文预览</div>
                                <pre style={{
                                    background: 'var(--bg-elevated)', padding: '12px',
                                    borderRadius: 'var(--r-sm)', fontSize: '13px',
                                    color: 'var(--text-secondary)', overflow: 'auto',
                                    maxHeight: '400px', whiteSpace: 'pre-wrap',
                                }}>{selectedSkill.content || '无描述'}</pre>
                            </div>
                        )}

                        <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                            <button className="btn btn-ghost" onClick={() => setSelectedSkill(null)}>关闭</button>
                            <button className="btn btn-ghost" style={{ color: 'var(--danger)' }}
                                onClick={() => { handleDelete(selectedSkill.id); setSelectedSkill(null); }}>删除</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Phase 4+: token 预览 modal（批量提升前） */}
            {promotePreviewNames && (
                <div style={modalOverlay} onClick={() => setPromotePreviewNames(null)}>
                    <div style={modalContent} onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                            <div style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>
                                ⬆️ 批量提升 {promotePreviewNames.length} 个 skill 为系统级
                            </div>
                            <button className="btn btn-ghost" onClick={() => setPromotePreviewNames(null)}>✕</button>
                        </div>

                        <div style={{
                            padding: '12px 16px', background: 'var(--warning-subtle)',
                            border: '1px solid var(--warning, #f59e0b)', borderRadius: 'var(--r-md)',
                            fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '16px', lineHeight: 1.6,
                        }}>
                            ⚠️ 提升后这 {promotePreviewNames.length} 个 skill 的内容会**每次 agent 启动时**全部注入到 system prompt。
                            请确认下方 token 估算值在你的上下文窗口预算内。
                        </div>

                        <div style={sectionLabel}>Token 估算（粗估，仅供参考）</div>
                        {promoteLoading && !promotePreview ? (
                            <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)' }}>计算中...</div>
                        ) : promotePreview ? (
                            <>
                                <div style={{
                                    background: 'var(--bg-elevated)', borderRadius: 'var(--r-md)',
                                    padding: '12px 16px', marginBottom: '12px',
                                    display: 'flex', alignItems: 'baseline', gap: '16px',
                                }}>
                                    <div>
                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>总计 tokens</div>
                                        <div style={{ fontSize: '24px', fontWeight: 700, color: 'var(--accent)' }}>
                                            {promotePreview.total_tokens.toLocaleString()}
                                        </div>
                                    </div>
                                    <div>
                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>会注入</div>
                                        <div style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text-primary)' }}>
                                            {promotePreview.system_prompt_would_inject.toLocaleString()} tokens
                                        </div>
                                    </div>
                                    <div style={{ marginLeft: 'auto', fontSize: '11px', color: 'var(--text-muted)' }}>
                                        方法: {promotePreview.method}
                                    </div>
                                </div>

                                <div style={{ maxHeight: '200px', overflow: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)' }}>
                                    <table style={{ width: '100%', fontSize: '12px', borderCollapse: 'collapse' }}>
                                        <thead style={{ background: 'var(--bg-secondary)', position: 'sticky', top: 0 }}>
                                            <tr>
                                                <th style={{ padding: '6px 10px', textAlign: 'left' }}>Skill</th>
                                                <th style={{ padding: '6px 10px', textAlign: 'right' }}>大小</th>
                                                <th style={{ padding: '6px 10px', textAlign: 'right' }}>Tokens</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {promotePreview.items.map((it, i) => (
                                                <tr key={it.name} style={{ background: i % 2 === 0 ? 'transparent' : 'var(--bg-secondary)' }}>
                                                    <td style={{ padding: '6px 10px', color: 'var(--text-primary)' }}>{it.name}</td>
                                                    <td style={{ padding: '6px 10px', textAlign: 'right', color: 'var(--text-muted)' }}>
                                                        {it.size_bytes < 1024 ? `${it.size_bytes} B` : `${(it.size_bytes / 1024).toFixed(1)} KB`}
                                                    </td>
                                                    <td style={{ padding: '6px 10px', textAlign: 'right', color: 'var(--accent)' }}>
                                                        {it.estimated_tokens.toLocaleString()}
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </>
                        ) : (
                            <div style={{ color: 'var(--text-muted)' }}>无数据</div>
                        )}

                        <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '16px' }}>
                            <button className="btn btn-ghost" onClick={() => setPromotePreviewNames(null)}>取消</button>
                            <button
                                className="btn btn-primary"
                                onClick={confirmPromote}
                                disabled={promoteLoading || !promotePreview}
                            >
                                {promoteLoading ? '执行中...' : `⬆️ 确认提升 ${promotePreviewNames.length} 个`}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

// ── 主壳 ──────────────────────────────────────────

type SubTab = 'local' | 'marketplace' | 'community';

export const SkillManagement: React.FC = () => {
    const [subTab, setSubTab] = useState<SubTab>('local');

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
            <div style={SUB_TAB_BAR}>
                <button
                    style={subTabStyle(subTab === 'local')}
                    onClick={() => setSubTab('local')}
                >
                    本地
                </button>
                <button
                    style={subTabStyle(subTab === 'marketplace')}
                    onClick={() => setSubTab('marketplace')}
                >
                    Skill 市场
                </button>
                <button
                    style={subTabStyle(subTab === 'community')}
                    onClick={() => setSubTab('community')}
                >
                    ✨ Community (Hub)
                </button>
            </div>
            <div style={{ flex: 1, overflow: 'hidden' }}>
                {subTab === 'local' && <LocalSkillsView />}
                {subTab === 'marketplace' && <><CozeSkillsMarket onInstall={() => window.location.reload()} /><MarketplaceView /></>}
                {subTab === 'community' && <CommunityHubView />}
            </div>
        </div>
    );
};
