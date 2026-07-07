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
    id: 'openai',
    name: '🟢 OpenAI Official',
    endpoint: 'https://api.openai.com/v1',
    model: 'gpt-4o',
    notes: 'OpenAI官方接口，支持GPT-4o/GPT-3.5-turbo等。',
  },
  {
    id: 'sheng_suan_yun',
    name: '🟣 胜算云',
    endpoint: 'https://api.shengyun.com/v1',
    model: 'sheng-suan-7b',
    notes: '胜算云模型接口。',
  },
  {
    id: 'patewayai',
    name: '⚫ PatewayAI',
    endpoint: 'https://api.patewayai.com/v1',
    model: 'pateway-v1',
    notes: 'PatewayAI官方接口。',
  },
  {
    id: 'volcengine_agentplan',
    name: '🔵 火山Agentplan',
    endpoint: 'https://ark.cn-beijing.volces.com/api/plan/v3',
    model: 'doubao-pro-32k',
    notes: '火山引擎AgentPlan/豆包兼容接口。',
  },
  {
    id: 'byteplus',
    name: '🔵 BytePlus',
    endpoint: 'https://api.byteplus.com/v1',
    model: 'byteplus-v1',
    notes: 'BytePlus官方接口。',
  },
  {
    id: 'doubaoseed',
    name: '🟣 DouBaoSeed',
    endpoint: 'https://api.doubao.com/v1',
    model: 'doubao-seed-128k',
    notes: '字节跳动豆包Seed系列模型。',
  },
  {
    id: 'ccsub',
    name: '🟢 CCSub',
    endpoint: 'https://api.ccsub.com/v1',
    model: 'ccsub-7b',
    notes: 'CCSub模型接口。',
  },
  {
    id: 'unity2ai',
    name: '⚫ Unity2.ai',
    endpoint: 'https://api.unity2.ai/v1',
    model: 'unity-v1',
    notes: 'Unity2.ai官方接口。',
  },
  {
    id: 'azure_openai',
    name: '🔵 Azure OpenAI',
    endpoint: 'https://{resource}.openai.azure.com/openai/deployments/{deployment}/v1',
    model: 'gpt-4o',
    notes: '微软Azure OpenAI服务，需替换资源和部署名称。',
  },
  {
    id: 'deepseek',
    name: '🔍 DeepSeek',
    endpoint: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
    notes: '深度求索官方接口，支持deepseek-chat/deepseek-coder。',
  },
  {
    id: 'zhipu',
    name: '🔷 Zhipu GLM',
    endpoint: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'glm-4',
    notes: '智谱清言官方接口，支持GLM-4/GLM-3.5等模型。',
  },
  {
    id: 'zhipu_en',
    name: '🔷 Zhipu GLM en',
    endpoint: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'glm-4-air',
    notes: '智谱GLM英文模型系列。',
  },
  {
    id: 'qianfan',
    name: '🐾 百度千帆',
    endpoint: 'https://qianfan.baidubce.com/v2',
    model: 'ernie-3.5-8k',
    notes: '百度智能云千帆大模型平台兼容接口。',
  },
  {
    id: 'bailian',
    name: '🟣 Bailian',
    endpoint: 'https://bailian.aliyuncs.com/v1',
    model: 'qwen-max',
    notes: '阿里云百炼平台兼容接口。',
  },
  {
    id: 'kimi',
    name: '🟣 Kimi Moonshot',
    endpoint: 'https://api.moonshot.cn/v1',
    model: 'moonshot-v1-8k',
    notes: 'Moonshot AI官方接口，支持超长上下文。',
  },
  {
    id: 'kimi_coding',
    name: '🟣 Kimi For Coding',
    endpoint: 'https://api.moonshot.cn/v1',
    model: 'moonshot-coder-v1',
    notes: 'Kimi代码专用模型。',
  },
  {
    id: 'stepfun',
    name: '🔹 StepFun',
    endpoint: 'https://api.stepfun.com/v1',
    model: 'step-1-8k',
    notes: '阶跃星辰官方中文接口。',
  },
  {
    id: 'stepfun_en',
    name: '🔹 StepFun en',
    endpoint: 'https://api.stepfun.com/v1',
    model: 'step-1-32k',
    notes: '阶跃星辰英文模型系列。',
  },
  {
    id: 'modelscope',
    name: '🔵 ModelScope',
    endpoint: 'https://api.modelscope.cn/v1',
    model: 'modelscope-v1',
    notes: '阿里达摩院ModelScope平台接口。',
  },
  {
    id: 'longcat',
    name: '🟢 Longcat',
    endpoint: 'https://api.longcat.ai/v1',
    model: 'longcat-7b',
    notes: 'Longcat长上下文模型。',
  },
  {
    id: 'minimax',
    name: '🎙️ MiniMax',
    endpoint: 'https://api.minimax.chat/v1',
    model: 'minimax-chat-01',
    notes: 'MiniMax官方中文接口，支持abab大模型系列。',
  },
  {
    id: 'minimax_en',
    name: '🎙️ MiniMax en',
    endpoint: 'https://api.minimax.chat/v1',
    model: 'minimax-abab6.5',
    notes: 'MiniMax英文模型系列。',
  },
  {
    id: 'bailing',
    name: '⚪ BaiLing',
    endpoint: 'https://api.bailing.ai/v1',
    model: 'bailing-v1',
    notes: '百聆大模型接口。',
  },
  {
    id: 'xiaomi_mimo',
    name: '➖ Xiaomi MiMo',
    endpoint: 'https://api.mi.ai/v1',
    model: 'mimo-v1',
    notes: '小米MiMo大模型系列。',
  },
  {
    id: 'siliconflow',
    name: '💜 SiliconFlow',
    endpoint: 'https://api.siliconflow.cn/v1',
    model: 'deepseek-v3',
    notes: '硅基流动聚合平台，支持海量开源/商用模型（中文）。',
  },
  {
    id: 'siliconflow_en',
    name: '💜 SiliconFlow en',
    endpoint: 'https://api.siliconflow.com/v1',
    model: 'deepseek-v3',
    notes: '硅基流动国际版接口。',
  },
  {
    id: 'novita_ai',
    name: '▲ Novita AI',
    endpoint: 'https://api.novita.ai/v3/openai',
    model: 'novita-v1',
    notes: 'Novita AI大模型接口。',
  },
  {
    id: 'nvidia',
    name: '🟢 Nvidia',
    endpoint: 'https://api.nvcf.nvidia.com/v2',
    model: 'nvidia-llama-3',
    notes: '英伟达NIM模型接口。',
  },
  {
    id: 'aihubmix',
    name: '⚪ AiHubMix',
    endpoint: 'https://api.aihubmix.com/v1',
    model: 'aihubmix-v1',
    notes: 'AiHubMix聚合模型接口。',
  },
  {
    id: 'cherryin',
    name: '🔴 CherryIN',
    endpoint: 'https://api.cherryin.com/v1',
    model: 'cherry-v1',
    notes: 'CherryIN模型接口。',
  },
  {
    id: 'dmxapi',
    name: '⚪ DMXAPI',
    endpoint: 'https://api.dmxapi.com/v1',
    model: 'dmx-v1',
    notes: 'DMXAPI模型接口。',
  },
  {
    id: 'packycode',
    name: '⚫ PackyCode',
    endpoint: 'https://api.packycode.com/v1',
    model: 'packy-coder-v1',
    notes: 'PackyCode代码大模型接口。',
  },
  {
    id: 'apikey_fun',
    name: '🟠 APIKEY.FUN',
    endpoint: 'https://api.apikey.fun/v1',
    model: 'apikeyfun-v1',
    notes: 'APIKEY.FUN聚合模型接口。',
  },
  {
    id: 'apinebula',
    name: '⚪ APINebula',
    endpoint: 'https://api.apinebula.com/v1',
    model: 'apinebula-v1',
    notes: 'APINebula星云模型接口。',
  },
  {
    id: 'atlascloud',
    name: '▲ AtlasCloud',
    endpoint: 'https://api.atlascloud.ai/v1',
    model: 'atlas-v1',
    notes: 'AtlasCloud大模型接口。',
  },
  {
    id: 'sudocode',
    name: '🟣 SudoCode',
    endpoint: 'https://api.sudocode.com/v1',
    model: 'sudo-coder-v1',
    notes: 'SudoCode代码大模型接口。',
  },
  {
    id: 'claude_cn',
    name: '🧩 ClaudeCN',
    endpoint: 'https://claude.volcengineapi.com/v1',
    model: 'claude-3-5-sonnet',
    notes: '火山方舟Claude国内节点接口。',
  },
  {
    id: 'runapi',
    name: '⬛ RunAPI',
    endpoint: 'https://api.runapi.com/v1',
    model: 'runapi-v1',
    notes: 'RunAPI聚合模型接口。',
  },
  {
    id: 'relaxycode',
    name: '⚪ RelaxyCode',
    endpoint: 'https://api.relaxycode.com/v1',
    model: 'relaxy-coder-v1',
    notes: 'RelaxyCode代码模型接口。',
  },
  {
    id: 'cubence',
    name: '⬛ Cubence',
    endpoint: 'https://api.cubence.com/v1',
    model: 'cubence-v1',
    notes: 'Cubence模型接口。',
  },
  {
    id: 'aigocode',
    name: '🟣 AIGoCode',
    endpoint: 'https://api.aigocode.com/v1',
    model: 'aigo-coder-v1',
    notes: 'AIGoCode代码大模型接口。',
  },
  {
    id: 'rightcode',
    name: '🟠 RightCode',
    endpoint: 'https://api.rightcode.com/v1',
    model: 'right-coder-v1',
    notes: 'RightCode代码模型接口。',
  },
  {
    id: 'aicodemirror',
    name: '✖️ AICodeMirror',
    endpoint: 'https://api.aicodemirror.com/v1',
    model: 'aicm-v1',
    notes: 'AICodeMirror镜像模型接口。',
  },
  {
    id: 'crazyrouter',
    name: '⚪ CrazyRouter',
    endpoint: 'https://api.crazyrouter.ai/v1',
    model: 'crazy-v1',
    notes: 'CrazyRouter大模型路由接口。',
  },
  {
    id: 'sssaicode',
    name: '⬛ SSSAiCode',
    endpoint: 'https://api.sssaicode.com/v1',
    model: 'sssaicode-v1',
    notes: 'SSSAiCode代码模型接口。',
  },
  {
    id: 'youyun',
    name: '🟣 优云智算',
    endpoint: 'https://api.youyunzhisuan.com/v1',
    model: 'youyun-v1',
    notes: '优云智算大模型接口。',
  },
  {
    id: 'micu',
    name: '🔵 Micu',
    endpoint: 'https://api.micu.ai/v1',
    model: 'micu-v1',
    notes: 'Micu大模型接口。',
  },
  {
    id: 'ctok',
    name: '🔵 CTok.ai',
    endpoint: 'https://api.ctok.ai/v1',
    model: 'ctok-v1',
    notes: 'CTok.ai模型接口。',
  },
  {
    id: 'eflowcode',
    name: '⚪ E-FlowCode',
    endpoint: 'https://api.eflowcode.com/v1',
    model: 'eflow-coder-v1',
    notes: 'E-FlowCode代码模型接口。',
  },
  {
    id: 'pipellm',
    name: '⬛ PIPELLM',
    endpoint: 'https://api.pipellm.com/v1',
    model: 'pipe-v1',
    notes: 'PIPELLM流水线大模型接口。',
  },
  {
    id: 'openrouter',
    name: '🔄 OpenRouter',
    endpoint: 'https://openrouter.ai/api/v1',
    model: 'anthropic/claude-3-opus',
    notes: 'OpenRouter聚合平台，支持全球数百种模型。',
  },
  {
    id: 'therouter',
    name: '🔄 TheRouter',
    endpoint: 'https://api.therouter.ai/v1',
    model: 'router-v1',
    notes: 'TheRouter大模型路由接口。',
  },
  {
    id: 'ollama',
    name: '🐳 Ollama OpenAI 兼容',
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
