import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import {
  deleteProviderProfile,
  getCurrentModel,
  getProviderProfiles,
  getSavedModels,
  switchModel,
  switchToSavedModel,
  testProviderProfile,
  testProviderTools,
  type CustomProviderProfile,
  type SavedModel,
} from '../../api/llm';
import AddModelDialog from './AddModelDialog';
import { streamChat } from '../../api/stream';
import './ModelSelector.css';

type ConnectedStatus = 'connected' | 'failed' | 'untested' | 'testing';

interface CurrentModel {
  provider: string;
  name?: string;
  icon?: string;
  color?: string;
  model?: string;
  api_key_configured?: boolean;
  provider_profile_id?: string;
  runtime?: {
    provider?: string;
    model?: string;
    api_format?: string;
    api_base?: string;
  };
}

interface ConnectedModelCard {
  id: string;
  source: 'profile' | 'saved';
  name: string;
  providerId: string;
  model: string;
  baseUrl?: string;
  icon: string;
  color: string;
  status: ConnectedStatus;
  isCurrent: boolean;
  hasApiKey: boolean;
  supportsTools?: boolean | null;
  supportsVision?: boolean | null;
  supportsReasoning?: boolean | null;
  lastMessage?: string;
  profile?: CustomProviderProfile;
  saved?: SavedModel;
}

const statusLabel: Record<ConnectedStatus, string> = {
  connected: '已连接',
  failed: '查询失败',
  untested: '未测试',
  testing: '测试中',
};

function shortName(name: string) {
  const clean = name.trim();
  if (!clean) return 'AI';
  const parts = clean.split(/\s+/);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return clean.slice(0, 2).toUpperCase();
}

interface ModelSelectorProps {
  defaultHubVisible?: boolean;
}

