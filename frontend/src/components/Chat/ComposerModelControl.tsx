/**
 * ComposerModelControl — Codex 风格输入框内联控件
 * 左下角一排 pill: [模型 ˅] [推理强度 ˅] [思考模式 ˅]
 * - 模型切换复用 llm.ts 的 profiles / saved / switch 逻辑
 * - 推理强度 (reasoning_effort) 与思考模式 (thinking_mode) 是 TongYong 新增,
 *   存 localStorage, 随请求发后端 (后端不识别也不影响)
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
import './ComposerModelControl.css';

export type ReasoningEffort = 'low' | 'medium' | 'high';
export type ThinkingMode = 'off' | 'auto' | 'always';

const EFFORT_KEY = 'weizhi.reasoning_effort';
const THINKING_KEY = 'weizhi.thinking_mode';

const EFFORT_OPTS: { id: ReasoningEffort; label: string; desc: string }[] = [
  { id: 'low', label: '轻度', desc: '更快, 适合简单任务' },
  { id: 'medium', label: '中等', desc: '平衡速度与质量' },
  { id: 'high', label: '高', desc: '更深入, 适合复杂推理' },
];

const THINKING_OPTS: { id: ThinkingMode; label: string; desc: string }[] = [
  { id: 'off', label: '关闭', desc: '不展示思考过程' },
  { id: 'auto', label: '自动', desc: '按需思考' },
  { id: 'always', label: '始终', desc: '每轮都先思考' },
];

export function getReasoningEffort(): ReasoningEffort {
  const v = localStorage.getItem(EFFORT_KEY) || localStorage.getItem('tongyong.reasoning_effort');
  return v === 'low' || v === 'medium' || v === 'high' ? v : 'medium';
}
export function getThinkingMode(): ThinkingMode {
  const v = localStorage.getItem(THINKING_KEY) || localStorage.getItem('tongyong.thinking_mode');
  return v === 'off' || v === 'auto' || v === 'always' ? v : 'auto';
}

type SwitchableCard = {
  key: string;
  source: 'profile' | 'saved';
  name: string;
  providerId: string;
  model: string;
  baseUrl?: string;
  isCurrent: boolean;
  saved?: SavedModel;
};

interface CurrentModel {
  provider: string;
  name?: string;
  model?: string;
  provider_profile_id?: string;
}

type PanelKey = null | 'model' | 'effort' | 'thinking';

export default function ComposerModelControl() {
  const [panel, setPanel] = useState<PanelKey>(null);
  const [current, setCurrent] = useState<CurrentModel | null>(null);
  const [profiles, setProfiles] = useState<CustomProviderProfile[]>([]);
  const [saved, setSaved] = useState<SavedModel[]>([]);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [effort, setEffort] = useState<ReasoningEffort>(getReasoningEffort());
  const [thinking, setThinking] = useState<ThinkingMode>(getThinkingMode());
  const rootRef = useRef<HTMLDivElement | null>(null);

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
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    const handler = () => load();
    window.addEventListener('modelbadge:refresh', handler);
    return () => window.removeEventListener('modelbadge:refresh', handler);
  }, [load]);

  useEffect(() => {
    if (!panel) return;
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setPanel(null);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setPanel(null); };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [panel]);

  const cards = useMemo<SwitchableCard[]>(() => {
    const profileCards: SwitchableCard[] = profiles
      .filter(p => p.has_api_key || p.id === current?.provider || p.id === current?.provider_profile_id)
      .map(p => {
        const model = p.default_model || p.models?.[0]?.id || '';
        const isCurrent = !!current && (current.provider === p.id || current.provider_profile_id === p.id);
        return { key: `profile:${p.id}`, source: 'profile', name: p.name, providerId: p.id || p.name, model, baseUrl: p.base_url, isCurrent };
      });
    const seen = new Set(profileCards.map(c => `${c.providerId}:${c.model}`));
    const savedCards: SwitchableCard[] = saved
      .filter(s => s.api_key && !seen.has(`${s.provider}:${s.model}`))
      .map(s => {
        const isCurrent = !!current && current.provider === s.provider && current.model === s.model;
        return { key: `saved:${s.id}`, source: 'saved', name: s.name || s.model, providerId: s.provider, model: s.model, baseUrl: s.api_endpoint, isCurrent, saved: s };
      });
    return [...profileCards, ...savedCards].sort((a, b) => Number(b.isCurrent) - Number(a.isCurrent));
  }, [profiles, saved, current]);

  const displayName = useMemo(() => {
    if (!current) return '选择模型';
    if (current.model) return current.model.split('/').pop() || current.model;
    if (current.name) return current.name;
    return current.provider;
  }, [current]);

  const switchTo = async (card: SwitchableCard) => {
    if (card.isCurrent || busyKey) { setPanel(null); return; }
    setBusyKey(card.key);
    try {
      if (card.source === 'profile') await switchModel(card.providerId, undefined, card.model, card.baseUrl);
      else if (card.saved) await switchToSavedModel(card.saved.id);
      await load();
      window.dispatchEvent(new CustomEvent('model:switched', { detail: { provider: card.providerId, model: card.model } }));
    } catch (e: any) {
      setError(e?.message || '切换失败');
    } finally {
      setBusyKey(null);
      setPanel(null);
    }
  };

  const pickEffort = (id: ReasoningEffort) => {
    setEffort(id); localStorage.setItem(EFFORT_KEY, id); setPanel(null);
  };
  const pickThinking = (id: ThinkingMode) => {
    setThinking(id); localStorage.setItem(THINKING_KEY, id); setPanel(null);
  };

  const effortLabel = EFFORT_OPTS.find(o => o.id === effort)?.label || '中等';
  const thinkingLabel = THINKING_OPTS.find(o => o.id === thinking)?.label || '自动';

  return (
    <div className="composer-ctl" ref={rootRef}>
      <button type="button" className={`composer-pill ${panel === 'model' ? 'open' : ''}`} onClick={() => setPanel(p => p === 'model' ? null : 'model')}>
        <span className="composer-pill-dot" />
        <span className="composer-pill-text">{displayName}</span>
        <Chevron />
      </button>
      <button type="button" className={`composer-pill ${panel === 'effort' ? 'open' : ''}`} onClick={() => setPanel(p => p === 'effort' ? null : 'effort')}>
        <span className="composer-pill-text">推理 · {effortLabel}</span>
        <Chevron />
      </button>
      <button type="button" className={`composer-pill ${panel === 'thinking' ? 'open' : ''}`} onClick={() => setPanel(p => p === 'thinking' ? null : 'thinking')}>
        <span className="composer-pill-text">思考 · {thinkingLabel}</span>
        <Chevron />
      </button>

      {panel === 'model' && (
        <div className="composer-menu">
          <div className="composer-menu-head">切换模型{error && <span className="composer-menu-err">{error}</span>}</div>
          {cards.length === 0 ? (
            <div className="composer-menu-empty">还没有可用模型</div>
          ) : (
            <div className="composer-menu-list">
              {cards.map(card => (
                <button key={card.key} type="button" className={`composer-menu-item ${card.isCurrent ? 'active' : ''}`} disabled={!!busyKey} onClick={() => switchTo(card)}>
                  <span className="composer-menu-main">
                    <span className="composer-menu-name">{card.name}</span>
                    <span className="composer-menu-meta">{card.providerId} · {card.model}</span>
                  </span>
                  {card.isCurrent && <span className="composer-menu-tag">当前</span>}
                </button>
              ))}
            </div>
          )}
          <div className="composer-menu-foot">
            <button type="button" className="composer-menu-link" onClick={() => { setPanel(null); window.dispatchEvent(new CustomEvent('modelmanager:add')); }}>+ 添加模型</button>
            <button type="button" className="composer-menu-link" onClick={() => { setPanel(null); window.dispatchEvent(new CustomEvent('modelmanager:open')); }}>⚙ 管理</button>
          </div>
        </div>
      )}

      {panel === 'effort' && (
        <div className="composer-menu composer-menu--sm">
          <div className="composer-menu-head">推理强度</div>
          <div className="composer-menu-list">
            {EFFORT_OPTS.map(o => (
              <button key={o.id} type="button" className={`composer-menu-item ${effort === o.id ? 'active' : ''}`} onClick={() => pickEffort(o.id)}>
                <span className="composer-menu-main">
                  <span className="composer-menu-name">{o.label}</span>
                  <span className="composer-menu-meta">{o.desc}</span>
                </span>
                {effort === o.id && <span className="composer-menu-tag">✓</span>}
              </button>
            ))}
          </div>
        </div>
      )}

      {panel === 'thinking' && (
        <div className="composer-menu composer-menu--sm">
          <div className="composer-menu-head">思考模式</div>
          <div className="composer-menu-list">
            {THINKING_OPTS.map(o => (
              <button key={o.id} type="button" className={`composer-menu-item ${thinking === o.id ? 'active' : ''}`} onClick={() => pickThinking(o.id)}>
                <span className="composer-menu-main">
                  <span className="composer-menu-name">{o.label}</span>
                  <span className="composer-menu-meta">{o.desc}</span>
                </span>
                {thinking === o.id && <span className="composer-menu-tag">✓</span>}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Chevron() {
  return (
    <svg className="composer-pill-chevron" width="9" height="9" viewBox="0 0 10 10" aria-hidden="true">
      <path d="M2 3.5 L5 6.5 L8 3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
