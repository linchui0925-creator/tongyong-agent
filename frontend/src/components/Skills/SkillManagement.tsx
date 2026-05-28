import React, { useState, useEffect, useCallback } from 'react';
import { listSkills, deleteSkill, uploadSkill, listCategories, triggerSkill, Skill, UploadResult } from '../../api/skills';

interface SkillDetail {
    name: string;
    category: string;
    metadata: Record<string, any>;
    body: string;
    has_references: boolean;
    has_templates: boolean;
}

export const SkillManagement: React.FC = () => {
    const [skills, setSkills] = useState<Skill[]>([]);
    const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);
    const [skillDetail, setSkillDetail] = useState<SkillDetail | null>(null);
    const [loading, setLoading] = useState(false);
    const [filter, setFilter] = useState('');
    const [showHelp, setShowHelp] = useState(false);

    // 上传相关状态
    const [showUpload, setShowUpload] = useState(false);
    const [uploadFile, setUploadFile] = useState<File | null>(null);
    const [uploadCategory, setUploadCategory] = useState('general');
    const [uploadName, setUploadName] = useState('');
    const [uploadPreview, setUploadPreview] = useState<UploadResult | null>(null);
    const [uploading, setUploading] = useState(false);
    const [uploadError, setUploadError] = useState('');
    const [uploadDragOver, setUploadDragOver] = useState(false);
    const [categories, setCategories] = useState<string[]>(['general']);

    const fetchSkills = useCallback(async () => {
        setLoading(true);
        try {
            const data = await listSkills();
            setSkills(data.skills || []);
        } catch (error) {
            console.error('获取技能列表失败:', error);
        } finally {
            setLoading(false);
        }
    }, []);

    const fetchCategories = useCallback(async () => {
        try {
            const data = await listCategories();
            setCategories(data.categories);
        } catch (error) {
            console.error('获取分类失败:', error);
        }
    }, []);

    useEffect(() => {
        fetchSkills();
        fetchCategories();
    }, [fetchSkills, fetchCategories]);

    const filteredSkills = skills.filter(skill =>
        skill.name.toLowerCase().includes(filter.toLowerCase()) ||
        skill.content.toLowerCase().includes(filter.toLowerCase())
    );

    const handleDelete = async (skillId: string) => {
        if (!confirm('确定要删除此技能吗？')) return;
        try {
            await deleteSkill(skillId);
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

    // 上传相关
    const handleFileSelect = (file: File) => {
        const ext = file.name.split('.').pop()?.toLowerCase() || '';
        const allowed = ['zip', 'md', 'txt', 'json', 'yaml', 'yml', 'py', 'js', 'ts', 'tsx', 'go', 'rs', 'sh', 'html', 'css', 'sql'];
        if (!allowed.includes(ext)) {
            setUploadError(`不支持的文件类型: .${ext}`);
            return;
        }
        setUploadFile(file);
        setUploadError('');
        setUploadPreview(null);
    };

    const handleUpload = async () => {
        if (!uploadFile) return;
        setUploading(true);
        setUploadError('');
        setUploadPreview(null);
        try {
            const result = await uploadSkill(uploadFile, uploadCategory, uploadName || undefined);
            setUploadPreview(result);
            if (result.success) {
                fetchSkills();
                setTimeout(() => {
                    setShowUpload(false);
                    setUploadFile(null);
                    setUploadName('');
                    setUploadPreview(null);
                }, 2000);
            }
        } catch (err: any) {
            setUploadError(err?.response?.data?.detail || '上传失败');
        } finally {
            setUploading(false);
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

    // 样式
    const modalOverlay: React.CSSProperties = {
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    };
    const modalContent: React.CSSProperties = {
        background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 'var(--r-xl)',
        padding: '24px', maxWidth: '580px', width: '90%', maxHeight: '85vh', overflow: 'auto',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
    };
    const sectionLabel: React.CSSProperties = {
        fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)',
        textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '6px',
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
            {/* Toolbar */}
            <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px',
                padding: '12px 16px', borderBottom: '1px solid var(--border)', background: 'var(--bg-surface)',
            }}>
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

            {/* Help */}
            {showHelp && (
                <div style={{
                    padding: '12px 16px', borderBottom: '1px solid var(--border)',
                    background: 'var(--bg-secondary)', fontSize: '13px', lineHeight: 1.6,
                    color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '12px',
                }}>
                    <div>
                        <strong style={{ color: 'var(--text-primary)', display: 'block', marginBottom: '4px' }}>📋 什么是 Skill？</strong>
                        <p style={{ margin: 0 }}>Skill 是 Agent 可执行的功能模块，包含触发条件、执行步骤和使用统计。你可以通过上传文件（zip、md、json 等）来创建新的 Skill。</p>
                    </div>
                    <div>
                        <strong style={{ color: 'var(--text-primary)', display: 'block', marginBottom: '4px' }}>📖 上传说明</strong>
                        <ul style={{ margin: 0, paddingLeft: '20px' }}>
                            <li style={{ marginBottom: '4px' }}><strong>.zip</strong> — 解压后读取所有文本文件，自动提取 trigger 和 steps</li>
                            <li style={{ marginBottom: '4px' }}><strong>.md/.txt</strong> — 直接解析内容，提取步骤和描述</li>
                            <li style={{ marginBottom: '4px' }}><strong>.json/.yaml</strong> — 尝试读取 name/description/steps/triggers 字段</li>
                            <li>支持文件: zip, md, txt, json, yaml, py, js, ts, go, sh, html, css, sql</li>
                        </ul>
                    </div>
                    <div>
                        <strong style={{ color: 'var(--text-primary)', display: 'block', marginBottom: '4px' }}>🔄 自动触发</strong>
                        <p style={{ margin: 0 }}>上传后的 Skill 会被 Agent 自动匹配。当你描述相关需求时，Agent 会自动调用匹配的 Skill 执行任务。</p>
                    </div>
                </div>
            )}

            {/* List */}
            <div style={{ flex: 1, overflow: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {loading ? (
                    <div className="empty-state">加载中...</div>
                ) : filteredSkills.length === 0 ? (
                    <div className="empty-state">暂无技能 — 点击右上角「上传 Skill」添加</div>
                ) : (
                    filteredSkills.map(skill => (
                        <div
                            key={skill.id}
                            onClick={() => viewDetail(skill)}
                            style={{
                                background: 'var(--bg-card)', border: '1px solid var(--border)',
                                borderRadius: 'var(--r-lg)', padding: '16px', cursor: 'pointer',
                                transition: 'border-color 0.12s ease',
                            }}
                            onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--border-hover)')}
                            onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}
                        >
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>{skill.name}</span>
                                    <span style={{
                                        fontSize: '11px', color: 'var(--text-muted)', background: 'var(--bg-elevated)',
                                        padding: '1px 6px', borderRadius: 'var(--r-sm)',
                                    }}>{skill.category}</span>
                                </div>
                                <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                                    <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>使用 {skill.usage_count} 次</span>
                                    <span style={{ fontSize: '12px', color: skill.success_rate > 80 ? 'var(--success)' : 'var(--text-tertiary)' }}>{skill.success_rate.toFixed(0)}%</span>
                                    <span style={{ fontSize: '11px', color: 'var(--text-muted)', background: 'var(--bg-elevated)', padding: '1px 6px', borderRadius: 'var(--r-sm)' }}>v{skill.version}</span>
                                    <button
                                        className="btn btn-ghost" style={{ fontSize: '12px', padding: '2px 6px' }}
                                        onClick={(e) => { e.stopPropagation(); handleDelete(skill.id); }}
                                    >删除</button>
                                </div>
                            </div>
                            <div style={{ fontSize: '13px', color: 'var(--text-tertiary)', lineHeight: 1.5, marginBottom: '4px' }}>
                                {skill.content.substring(0, 120)}...
                            </div>
                            {skill.trigger_conditions.length > 0 && (
                                <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                                    {skill.trigger_conditions.slice(0, 3).map((t, i) => (
                                        <span key={i} style={{ fontSize: '11px', color: 'var(--accent)', background: 'rgba(59,130,246,0.1)', padding: '1px 6px', borderRadius: 'var(--r-sm)' }}>{t}</span>
                                    ))}
                                </div>
                            )}
                        </div>
                    ))
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

                        {/* 拖拽上传区 */}
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

                        {/* 分类和名称 */}
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

                        {/* 上传结果预览 */}
                        {uploadPreview && (
                            <div style={{
                                background: uploadPreview.success ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
                                border: `1px solid ${uploadPreview.success ? 'var(--success)' : 'var(--danger)'}`,
                                borderRadius: 'var(--r-lg)', padding: '16px', marginBottom: '16px',
                            }}>
                                <div style={{ fontSize: '14px', fontWeight: 600, color: uploadPreview.success ? 'var(--success)' : 'var(--danger)', marginBottom: '8px' }}>
                                    {uploadPreview.success ? `✅ ${uploadPreview.message}` : `❌ ${uploadPreview.message}`}
                                </div>
                                {uploadPreview.parsed_triggers.length > 0 && (
                                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                                        <strong>触发条件:</strong> {uploadPreview.parsed_triggers.join(', ')}
                                    </div>
                                )}
                                {uploadPreview.parsed_steps.length > 0 && (
                                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                                        <strong>执行步骤:</strong> {uploadPreview.parsed_steps.length} 步
                                    </div>
                                )}
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

                        {/* 按钮 */}
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
                    <div style={modalContent} onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
                            <div>
                                <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)' }}>{selectedSkill.name}</div>
                                <span style={{ fontSize: '12px', color: 'var(--text-muted)', background: 'var(--bg-elevated)', padding: '1px 8px', borderRadius: 'var(--r-sm)' }}>{selectedSkill.category}</span>
                            </div>
                            <button className="btn btn-ghost" onClick={() => setSelectedSkill(null)}>✕</button>
                        </div>

                        {skillDetail?.metadata && (
                            <div style={{ marginBottom: '16px' }}>
                                <div style={sectionLabel}>元数据</div>
                                <div style={{ fontSize: '13px', color: 'var(--text-secondary)', display: 'flex', gap: '12px' }}>
                                    <span>版本: {skillDetail.metadata.version || '1.0.0'}</span>
                                    {skillDetail.metadata.platforms && (
                                        <span>平台: {(skillDetail.metadata.platforms as string[]).join(', ')}</span>
                                    )}
                                </div>
                            </div>
                        )}

                        <div style={{ marginBottom: '16px' }}>
                            <div style={sectionLabel}>描述</div>
                            <p style={{ fontSize: '14px', color: 'var(--text-secondary)', lineHeight: 1.6, margin: 0 }}>
                                {selectedSkill.content || '无描述'}
                            </p>
                        </div>

                        {skillDetail?.body && (
                            <>
                                <div style={{ marginBottom: '16px' }}>
                                    <div style={sectionLabel}>完整内容</div>
                                    <pre style={{
                                        fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6,
                                        background: 'var(--bg-secondary)', padding: '12px', borderRadius: 'var(--r-lg)',
                                        overflow: 'auto', maxHeight: '200px', margin: 0,
                                    }}>{skillDetail.body}</pre>
                                </div>

                                {skillDetail.has_references && (
                                    <div style={{ marginBottom: '16px' }}>
                                        <div style={sectionLabel}>引用文件</div>
                                        <span style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>包含多个引用文件</span>
                                    </div>
                                )}
                            </>
                        )}

                        <div style={{
                            display: 'flex', alignItems: 'center', gap: '16px', padding: '12px 0',
                            borderTop: '1px solid var(--border)', marginBottom: '16px',
                            fontSize: '13px', color: 'var(--text-tertiary)',
                        }}>
                            <span>使用次数: {selectedSkill.usage_count}</span>
                            <span>成功率: {selectedSkill.success_rate.toFixed(1)}%</span>
                            <span>版本: {selectedSkill.version}</span>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <button
                                style={{ background: 'transparent', border: '1px solid var(--danger)', color: 'var(--danger)', borderRadius: 'var(--r-md)', padding: '6px 12px', fontSize: '13px', cursor: 'pointer' }}
                                onClick={() => { handleDelete(selectedSkill.id); setSelectedSkill(null); }}
                            >
                                删除此 Skill
                            </button>
                            <button className="btn btn-secondary" onClick={() => setSelectedSkill(null)}>关闭</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default SkillManagement;