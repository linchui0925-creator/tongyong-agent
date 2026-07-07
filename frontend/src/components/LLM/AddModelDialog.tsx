import { useEffect, useMemo, useState } from 'react';
import {
  fetchProviderModels,
  saveProviderProfile,
  switchModel,
  testProviderProfile,
  testProviderTools,
  type CustomProviderProfile,
  type ProviderModelEntry,
} from '../../api/llm';
import './AddModelDialog.css';

interface AddModelDialogProps {
  open: boolean;
  onClose: () => void;
  initialProfile?: CustomProviderProfile | null;
}

type TestStatus = 'idle' | 'testing' | 'success' | 'fail';

const OPENAI_COMPATIBLE_DEFAULTS = {
  chat_path: '/chat/completions',
  models_path: '/models',
  tool_call_mode: 'auto',
  headers: {},
  body_defaults: {},
  body_overrides: {},
  field_mapping: {},
  response_mapping: {
    content: 'choices.0.message.content',
    reasoning_content: 'choices.0.message.reasoning_content',
    tool_calls: 'choices.0.message.tool_calls',
    finish_reason: 'choices.0.finish_reason',
  },
};

const TEMPLATE_OPTIONS = [
  {
    id: 'openai_compatible',
    name: 'OpenAI Compatible',
    endpoint: 'https://api.openai.com/v1',
    model: 'gpt-4o-mini',
    notes: '适合 OpenAI、中转站、聚合代理、硅基流动、Moonshot 等兼容接口。',
  },
  {
    id: 'relay',
    name: '中转站 / 聚合代理',
    endpoint: 'https://api.edgefn.net/v1',
    model: 'GLM-4.5V',
    notes: '支持额外 Headers、Body Overrides、reasoning_content、XML fallback。',
  },
  {
    id: 'ollama',
    name: 'Ollama OpenAI 兼容',
    endpoint: 'http://localhost:11434/v1',
    model: 'llama3.2',
    notes: '本地模型，通常不需要 API Key，可填任意占位值。',
  },
];