export default function ModelSelector({ defaultHubVisible = true }: ModelSelectorProps = {}) {
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [showManager, setShowManager] = useState(false);
  const [editingProfile, setEditingProfile] = useState<CustomProviderProfile | null>(null);
  const [profiles, setProfiles] = useState<CustomProviderProfile[]>([]);
  const [savedModels, setSavedModels] = useState<SavedModel[]>([]);
  const [current, setCurrent] = useState<CurrentModel | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [localStatus, setLocalStatus] = useState<Record<string, { status: ConnectedStatus; message?: string }>>({});
  const [hubVisible] = useState<boolean>(defaultHubVisible);
  const [linkCard, setLinkCard] = useState<ConnectedModelCard | null>(null);
  const [linkPrompt, setLinkPrompt] = useState<string>('ping');
  const [linkResponse, setLinkResponse] = useState<string>('');
  const [linkRunning, setLinkRunning] = useState<boolean>(false);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [linkController, setLinkController] = useState<AbortController | null>(null);

  // 监听外部事件：从 header 右上角 badge 触发
  // 注意：这里不动 hubVisible — 事件触发时只开 manager overlay / AddModelDialog，
  //       不要把内联 hub 也显示出来（默认 defaultHubVisible={false} 时内联 hub 应保持隐藏）
  useEffect(() => {
    const onOpenManager = () => setShowManager(true);
    const onAddNew = () => setShowAddDialog(true);
    window.addEventListener('modelmanager:open', onOpenManager);
    window.addEventListener('modelmanager:add', onAddNew);
    return () => {
      window.removeEventListener('modelmanager:open', onOpenManager);
      window.removeEventListener('modelmanager:add', onAddNew);
    };
  }, []);

  const loadData = useCallback(async () => {
    try {
      const [profileData, savedData, currentData] = await Promise.all([
        getProviderProfiles(),
        getSavedModels(),
        getCurrentModel(),
      ]);
      setProfiles(profileData.providers || []);
      setSavedModels(savedData.models || []);
      setCurrent(currentData);
    } catch (error) {
      console.error('[ModelSelector] 加载模型连接失败:', error);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (!showAddDialog) loadData();
  }, [showAddDialog, loadData]);

  const connectedModels = useMemo<ConnectedModelCard[]>(() => {
    // W5-3: 每个 (provider, model) 一张卡, 不再吞掉同一 provider 下的多个 model
    // 解决 "edgefn 有 GLM-4.5V/GLM-5.2 等 6 个 model 但只显示 1 张卡 (默认 GLM-4.5V)" 的问题
    const profileCards: ConnectedModelCard[] = [];
    profiles
      .filter(profile => profile.has_api_key || profile.id === current?.provider || profile.id === current?.provider_profile_id)
      .forEach(profile => {
        // 候选 model 列表: profile.models[] (来自 builtin / scrape), 至少含 default_model
        const ids = (profile.models && profile.models.length > 0)
            ? profile.models.map(m => m.id)
            : (profile.default_model ? [profile.default_model] : []);
        if (ids.length === 0) {
          // fallback: 没 models 也没 default → 单卡, 用 profile 的 default_model
          const model = profile.default_model || '';
          const isCurrent = (current?.provider === profile.id || current?.provider_profile_id === profile.id) &&
                            (!model || current?.model === model);
          const firstModel = profile.models?.find(m => m.id === model);
          profileCards.push({
            id: `${profile.id || profile.name}::${model}`,
            source: 'profile',
            name: profile.name,
            providerId: profile.id || profile.name,
            model,
            baseUrl: profile.base_url,
            icon: profile.icon || shortName(profile.name),
            color: profile.color || '#3B82F6',
            status: localStatus[profile.id || '']?.status || (isCurrent ? 'connected' : 'untested'),
            isCurrent,
            hasApiKey: Boolean(profile.has_api_key),
            supportsTools: firstModel?.supports_tools,
            supportsVision: firstModel?.supports_vision,
            supportsReasoning: firstModel?.supports_reasoning,
            lastMessage: localStatus[profile.id || '']?.message,
            profile,
          } as ConnectedModelCard);
          return;
        }
        ids.forEach(modelId => {
          const isCurrent = (current?.provider === profile.id || current?.provider_profile_id === profile.id) &&
                            current?.model === modelId;
          const firstModel = profile.models?.find(m => m.id === modelId) || profile.models?.[0];
          const cardKey = `${profile.id || profile.name}::${modelId}`;
          profileCards.push({
            id: cardKey,
            source: 'profile',
            name: `${profile.name} · ${modelId}`,
            providerId: profile.id || profile.name,
            model: modelId,
            baseUrl: profile.base_url,
            icon: profile.icon || shortName(profile.name),
            color: profile.color || '#3B82F6',
            status: localStatus[cardKey]?.status || (isCurrent ? 'connected' : 'untested'),
            isCurrent,
            hasApiKey: Boolean(profile.has_api_key),
            supportsTools: firstModel?.supports_tools,
            supportsVision: firstModel?.supports_vision,
            supportsReasoning: firstModel?.supports_reasoning,
            lastMessage: localStatus[cardKey]?.message,
            profile,
          } as ConnectedModelCard);
        });
      });

    const seen = new Set(profileCards.map(card => `${card.providerId}:${card.model}`));
    const savedCards = savedModels
      .filter(saved => saved.api_key && saved.api_key !== 'YOUR_API_KEY' && !seen.has(`${saved.provider}:${saved.model}`))
      .map(saved => {
        const isCurrent = current?.provider === saved.provider && current?.model === saved.model;
        const id = `saved:${saved.id}`;
        return {
          id,
          source: 'saved' as const,
          name: saved.name || saved.model,
          providerId: saved.provider,
          model: saved.model,
          baseUrl: saved.api_endpoint,
          icon: 'AI',
          color: '#64748B',
          status: localStatus[id]?.status || (isCurrent ? 'connected' : 'untested'),
          isCurrent,
          hasApiKey: Boolean(saved.api_key),
          lastMessage: localStatus[id]?.message,
          saved,
        };
      });

    return [...profileCards, ...savedCards].sort((a, b) => Number(b.isCurrent) - Number(a.isCurrent));
  }, [profiles, savedModels, current, localStatus]);

  const currentCard = connectedModels.find(card => card.isCurrent) || connectedModels[0];

  const switchCard = async (card: ConnectedModelCard) => {
    setBusyId(card.id);
    try {
      if (card.source === 'profile') {
        await switchModel(card.providerId, undefined, card.model, card.baseUrl);
      } else if (card.saved) {
        await switchToSavedModel(card.saved.id);
      }
      setLocalStatus(prev => ({ ...prev, [card.id]: { status: 'connected', message: '已切换' } }));
      await loadData();
    } catch (error: any) {
      setLocalStatus(prev => ({ ...prev, [card.id]: { status: 'failed', message: error.message } }));
    } finally {
      setBusyId(null);
    }
  };

  const testCard = async (card: ConnectedModelCard) => {
    if (card.source !== 'profile' || !card.profile?.id) return;
    setBusyId(card.id);
    setLocalStatus(prev => ({ ...prev, [card.id]: { status: 'testing', message: '测试中' } }));
    try {
      const body = {
        model: card.model,
        base_url: card.baseUrl,
        request_config: card.profile.request_config,
      };
      const chat = await testProviderProfile(card.profile.id, body);
      if (!chat.success) {
        setLocalStatus(prev => ({ ...prev, [card.id]: { status: 'failed', message: chat.message } }));
        return;
      }
      const tools = await testProviderTools(card.profile.id, body);
      setLocalStatus(prev => ({
        ...prev,
        [card.id]: {
          status: tools.success ? 'connected' : 'failed',
          message: tools.success ? `工具可用 · ${tools.tool_call_mode || 'auto'}` : tools.message,
        },
      }));
    } catch (error: any) {
      setLocalStatus(prev => ({ ...prev, [card.id]: { status: 'failed', message: error.message } }));
    } finally {
      setBusyId(null);
    }
  };

  const deleteCard = async (card: ConnectedModelCard) => {
    if (card.source !== 'profile' || !card.profile?.id) return;
    if (!window.confirm(`确定要删除供应商「${card.name}」吗？此操作不可恢复。`)) return;

    setBusyId(card.id);
    try {
      await deleteProviderProfile(card.profile.id);
      await loadData();
    } catch (error: any) {
      setLocalStatus(prev => ({ ...prev, [card.id]: { status: 'failed', message: error.message } }));
    } finally {
      setBusyId(null);
    }
  };

  const openTestLink = (card: ConnectedModelCard) => {
    setLinkCard(card);
    setLinkResponse('');
    setLinkError(null);
    setLinkPrompt('ping');
  };
  const closeTestLink = () => {
    if (linkController) linkController.abort();
    setLinkCard(null);
    setLinkResponse('');
    setLinkError(null);
    setLinkRunning(false);
  };
  const runTestLink = async () => {
    if (!linkCard || !linkPrompt.trim() || linkRunning) return;
    setLinkRunning(true);
    setLinkResponse('');
    setLinkError(null);
    try {
      // 先切到目标模型
      if (linkCard.source === 'profile') {
        await switchModel(linkCard.providerId, undefined, linkCard.model, linkCard.baseUrl);
      } else if (linkCard.saved) {
        await switchToSavedModel(linkCard.saved.id);
      }
      await loadData();
      // 用 streamChat 发测试消息（无 session_id = 新会话）。
      // streamChat 自己创建 AbortController 并通过返回值给我们 — linkController.abort() 可以停止流。
      const ac = streamChat(linkPrompt.trim(), undefined, false, {
        onContent: (_chunk, full) => setLinkResponse(full || ''),
        onDone: () => setLinkRunning(false),
        onError: (err) => { setLinkError(err); setLinkRunning(false); },
      });
      setLinkController(ac);
    } catch (e: any) {
      setLinkError(e?.message || '切换模型失败');
      setLinkRunning(false);
    }
  };

  return (
    <>
    {hubVisible && (
    <div className="model-hub">
      <div className="model-hub-brand">
        <button className="model-brand-pill" onClick={() => setShowManager(true)} title="模型连接管理">
          <span className="model-brand-mark">TY</span>
          <span className="model-hub-title">维知</span>
        </button>
        <button className="model-hub-settings" onClick={() => setShowManager(true)} title="模型连接管理">⚙</button>
      </div>

      <div className="model-tabs" aria-label="已连接模型">
        {connectedModels.length === 0 ? (
          <button className="model-tab empty" onClick={() => setShowAddDialog(true)}>
            <span className="model-tab-icon">+</span>
            <span>添加模型</span>
          </button>
        ) : connectedModels.slice(0, 8).map(card => (
          <button
            key={card.id}
            className={`model-tab ${card.isCurrent ? 'active' : ''}`}
            onClick={() => switchCard(card)}
            disabled={busyId === card.id}
            title={`${card.name} · ${card.model}`}
          >
            <span className="model-tab-icon" style={{ color: card.color }}>{card.icon}</span>
            <span className="model-tab-label">{card.name}</span>
            {card.isCurrent && <span className="model-tab-active-dot" />}
          </button>
        ))}
      </div>

      <div className="model-hub-actions">
        {currentCard && (
          <button className="current-model-pill" onClick={() => setShowManager(true)}>
            <span className={`status-dot ${currentCard.status}`} />
            {currentCard.model || currentCard.name}
            {current?.runtime?.api_format && <span className="current-model-pill-protocol">{current.runtime.api_format}</span>}
          </button>
        )}
        <button className="model-icon-btn" onClick={loadData} title="刷新">↻</button>
        <button className="model-add-fab" onClick={() => setShowAddDialog(true)} title="添加供应商">+</button>
      </div>
    </div>
    )}

      {showManager && (
        <div className="model-manager-overlay" onClick={() => setShowManager(false)}>
          <section className="model-manager" onClick={e => e.stopPropagation()}>
            <header className="model-manager-header">
              <div>
                <h2>模型连接</h2>
                <p>集中管理 OpenAI-compatible、中转站、本地模型与当前运行模型。</p>
              </div>
              <div className="model-manager-header-actions">
                <button className="model-secondary-btn" onClick={loadData}>刷新</button>
                <button className="model-primary-btn" onClick={() => setShowAddDialog(true)}>+ 添加供应商</button>
                <button className="model-close-btn" onClick={() => setShowManager(false)}>✕</button>
              </div>
            </header>

            <div className="connected-model-list">
              {connectedModels.length === 0 ? (
                <div className="connected-empty">
                  <strong>还没有已连接模型</strong>
                  <span>添加 OpenAI-compatible、中转站或 Ollama 供应商后会显示在这里。</span>
                  <button className="model-primary-btn" onClick={() => setShowAddDialog(true)}>添加第一个供应商</button>
                </div>
              ) : connectedModels.map(card => (
                <Fragment key={card.id}>
                <article className={`connected-card ${card.isCurrent ? 'active' : ''}`}>
                  <div className="connected-avatar" style={{ color: card.color }}>{card.icon || shortName(card.name)}</div>
                  <div className="connected-main">
                    <div className="connected-title-row">
                      <h3>{card.name}</h3>
                      {card.supportsVision && <span className="capability-pill">Vision</span>}
                      {card.supportsReasoning && <span className="capability-pill">Reasoning</span>}
                      {card.supportsTools && <span className="capability-pill">Tools</span>}
                    </div>
                    <a className="connected-url" href={card.baseUrl} target="_blank" rel="noreferrer">{card.baseUrl || card.providerId}</a>
                    <div className="connected-meta">
                      <span className="model-code">{card.model}</span>
                      <span className={`status-chip ${card.status}`}>{statusLabel[card.status]}</span>
                      {card.lastMessage && <span>{card.lastMessage}</span>}
                      {current?.runtime?.api_format && card.isCurrent && (
                        <span className="status-chip protocol">{current.runtime.api_format}</span>
                      )}
                    </div>
                  </div>
                  <div className="connected-actions">
                    {card.isCurrent && <span className="using-badge">使用中</span>}
                    <button onClick={() => testCard(card)} disabled={busyId === card.id || card.source !== 'profile'} title="测试">↻</button>
                    <button onClick={() => switchCard(card)} disabled={busyId === card.id || card.isCurrent} title="使用">✓</button>
                    <button
                      onClick={() => {
                        setEditingProfile(card.profile || null);
                        setShowAddDialog(true);
                      }}
                      disabled={card.source !== 'profile'}
                      title="编辑"
                    >
                      ✎
                    </button>
                    <button
                      onClick={() => openTestLink(card)}
                      disabled={busyId === card.id}
                      title="测试此模型 (发一条 chat 看响应)"
                      className="test-link-btn"
                    >
                      💬
                    </button>
                    <button onClick={() => deleteCard(card)} disabled={busyId === card.id || card.source !== 'profile'} title="删除">⌫</button>
                  </div>
                </article>

              {linkCard?.id === card.id && (
                <div className="test-link-panel" role="dialog" aria-label="测试此模型">
                  <div className="test-link-header">
                    <span className="test-link-title">测试 {card.name}</span>
                    <span className="test-link-sub">会用 {card.model} 真发一条 chat</span>
                    <button
                      type="button"
                      className="test-link-close"
                      onClick={closeTestLink}
                      title="关闭"
                      aria-label="关闭"
                    >✕</button>
                  </div>
                  <div className="test-link-body">
                    <textarea
                      className="test-link-prompt"
                      value={linkPrompt}
                      onChange={e => setLinkPrompt(e.target.value)}
                      placeholder="输入测试 prompt..."
                      rows={2}
                      disabled={linkRunning}
                    />
                    <div className="test-link-actions">
                      <button
                        type="button"
                        className="test-link-send"
                        onClick={runTestLink}
                        disabled={linkRunning || !linkPrompt.trim()}
                      >
                        {linkRunning ? '发送中...' : '发送测试'}
                      </button>
                      {linkRunning && linkController && (
                        <button
                          type="button"
                          className="test-link-stop"
                          onClick={() => linkController.abort()}
                        >停止</button>
                      )}
                    </div>
                    {(linkResponse || linkError || linkRunning) && (
                      <div className={`test-link-response ${linkError ? 'error' : ''} ${linkRunning ? 'streaming' : ''}`}>
                        {linkError ? (
                          <div className="test-link-error">{linkError}</div>
                        ) : (
                          <>
                            <div className="test-link-response-label">
                              {linkRunning ? '▍ 响应中...' : '响应'}
                            </div>
                            <div className="test-link-response-text">{linkResponse || (linkRunning ? '' : '（无内容）')}</div>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
                </Fragment>
              ))}
            </div>
          </section>
        </div>
      )}

      <AddModelDialog
        open={showAddDialog}
        initialProfile={editingProfile}
        onClose={() => {
          setShowAddDialog(false);
          setEditingProfile(null);
        }}
      />
    </>
  );
}
