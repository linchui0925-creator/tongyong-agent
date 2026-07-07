/**
 * ModelBadge — header 右上角紧凑当前模型徽章 + 下拉切换
 * 替代 sidebar 底部的 ModelSelector hub，模型选择变成全局高优先级可见元素
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  getCurrentModel,
  getProviderProfiles,
  getSavedModels,
  switchModel,
  switchToSavedModel,
  type CustomProviderProfile,
  type SavedModel,
} from '../../api/llm';
import './ModelBadge.css';

interface CurrentModel {
  provider: string;
  name?: string;
  icon?: string;
  color?: string;
  model?: string;
  provider_profile_id?: string;
}

type SwitchableCard = {
  key: string;
  source: 'profile' | 'saved';
  name: string;
  providerId: string;
  model: string;
  baseUrl?: string;
  icon: string;
  color: string;
  isCurrent: boolean;
  profile?: CustomProviderProfile;
  saved?: SavedModel;
};

function shortName(name: string): string {
  const clean = (name || '').trim();
  if (!clean) return 'AI';
  const parts = clean.split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return clean.slice(0, 2).toUpperCase();
}

export default function ModelBadge() {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState<CurrentModel | null>(null);
  const [profiles, setProfiles] = useState<CustomProviderProfile[]>([]);
  const [saved, setSaved] = useState<SavedModel[]>([]);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, s, c] = await Promise.all([
        getProviderProfiles(),
        getSavedModels(),
        getCurrentModel(),
      ]);
      setProfiles(p.providers || []);
      setSaved(s.models || []);
      setCurrent(c || null);
      setError(null);
    } catch (e: any) {
      setError(e?.message || '加载模型失败');
    }
  }, []);

  useEffect(() => {
    load();
    // 简易 30s 轮询，跟其他面板保持活跃状态一致
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  // 暴露一个全局刷新入口：别的组件切完模型可以触发 badge 重新拉
  useEffect(() => {
    const handler = () => load();
    window.addEventListener('modelbadge:refresh', handler);
    return () => window.removeEventListener('modelbadge:refresh', handler);
  }, [load]);

  // 点击外部 / Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const cards = useMemo<SwitchableCard[]>(() => {
    const profileCards: SwitchableCard[] = profiles
      .filter(p => p.has_api_key || p.id === current?.provider || p.id === current?.provider_profile_id)
      .map(p => {
        const model = p.default_model || p.models?.[0]?.id || '';
        const isCurrent = !!current && (current.provider === p.id || current.provider_profile_id === p.id);
        return {
          key: `profile:${p.id}`,
          source: 'profile',
          name: p.name,
          providerId: p.id || p.name,
          model,
          baseUrl: p.base_url,
          icon: p.icon || shortName(p.name),
          color: p.color || '#3B82F6',
          isCurrent,
          profile: p,
        };
      });

    const seen = new Set(profileCards.map(c => `${c.providerId}:${c.model}`));
    const savedCards: SwitchableCard[] = saved
      .filter(s => s.api_key && !seen.has(`${s.provider}:${s.model}`))
      .map(s => {
        const isCurrent = !!current && current.provider === s.provider && current.model === s.model;
        return {
          key: `saved:${s.id}`,
          source: 'saved',
          name: s.name || s.model,
          providerId: s.provider,
          model: s.model,
          baseUrl: s.api_endpoint,
          icon: shortName(s.name || s.provider),
          color: '#64748B',
          isCurrent,
          saved: s,
        };
      });

    return [...profileCards, ...savedCards].sort((a, b) => Number(b.isCurrent) - Number(a.isCurrent));
  }, [profiles, saved, current]);

  const currentCard = cards.find(c => c.isCurrent) || cards[0];

  const switchTo = async (card: SwitchableCard) => {
    if (card.isCurrent || busyKey) {
      setOpen(false);
      return;
    }
    setBusyKey(card.key);
    try {
      if (card.source === 'profile') {
        await switchModel(card.providerId, undefined, card.model, card.baseUrl);
      } else if (card.saved) {
        await switchToSavedModel(card.saved.id);
      }
      await load();
      // 通知其它模块刷新（如果需要）
      window.dispatchEvent(new CustomEvent('model:switched', { detail: { provider: card.providerId, model: card.model } }));
    } catch (e: any) {
      setError(e?.message || '切换失败');
    } finally {
      setBusyKey(null);
      setOpen(false);
    }
  };

  const onAddNew = () => {
    setOpen(false);
    window.dispatchEvent(new CustomEvent('modelmanager:add'));
  };

  const onManage = () => {
    setOpen(false);
    window.dispatchEvent(new CustomEvent('modelmanager:open'));
  };

  // 显示名：取 model 短名 (去 provider 前缀)
  const displayName = useMemo(() => {
    if (!current) return '未选择模型';
    if (current.model) {
      const m = current.model.split('/').pop() || current.model;
      return m;
    }
    if (current.name) return current.name;
    return current.provider;
  }, [current]);

  const dotColor = current?.color || '#7C3AED';
  const dotIcon = current?.icon ? current.icon.slice(0, 2) : (currentCard?.icon?.slice(0, 2) || 'AI');

  return (
    <div className="model-badge-root" ref={containerRef}>
      <button
        type="button"
        className={`model-badge ${open ? 'open' : ''} ${busyKey ? 'busy' : ''}`}
        onClick={() => setOpen(o => !o)}
        title={current ? `当前模型: ${displayName}` : '点击选择模型'}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="model-badge-dot" style={{ background: dotColor }}>
          <span className="model-badge-dot-label">{dotIcon}</span>
        </span>
        <span className="model-badge-name">{displayName}</span>
        <svg className="model-badge-chevron" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M2 3.5 L5 6.5 L8 3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="model-picker" role="listbox" aria-label="选择模型">
          <div className="model-picker-header">
            <span>切换对话模型</span>
            <span className="model-picker-count">{cards.length}</span>
          </div>

          {error && <div className="model-picker-error">{error}</div>}

          {cards.length === 0 ? (
            <div className="model-picker-empty">
              还没有可用模型。<br />点下方添加一个。
            </div>
          ) : (
            <div className="model-picker-list">
              {cards.map(card => {
                const isBusy = busyKey === card.key;
                return (
                  <button
                    key={card.key}
                    type="button"
                    className={`model-picker-item ${card.isCurrent ? 'active' : ''} ${isBusy ? 'busy' : ''}`}
                    onClick={() => switchTo(card)}
                    disabled={!!busyKey}
                    role="option"
                    aria-selected={card.isCurrent}
                  >
                    <span className="model-picker-icon" style={{ color: card.color }}>
                      {card.icon?.slice(0, 2) || 'AI'}
                    </span>
                    <span className="model-picker-main">
                      <span className="model-picker-name">{card.name}</span>
                      <span className="model-picker-meta">
                        {card.providerId} · {card.model}
                      </span>
                    </span>
                    {card.isCurrent && <span className="model-picker-tag">当前</span>}
                    {isBusy && <span className="model-picker-spinner" aria-hidden="true" />}
                  </button>
                );
              })}
            </div>
          )}

          <div className="model-picker-footer">
            <button type="button" className="model-picker-link" onClick={onAddNew}>
              <span className="model-picker-link-icon">+</span>
              <span>添加新模型</span>
            </button>
            <button type="button" className="model-picker-link" onClick={onManage}>
              <span className="model-picker-link-icon">⚙</span>
              <span>管理所有模型</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