function prettyJson(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function parseJsonObject(text: string, label: string): Record<string, unknown> {
  if (!text.trim()) return {};
  const parsed = JSON.parse(text);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON object`);
  }
  return parsed as Record<string, unknown>;
}

function modelLinesToEntries(text: string): ProviderModelEntry[] {
  return text
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map(id => ({ id, name: id, enabled: true }));
}

export default function AddModelDialog({ open, onClose, initialProfile }: AddModelDialogProps) {
  const [template, setTemplate] = useState(TEMPLATE_OPTIONS[0].id);
  const selectedTemplate = useMemo(
    () => TEMPLATE_OPTIONS.find(t => t.id === template) || TEMPLATE_OPTIONS[0],
    [template],
  );
  const [providerName, setProviderName] = useState('自定义供应商');
  const [baseUrl, setBaseUrl] = useState(selectedTemplate.endpoint);
  const [apiKey, setApiKey] = useState('');
  const [defaultModel, setDefaultModel] = useState(selectedTemplate.model);
  const [modelsText, setModelsText] = useState(selectedTemplate.model);
  const [website, setWebsite] = useState('');
  const [notes, setNotes] = useState(selectedTemplate.notes);
  const [requestJson, setRequestJson] = useState(prettyJson(OPENAI_COMPATIBLE_DEFAULTS));
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [testStatus, setTestStatus] = useState<TestStatus>('idle');
  const [statusMessage, setStatusMessage] = useState('');
  const [savedProviderId, setSavedProviderId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (initialProfile) {
      setTemplate(initialProfile.protocol === 'openai_compatible' ? 'relay' : 'openai_compatible');
      setProviderName(initialProfile.name || '自定义供应商');
      setBaseUrl(initialProfile.base_url || '');
      setDefaultModel(initialProfile.default_model || initialProfile.models?.[0]?.id || '');
      setModelsText((initialProfile.models || []).map(m => m.id).join('\n') || initialProfile.default_model || '');
      setWebsite(initialProfile.website || '');
      setNotes(initialProfile.notes || '');
      setRequestJson(prettyJson(initialProfile.request_config || OPENAI_COMPATIBLE_DEFAULTS));
      setSavedProviderId(initialProfile.id || null);
    } else {
      setProviderName(template === 'relay' ? 'EdgeFn GLM-4.5V' : '自定义供应商');
      setBaseUrl(selectedTemplate.endpoint);
      setDefaultModel(selectedTemplate.model);
      setModelsText(selectedTemplate.model);
      setWebsite('');
      setNotes(selectedTemplate.notes);
      setRequestJson(prettyJson(OPENAI_COMPATIBLE_DEFAULTS));
      setSavedProviderId(null);
    }
    setStatusMessage('');
    setTestStatus('idle');
  }, [template, open, selectedTemplate, initialProfile]);

  const isValid = providerName.trim() && baseUrl.trim() && defaultModel.trim();

  const buildProfile = (id?: string): CustomProviderProfile => {
    const request_config = parseJsonObject(requestJson, '高级配置');
    const models = modelLinesToEntries(modelsText);
    return {
      id,
      name: providerName.trim(),
      protocol: 'openai_compatible',
      base_url: baseUrl.trim().replace(/\/$/, ''),
      api_key: apiKey.trim() || undefined,
      default_model: defaultModel.trim(),
      enabled: true,
      website: website.trim() || undefined,
      notes: notes.trim() || undefined,
      icon: template === 'ollama' ? '🦙' : '⚙',
      color: template === 'relay' ? '#7C3AED' : '#2563EB',
      request_config,
      models: models.length ? models : [{ id: defaultModel.trim(), name: defaultModel.trim(), enabled: true }],
      model_overrides: {},
    };
  };

  const ensureSavedProvider = async () => {
    const result = await saveProviderProfile(buildProfile(savedProviderId || undefined));
    setSavedProviderId(result.provider.id || null);
    return result.provider;
  };

  const handleFetchModels = async () => {
    if (!isValid) return;
    setTestStatus('testing');
    setStatusMessage('正在保存供应商并拉取模型列表...');
    try {
      const provider = await ensureSavedProvider();
      const request_config = parseJsonObject(requestJson, '高级配置');
      const result = await fetchProviderModels(provider.id!, {
        api_key: apiKey.trim() || undefined,
        model: defaultModel.trim(),
        base_url: baseUrl.trim(),
        request_config,
      });
      if (result.success && result.models.length) {
        setModelsText(result.models.join('\n'));
        if (!result.models.includes(defaultModel)) setDefaultModel(result.models[0]);
        setTestStatus('success');
        setStatusMessage(`已获取 ${result.models.length} 个模型`);
      } else {
        setTestStatus('fail');
        setStatusMessage(result.message || '模型列表为空，可手动填写模型 ID');
      }
    } catch (err: any) {
      setTestStatus('fail');
      setStatusMessage(`获取模型失败: ${err.message}`);
    }
  };

  const handleTestChat = async () => {
    if (!isValid) return;
    setTestStatus('testing');
    setStatusMessage('正在测试 Chat Completions...');
    try {
      const provider = await ensureSavedProvider();
      const result = await testProviderProfile(provider.id!, {
        api_key: apiKey.trim() || undefined,
        model: defaultModel.trim(),
        base_url: baseUrl.trim(),
        request_config: parseJsonObject(requestJson, '高级配置'),
      });
      setTestStatus(result.success ? 'success' : 'fail');
      setStatusMessage(result.success ? `连接成功 — ${result.model || defaultModel}` : `连接失败: ${result.message}`);
    } catch (err: any) {
      setTestStatus('fail');
      setStatusMessage(`测试出错: ${err.message}`);
    }
  };

  const handleTestTools = async () => {
    if (!isValid) return;
    setTestStatus('testing');
    setStatusMessage('正在测试 Function Call...');
    try {
      const provider = await ensureSavedProvider();
      const result = await testProviderTools(provider.id!, {
        api_key: apiKey.trim() || undefined,
        model: defaultModel.trim(),
        base_url: baseUrl.trim(),
        request_config: parseJsonObject(requestJson, '高级配置'),
      });
      setTestStatus(result.success ? 'success' : 'fail');
      setStatusMessage(result.success ? `工具调用可用 — ${result.tool_call_mode}` : `工具调用不可用: ${result.message}`);
    } catch (err: any) {
      setTestStatus('fail');
      setStatusMessage(`工具测试出错: ${err.message}`);
    }
  };

  const handleSaveSwitch = async () => {
    if (!isValid) return;
    setTestStatus('testing');
    setStatusMessage('正在保存并切换...');
    try {
      const provider = await ensureSavedProvider();
      const result = await switchModel(provider.id!, apiKey.trim() || undefined, defaultModel.trim(), baseUrl.trim());
      if (!result.success) {
        setTestStatus('fail');
        setStatusMessage(`切换失败: ${result.message}`);
        return;
      }
      setTestStatus('success');
      setStatusMessage(`已保存并切换到 ${providerName} / ${defaultModel}`);
      setTimeout(() => onClose(), 900);
    } catch (err: any) {
      setTestStatus('fail');
      setStatusMessage(`保存失败: ${err.message}`);
    }
  };

  if (!open) return null;

  return (
    <div className="add-model-overlay" onClick={onClose}>
      <div className="add-model-dialog add-model-dialog-wide" onClick={e => e.stopPropagation()}>
        <div className="add-model-header">
          <div>
            <h2>{initialProfile ? '编辑模型连接' : '添加自定义供应商'}</h2>
            <p>保存 Base URL、模型 ID 与密钥后即可在顶部一键切换。</p>
          </div>
          <button className="add-model-close" onClick={onClose}>✕</button>
        </div>

        <div className="add-model-body">
          <div className="provider-template-grid">
            {TEMPLATE_OPTIONS.map(item => (
              <button
                key={item.id}
                className={`provider-template ${template === item.id ? 'active' : ''}`}
                onClick={() => setTemplate(item.id)}
              >
                <strong>{item.name}</strong>
                <span>{item.notes}</span>
              </button>
            ))}
          </div>

          <div className="add-model-grid">
            <div className="add-model-field">
              <label className="required">供应商名称</label>
              <input value={providerName} onChange={e => setProviderName(e.target.value)} placeholder="例如 EdgeFn / OpenRouter / 公司网关" />
            </div>
            <div className="add-model-field">
              <label>官网 / 控制台</label>
              <input value={website} onChange={e => setWebsite(e.target.value)} placeholder="https://..." />
            </div>
          </div>

          <div className="add-model-field">
            <label className="required">API 端点 Base URL</label>
            <input value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://api.example.com/v1" />
          </div>

          <div className="add-model-grid">
            <div className="add-model-field">
              <label>API Key</label>
              <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="sk-... / 本地模型可留空" />
            </div>
            <div className="add-model-field">
              <label className="required">默认模型</label>
              <input value={defaultModel} onChange={e => setDefaultModel(e.target.value)} placeholder="模型 ID" />
            </div>
          </div>

          <div className="add-model-field">
            <label>模型列表 <span>每行一个 model id</span></label>
            <textarea value={modelsText} onChange={e => setModelsText(e.target.value)} rows={5} />
          </div>

          <div className="add-model-field">
            <label>备注</label>
            <input value={notes} onChange={e => setNotes(e.target.value)} placeholder="用途、限制、计费说明" />
          </div>

          <button className="advanced-toggle" onClick={() => setAdvancedOpen(v => !v)}>
            {advancedOpen ? '收起高级配置' : '展开高级配置'}
          </button>

          {advancedOpen && (
            <div className="add-model-field">
              <label>Request Config JSON</label>
              <textarea
                className="json-textarea"
                value={requestJson}
                onChange={e => setRequestJson(e.target.value)}
                rows={14}
                spellCheck={false}
              />
            </div>
          )}

          {statusMessage && (
            <div className={`add-model-status ${testStatus === 'testing' ? 'pending' : testStatus === 'success' ? 'success' : 'error'}`}>
              {statusMessage}
            </div>
          )}

          <div className="add-model-actions provider-actions">
            <button className="btn-test" disabled={!isValid || testStatus === 'testing'} onClick={handleFetchModels}>获取模型</button>
            <button className="btn-test" disabled={!isValid || testStatus === 'testing'} onClick={handleTestChat}>测试连接</button>
            <button className="btn-test" disabled={!isValid || testStatus === 'testing'} onClick={handleTestTools}>测试工具</button>
            <button className="btn-save" disabled={!isValid || testStatus === 'testing'} onClick={handleSaveSwitch}>保存并切换</button>
          </div>
        </div>
      </div>
    </div>
  );
}
