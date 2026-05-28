import { useState, useEffect, useCallback } from 'react';
import {
    getProfiles,
    createProfile,
    updateProfile,
    deleteProfile,
    activateProfile,
    testProfile,
    getGatewayStatus,
    startGateway,
    stopGateway,
    restartGateway,
    type Profile,
    type ProfileCreate,
    type Gateway,
} from '../../api/gateway_profiles';
import './ProfileSelector.css';

const PROVIDERS = [
    { id: 'tongyi', name: '通义千问', icon: '🐰' },
    { id: 'openai', name: 'OpenAI', icon: '🤖' },
    { id: 'anthropic', name: 'Anthropic', icon: '🧠' },
    { id: 'minimax', name: 'MiniMax', icon: '🦊' },
    { id: 'deepseek', name: 'DeepSeek', icon: '🔮' },
    { id: 'moonshot', name: 'Moonshot', icon: '🌙' },
    { id: 'zhipu', name: '智谱', icon: '🔵' },
    { id: 'baichuan', name: '百川', icon: '💎' },
    { id: 'google', name: 'Google', icon: '🌐' },
    { id: 'yi', name: '零一万物', icon: '✨' },
    { id: 'wenxin', name: '文心一言', icon: '📝' },
    { id: 'xfyun', name: '讯飞星火', icon: '🔥' },
    { id: 'stepfun', name: '阶跃星辰', icon: '🚀' },
    { id: 'siliconflow', name: 'SiliconFlow', icon: '⚡' },
    { id: 'ollama', name: 'Ollama', icon: '🦙' },
];

export default function ProfileSelector() {
    const [profiles, setProfiles] = useState<Profile[]>([]);
    const [activeProfileId, setActiveProfileId] = useState<string | null>(null);
    const [gateways, setGateways] = useState<Record<string, Gateway>>({});
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [showForm, setShowForm] = useState(false);
    const [editingProfile, setEditingProfile] = useState<Profile | null>(null);
    const [testingId, setTestingId] = useState<string | null>(null);
    const [gatewayLoading, setGatewayLoading] = useState<Record<string, boolean>>({});
    const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null);

    // Form state
    const [formData, setFormData] = useState<ProfileCreate>({
        name: '',
        provider: 'minimax',
        model: '',
        api_key: '',
        api_endpoint: '',
        max_tool_rounds: 10,
    });

    const loadProfiles = useCallback(async () => {
        try {
            setLoading(true);
            const data = await getProfiles();
            setProfiles(data.profiles);
            setActiveProfileId(data.active_profile_id);

            // 加载网关状态
            const gatewayStatuses: Record<string, Gateway> = {};
            for (const profile of data.profiles) {
                try {
                    const status = await getGatewayStatus(profile.id);
                    gatewayStatuses[profile.id] = status;
                } catch (e) {
                    // 网关未启动，忽略
                }
            }
            setGateways(gatewayStatuses);

            setError(null);
        } catch (e) {
            setError('加载Profile失败');
            console.error(e);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadProfiles();
    }, [loadProfiles]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            if (editingProfile) {
                await updateProfile(editingProfile.id, formData);
            } else {
                await createProfile(formData);
            }
            setShowForm(false);
            setEditingProfile(null);
            resetForm();
            await loadProfiles();
        } catch (e) {
            console.error(e);
            setError(editingProfile ? '更新Profile失败' : '创建Profile失败');
        }
    };

    const handleEdit = (profile: Profile) => {
        setEditingProfile(profile);
        setFormData({
            name: profile.name,
            provider: profile.provider,
            model: profile.model || '',
            api_key: profile.api_key || '',
            api_endpoint: profile.api_endpoint || '',
            max_tool_rounds: profile.max_tool_rounds,
        });
        setShowForm(true);
    };

    const handleDelete = async (profileId: string) => {
        if (!confirm('确定要删除这个Profile吗？')) return;
        try {
            await deleteProfile(profileId);
            await loadProfiles();
        } catch (e) {
            console.error(e);
            setError('删除Profile失败');
        }
    };

    const handleActivate = async (profileId: string) => {
        try {
            await activateProfile(profileId);
            setActiveProfileId(profileId);
        } catch (e) {
            console.error(e);
            setError('激活Profile失败');
        }
    };

    const handleTest = async (profileId: string) => {
        setTestingId(profileId);
        try {
            const result = await testProfile(profileId);
            alert(result.success ? `连接成功: ${result.message}` : `连接失败: ${result.message}`);
        } catch (e) {
            console.error(e);
            alert('测试失败');
        } finally {
            setTestingId(null);
        }
    };

    const handleStartGateway = async (profileId: string) => {
        setGatewayLoading(prev => ({ ...prev, [profileId]: true }));
        try {
            const result = await startGateway(profileId);
            setGateways(prev => ({
                ...prev,
                [profileId]: {
                    profile_id: profileId,
                    port: result.port,
                    is_running: true,
                    url: result.url,
                },
            }));
        } catch (e) {
            console.error(e);
            alert('启动网关失败');
        } finally {
            setGatewayLoading(prev => ({ ...prev, [profileId]: false }));
        }
    };

    const handleStopGateway = async (profileId: string) => {
        setGatewayLoading(prev => ({ ...prev, [profileId]: true }));
        try {
            await stopGateway(profileId);
            setGateways(prev => {
                const next = { ...prev };
                delete next[profileId];
                return next;
            });
        } catch (e) {
            console.error(e);
            alert('停止网关失败');
        } finally {
            setGatewayLoading(prev => ({ ...prev, [profileId]: false }));
        }
    };

    const handleRestartGateway = async (profileId: string) => {
        setGatewayLoading(prev => ({ ...prev, [profileId]: true }));
        try {
            const result = await restartGateway(profileId);
            setGateways(prev => ({
                ...prev,
                [profileId]: {
                    profile_id: profileId,
                    port: result.port,
                    is_running: true,
                    url: result.url,
                },
            }));
        } catch (e) {
            console.error(e);
            alert('重启网关失败');
        } finally {
            setGatewayLoading(prev => ({ ...prev, [profileId]: false }));
        }
    };

    const isGatewayRunning = (profileId: string) => {
        return gateways[profileId]?.is_running === true;
    };

    const getGatewayPort = (profileId: string) => {
        return gateways[profileId]?.port || 0;
    };

    const getGatewayUrl = (profileId: string) => {
        return gateways[profileId]?.url || '';
    };

    const resetForm = () => {
        setFormData({
            name: '',
            provider: 'minimax',
            model: '',
            api_key: '',
            api_endpoint: '',
            max_tool_rounds: 10,
        });
    };

    const openCreateForm = () => {
        setEditingProfile(null);
        resetForm();
        setShowForm(true);
    };

    const getProviderInfo = (providerId: string) => {
        return PROVIDERS.find(p => p.id === providerId) || { name: providerId, icon: '⚙' };
    };

    return (
        <div className="profile-selector">
            <div className="profile-header">
                <h3>网关 Profiles</h3>
                <button className="profile-add-btn" onClick={openCreateForm}>+ 新建</button>
            </div>

            {error && <div className="profile-error">{error}</div>}

            {loading ? (
                <div className="profile-loading">加载中...</div>
            ) : profiles.length === 0 ? (
                <div className="profile-empty">
                    <p>暂无Profile</p>
                    <button onClick={openCreateForm}>创建第一个Profile</button>
                </div>
            ) : (
                <div className="profile-list">
                    {profiles.map(profile => {
                        const provider = getProviderInfo(profile.provider);
                        const isActive = profile.id === activeProfileId;
                        const isSelected = profile.id === selectedProfileId;
                        return (
                            <div
                                key={profile.id}
                                className={`profile-item ${isActive ? 'active' : ''} ${isSelected ? 'selected' : ''}`}
                                onClick={() => setSelectedProfileId(isSelected ? null : profile.id)}
                            >
                                <div className="profile-item-icon">{provider.icon}</div>
                                <div className="profile-item-info">
                                    <div className="profile-item-name">
                                        {profile.name}
                                        {isActive && <span className="profile-active-badge">当前</span>}
                                    </div>
                                    <div className="profile-item-meta">
                                        {provider.name} / {profile.model || profile.provider}
                                    </div>
                                </div>
                                <div className="profile-item-actions">
                                    {!isActive && (
                                        <button
                                            className="profile-action-btn activate"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                handleActivate(profile.id);
                                            }}
                                            title="激活"
                                        >
                                            激活
                                        </button>
                                    )}
                                    <button
                                        className="profile-action-btn test"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            handleTest(profile.id);
                                        }}
                                        disabled={testingId === profile.id}
                                        title="测试"
                                    >
                                        {testingId === profile.id ? '测试中...' : '测试'}
                                    </button>
                                    <button
                                        className="profile-action-btn edit"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            handleEdit(profile);
                                        }}
                                        title="编辑"
                                    >
                                        编辑
                                    </button>
                                    <button
                                        className="profile-action-btn delete"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            handleDelete(profile.id);
                                        }}
                                        title="删除"
                                    >
                                        删除
                                    </button>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* 独立网关控制面板 */}
            {selectedProfileId && (
                <div className="gateway-panel">
                    <div className="gateway-panel-header">
                        <h4>网关控制</h4>
                        <span className="gateway-panel-profile">
                            {profiles.find(p => p.id === selectedProfileId)?.name}
                        </span>
                    </div>
                    <div className="gateway-panel-actions">
                        {isGatewayRunning(selectedProfileId) ? (
                            <>
                                <div className="gateway-status running">
                                    <span className="gateway-status-dot"></span>
                                    运行中 (端口: {getGatewayPort(selectedProfileId)})
                                </div>
                                <button
                                    className="gateway-action-btn restart"
                                    onClick={() => handleRestartGateway(selectedProfileId)}
                                    disabled={gatewayLoading[selectedProfileId]}
                                >
                                    {gatewayLoading[selectedProfileId] ? '重启中...' : '重启网关'}
                                </button>
                                <button
                                    className="gateway-action-btn stop"
                                    onClick={() => handleStopGateway(selectedProfileId)}
                                    disabled={gatewayLoading[selectedProfileId]}
                                >
                                    {gatewayLoading[selectedProfileId] ? '停止中...' : '停止网关'}
                                </button>
                            </>
                        ) : (
                            <>
                                <div className="gateway-status stopped">已停止</div>
                                <button
                                    className="gateway-action-btn start"
                                    onClick={() => handleStartGateway(selectedProfileId)}
                                    disabled={gatewayLoading[selectedProfileId]}
                                >
                                    {gatewayLoading[selectedProfileId] ? '启动中...' : '启动网关'}
                                </button>
                            </>
                        )}
                    </div>
                    {isGatewayRunning(selectedProfileId) && (
                        <div className="gateway-url">
                            URL: <code>{getGatewayUrl(selectedProfileId)}</code>
                        </div>
                    )}
                </div>
            )}

            {showForm && (
                <div className="profile-form-overlay" onClick={() => setShowForm(false)}>
                    <div className="profile-form" onClick={e => e.stopPropagation()}>
                        <h3>{editingProfile ? '编辑 Profile' : '新建 Profile'}</h3>
                        <form onSubmit={handleSubmit}>
                            <div className="form-group">
                                <label>名称</label>
                                <input
                                    type="text"
                                    value={formData.name}
                                    onChange={e => setFormData({ ...formData, name: e.target.value })}
                                    required
                                    placeholder="Profile显示名称"
                                />
                            </div>
                            <div className="form-group">
                                <label>Provider</label>
                                <select
                                    value={formData.provider}
                                    onChange={e => setFormData({ ...formData, provider: e.target.value })}
                                >
                                    {PROVIDERS.map(p => (
                                        <option key={p.id} value={p.id}>{p.icon} {p.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="form-group">
                                <label>模型</label>
                                <input
                                    type="text"
                                    value={formData.model}
                                    onChange={e => setFormData({ ...formData, model: e.target.value })}
                                    placeholder="模型名称（如 qwen-plus）"
                                />
                            </div>
                            <div className="form-group">
                                <label>API Key</label>
                                <input
                                    type="password"
                                    value={formData.api_key}
                                    onChange={e => setFormData({ ...formData, api_key: e.target.value })}
                                    placeholder="API密钥（留空使用环境配置）"
                                />
                            </div>
                            <div className="form-group">
                                <label>API Endpoint</label>
                                <input
                                    type="text"
                                    value={formData.api_endpoint}
                                    onChange={e => setFormData({ ...formData, api_endpoint: e.target.value })}
                                    placeholder="自定义API端点（可选）"
                                />
                            </div>
                            <div className="form-group">
                                <label>最大工具调用轮数</label>
                                <input
                                    type="number"
                                    value={formData.max_tool_rounds}
                                    onChange={e => setFormData({ ...formData, max_tool_rounds: parseInt(e.target.value) || 10 })}
                                    min={1}
                                    max={50}
                                />
                            </div>
                            <div className="form-actions">
                                <button type="button" onClick={() => setShowForm(false)}>取消</button>
                                <button type="submit">{editingProfile ? '保存' : '创建'}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}