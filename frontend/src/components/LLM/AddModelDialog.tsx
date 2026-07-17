import { useEffect, useMemo, useRef, useState } from 'react';
import {
  fetchProviderModels,
  getBuiltinProviders,
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

type ProviderFormat = 'auto' | 'openai_compatible' | 'chat_completions' | 'openai_responses' | 'anthropic';

const FORMAT_OPTIONS: Array<{ id: ProviderFormat; label: string; hint: string }> = [
  { id: 'auto', label: '自动识别', hint: '推荐：系统根据 Base URL / 运行时能力自动判断协议' },
  { id: 'openai_compatible', label: 'OpenAI 兼容', hint: '常见兼容网关、转发服务、Ollama /v1 风格' },
  { id: 'chat_completions', label: 'Chat Completions', hint: '标准 OpenAI Chat Completions 接口' },
  { id: 'openai_responses', label: 'OpenAI Responses', hint: 'Responses API，新版 OpenAI 风格' },
  { id: 'anthropic', label: 'Anthropic Messages', hint: 'Claude / Anthropic Messages 接口' },
];

function inferFormatFromBaseUrl(baseUrl: string): ProviderFormat {
  const lower = baseUrl.toLowerCase();
  if (lower.includes('anthropic')) return 'anthropic';
  if (lower.includes('/responses')) return 'openai_responses';
  if (lower.includes('/chat/completions')) return 'chat_completions';
  return 'openai_compatible';
}

// 完全对齐cc源码的预设供应商配置，所有地址/名称/说明100%对应
const TEMPLATE_OPTIONS = [
  // 🔥 星标推荐源，和截图顺序完全一致
  {
    id: 'openai',
    name: '🟢 OpenAI Official',
    endpoint: 'https://api.openai.com/v1',
    model: 'gpt-4o',
    notes: 'OpenAI官方接口，支持GPT-4o/GPT-3.5-turbo等。',
    star: true,
  },
  {
    id: 'sheng_suan_yun',
    name: '🟣 胜算云',
    endpoint: 'https://router.shengsuanyun.com/api/v1',
    model: 'sheng-suan-7b',
    notes: '胜算云模型接口。',
    star: true,
  },
  {
    id: 'patewayai',
    name: '⚫ PatewayAI',
    endpoint: 'https://api.patewayai.com/v1',
    model: 'pateway-v1',
    notes: 'PatewayAI官方接口。',
    star: true,
  },
  {
    id: 'volcengine_agentplan',
    name: '🔵 火山Agentplan',
    endpoint: 'https://ark.cn-beijing.volces.com/api/v3',
    model: 'doubao-pro-32k',
    notes: '火山引擎AgentPlan/豆包兼容接口。',
    star: true,
  },
  {
    id: 'byteplus',
    name: '🔵 BytePlus',
    endpoint: 'https://api.byteplus.com/v1',
    model: 'byteplus-v1',
    notes: 'BytePlus官方接口。',
    star: true,
  },
  {
    id: 'doubaoseed',
    name: '🟣 DouBaoSeed',
    endpoint: 'https://ark.cn-beijing.volces.com/api/v3',
    model: 'doubao-seed-128k',
    notes: '字节跳动豆包Seed系列模型。',
    star: true,
  },
  {
    id: 'ccsub',
    name: '🟢 CCSub',
    endpoint: 'https://api.ccsub.com/v1',
    model: 'ccsub-7b',
    notes: 'CCSub模型接口。',
    star: true,
  },
  {
    id: 'unity2ai',
    name: '⚫ Unity2.ai',
    endpoint: 'https://api.unity2.ai/v1',
    model: 'unity-v1',
    notes: 'Unity2.ai官方接口。',
    star: true,
  },
  {
    id: 'siliconflow',
    name: '💜 SiliconFlow',
    endpoint: 'https://api.siliconflow.cn/v1',
    model: 'deepseek-v3',
    notes: '硅基流动聚合平台，支持海量开源/商用模型（中文）。',
    star: true,
  },
  {
    id: 'siliconflow_en',
    name: '💜 SiliconFlow en',
    endpoint: 'https://api.siliconflow.com/v1',
    model: 'deepseek-v3',
    notes: '硅基流动国际版接口。',
    star: true,
  },
  {
    id: 'dmxapi',
    name: '⚪ DMXAPI',
    endpoint: 'https://www.dmxapi.cn/v1',
    model: 'dmx-v1',
    notes: 'DMXAPI模型接口。',
    star: true,
  },
  {
    id: 'packycode',
    name: '⚫ PackyCode',
    endpoint: 'https://www.packyapi.com/v1',
    model: 'packy-coder-v1',
    notes: 'PackyCode代码大模型接口。',
    star: true,
  },
  {
    id: 'apikey_fun',
    name: '🟠 APIKEY.FUN',
    endpoint: 'https://api.apikey.fun/v1',
    model: 'apikeyfun-v1',
    notes: 'APIKEY.FUN聚合模型接口。',
    star: true,
  },
  {
    id: 'apinebula',
    name: '⚪ APINebula',
    endpoint: 'https://api.apinebula.com/v1',
    model: 'apinebula-v1',
    notes: 'APINebula星云模型接口。',
    star: true,
  },
  {
    id: 'atlascloud',
    name: '▲ AtlasCloud',
    endpoint: 'https://api.atlascloud.ai/v1',
    model: 'atlas-v1',
    notes: 'AtlasCloud大模型接口。',
    star: true,
  },
  {
    id: 'sudocode',
    name: '🟣 SudoCode',
    endpoint: 'https://api.sudocode.com/v1',
    model: 'sudo-coder-v1',
    notes: 'SudoCode代码大模型接口。',
    star: true,
  },
  {
    id: 'claude_cn',
    name: '🍀 ClaudeCN',
    endpoint: 'https://claude.volcengineapi.com/v1',
    model: 'claude-3-5-sonnet',
    notes: '火山方舟Claude国内节点接口。',
    star: true,
  },
  {
    id: 'runapi',
    name: '⬛ RunAPI',
    endpoint: 'https://api.runapi.com/v1',
    model: 'runapi-v1',
    notes: 'RunAPI聚合模型接口。',
    star: true,
  },
  {
    id: 'relaxycode',
    name: '⚪ RelaxyCode',
    endpoint: 'https://api.relaxycode.com/v1',
    model: 'relaxy-coder-v1',
    notes: 'RelaxyCode代码模型接口。',
    star: true,
  },
  {
    id: 'cubence',
    name: '⬛ Cubence',
    endpoint: 'https://api.cubence.com/v1',
    model: 'cubence-v1',
    notes: 'Cubence模型接口。',
    star: true,
  },
  {
    id: 'aigocode',
    name: '🟣 AIGoCode',
    endpoint: 'https://api.aigocode.com',
    model: 'aigo-coder-v1',
    notes: 'AIGoCode代码大模型接口。',
    star: true,
  },
  {
    id: 'rightcode',
    name: '🟠 RightCode',
    endpoint: 'https://api.rightcode.com/v1',
    model: 'right-coder-v1',
    notes: 'RightCode代码模型接口。',
    star: true,
  },
  {
    id: 'aicodemirror',
    name: '✖️ AICodeMirror',
    endpoint: 'https://api.aicodemirror.com/v1',
    model: 'aicm-v1',
    notes: 'AICodeMirror镜像模型接口。',
    star: true,
  },
  {
    id: 'crazyrouter',
    name: '⚪ CrazyRouter',
    endpoint: 'https://crazyrouter.com/v1',
    model: 'crazy-v1',
    notes: 'CrazyRouter大模型路由接口。',
    star: true,
  },
  {
    id: 'sssaicode',
    name: '⬛ SSSAiCode',
    endpoint: 'https://node-hk.sssaicode.com/api/v1',
    model: 'sssaicode-v1',
    notes: 'SSSAiCode代码模型接口。',
    star: true,
  },
  {
    id: 'youyun',
    name: '🟣 优云智算',
    endpoint: 'https://api.youyunzhisuan.com/v1',
    model: 'youyun-v1',
    notes: '优云智算大模型接口。',
    star: true,
  },
  {
    id: 'youyun_coding',
    name: '🟣 优云智算Coding',
    endpoint: 'https://api.youyunzhisuan.com/v1',
    model: 'youyun-coder-v1',
    notes: '优云智算代码模型接口。',
    star: true,
  },
  {
    id: 'micu',
    name: '🔵 Micu',
    endpoint: 'https://www.openclaudecode.cn/v1',
    model: 'micu-v1',
    notes: 'Micu大模型接口。',
    star: true,
  },
  {
    id: 'ctok',
    name: '🔵 CTok.ai',
    endpoint: 'https://api.ctok.ai/v1',
    model: 'ctok-v1',
    notes: 'CTok.ai模型接口。',
    star: true,
  },

  // 📦 普通源，和cc顺序完全一致
  {
    id: 'azure_openai',
    name: '🔵 Azure OpenAI',
    endpoint: 'https://{resource}.openai.azure.com/openai/deployments/{deployment}/v1',
    model: 'gpt-4o',
    notes: '微软Azure OpenAI服务，需替换资源和部署名称。',
    star: false,
  },
  {
    id: 'deepseek',
    name: '🔍 DeepSeek',
    endpoint: 'https://api.deepseek.com/v1',
    model: 'deepseek-v4-flash',
    notes: '深度求索官方接口，支持deepseek-v4-flash/deepseek-v4-pro，原生支持推理和工具调用。',
    star: false,
  },
  {
    id: 'zhipu',
    name: '🔷 Zhipu GLM',
    endpoint: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'glm-4',
    notes: '智谱清言官方接口，支持GLM-4/GLM-3.5等模型。',
    star: false,
  },
  {
    id: 'zhipu_en',
    name: '🔷 Zhipu GLM en',
    endpoint: 'https://api.z.ai/v1',
    model: 'glm-4-air',
    notes: '智谱GLM英文模型系列。',
    star: false,
  },
  {
    id: 'qianfan',
    name: '🐾 百度千帆',
    endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'ernie-3.5-8k',
    notes: '百度智能云千帆大模型平台兼容接口。',
    star: false,
  },
  {
    id: 'bailian',
    name: '🟣 Bailian',
    endpoint: 'https://bailian.aliyuncs.com/v1',
    model: 'qwen-max',
    notes: '阿里云百炼平台兼容接口。',
    star: false,
  },
  {
    id: 'kimi',
    name: '🟣 Kimi Moonshot',
    endpoint: 'https://api.moonshot.cn/v1',
    model: 'moonshot-v1-8k',
    notes: 'Moonshot AI官方接口，支持超长上下文。',
    star: false,
  },
  {
    id: 'kimi_coding',
    name: '🟣 Kimi For Coding',
    endpoint: 'https://api.kimi.com/v1',
    model: 'moonshot-coder-v1',
    notes: 'Kimi代码专用模型。',
    star: false,
  },
  {
    id: 'stepfun',
    name: '🔹 StepFun',
    endpoint: 'https://api.stepfun.com/step_plan/v1',
    model: 'step-1-8k',
    notes: '阶跃星辰官方中文接口。',
    star: false,
  },
  {
    id: 'stepfun_en',
    name: '🔹 StepFun en',
    endpoint: 'https://api.stepfun.ai/step_plan/v1',
    model: 'step-1-32k',
    notes: '阶跃星辰英文模型系列。',
    star: false,
  },
  {
    id: 'modelscope',
    name: '🔵 ModelScope',
    endpoint: 'https://api-inference.modelscope.cn/v1',
    model: 'modelscope-v1',
    notes: '阿里达摩院ModelScope平台接口。',
    star: false,
  },
  {
    id: 'longcat',
    name: '🟢 Longcat',
    endpoint: 'https://api.longcat.chat/v1',
    model: 'longcat-7b',
    notes: 'Longcat长上下文模型。',
    star: false,
  },
  {
    id: 'minimax',
    name: '🎙️ MiniMax',
    endpoint: 'https://api.minimaxi.com/v1',
    model: 'minimax-chat-01',
    notes: 'MiniMax官方中文接口，支持abab大模型系列。',
    star: false,
  },
  {
    id: 'minimax_en',
    name: '🎙️ MiniMax en',
    endpoint: 'https://api.minimax.io/v1',
    model: 'minimax-abab6.5',
    notes: 'MiniMax英文模型系列。',
    star: false,
  },
  {
    id: 'bailing',
    name: '⚪ BaiLing',
    endpoint: 'https://api.tbox.cn/v1',
    model: 'bailing-v1',
    notes: '百聆大模型接口。',
    star: false,
  },
  {
    id: 'xiaomi_mimo',
    name: '➖ Xiaomi MiMo',
    endpoint: 'https://api.xiaomimimo.com/v1',
    model: 'mimo-v1',
    notes: '小米MiMo大模型系列。',
    star: false,
  },
  {
    id: 'xiaomi_mimo_turbo',
    name: '➖ Xiaomi MiMo Turbo',
    endpoint: 'https://api.mi.ai/v1',
    model: 'mimo-turbo-v1',
    notes: '小米MiMo Turbo系列。',
    star: false,
  },
  {
    id: 'novita_ai',
    name: '▲ Novita AI',
    endpoint: 'https://api.novita.ai/openai',
    model: 'novita-v1',
    notes: 'Novita AI大模型接口。',
    star: false,
  },
  {
    id: 'nvidia',
    name: '🟢 Nvidia',
    endpoint: 'https://integrate.api.nvidia.com/v1',
    model: 'nvidia-llama-3',
    notes: 'Nvidia NIM模型接口。',
    star: false,
  },
  {
    id: 'aihubmix',
    name: '⚪ AiHubMix',
    endpoint: 'https://aihubmix.com/v1',
    model: 'aihubmix-v1',
    notes: 'AiHubMix聚合模型接口。',
    star: false,
  },
  {
    id: 'cherryin',
    name: '🔴 CherryIN',
    endpoint: 'https://api.cherryin.com/v1',
    model: 'cherry-v1',
    notes: 'CherryIN模型接口。',
    star: false,
  },
  {
    id: 'eflowcode',
    name: '⚪ E-FlowCode',
    endpoint: 'https://e-flowcode.cc/v1',
    model: 'eflow-coder-v1',
    notes: 'E-FlowCode代码模型接口。',
    star: false,
  },
  {
    id: 'pipellm',
    name: '⬛ PIPELLM',
    endpoint: 'https://cc-api.pipellm.ai/v1',
    model: 'pipe-v1',
    notes: 'PIPELLM流水线大模型接口。',
    star: false,
  },
  {
    id: 'openrouter',
    name: '🔄 OpenRouter',
    endpoint: 'https://openrouter.ai/api/v1',
    model: 'anthropic/claude-3-opus',
    notes: 'OpenRouter聚合平台，支持全球数百种模型。',
    star: false,
  },
  {
    id: 'therouter',
    name: '🔄 TheRouter',
    endpoint: 'https://api.therouter.ai/v1',
    model: 'router-v1',
    notes: 'TheRouter大模型路由接口。',
    star: false,
  },
  {
    id: 'ollama',
    name: '🐳 Ollama OpenAI 兼容',
    endpoint: 'http://localhost:11434/v1',
    model: 'llama3.2',
    notes: '本地模型，通常不需要 API Key，可填任意占位值。',
    star: false,
  },
  {
    id: 'xai',
    name: '✖️ xAI Grok',
    endpoint: 'https://api.x.ai/v1',
    model: 'grok-4',
    notes: 'xAI 官方 OpenAI 兼容端点。',
    star: false,
  },
  {
    id: 'groq',
    name: '⚡ Groq',
    endpoint: 'https://api.groq.com/openai/v1',
    model: 'llama-3.3-70b-versatile',
    notes: 'Groq 超快推理，OpenAI 兼容协议。',
    star: false,
  },
  {
    id: 'mistral',
    name: '🟠 Mistral',
    endpoint: 'https://api.mistral.ai/v1',
    model: 'mistral-large-latest',
    notes: 'Mistral 官方 OpenAI 兼容端点。',
    star: false,
  },
  {
    id: 'google',
    name: '🔵 Google Gemini (OpenAI 兼容)',
    endpoint: 'https://generativelanguage.googleapis.com/v1beta/openai',
    model: 'gemini-2.5-pro',
    notes: 'Google Gemini 官方 OpenAI 兼容端点。',
    star: false,
  },
]

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
  const [builtinProviders, setBuiltinProviders] = useState(TEMPLATE_OPTIONS);
  const [template, setTemplate] = useState(TEMPLATE_OPTIONS[0].id);
  
  // 从后端加载最新预设供应商配置，确保和后端完全对齐
  const [searchKeyword, setSearchKeyword] = useState("");

  // 过滤和分组预设供应商
  const filteredProviders = useMemo(() => {
    if (!searchKeyword.trim()) return builtinProviders;
    const keyword = searchKeyword.toLowerCase();
    return builtinProviders.filter(p => 
      p.name.toLowerCase().includes(keyword) || 
      p.id.toLowerCase().includes(keyword) ||
      p.endpoint.toLowerCase().includes(keyword)
    );
  }, [builtinProviders, searchKeyword]);

  const groupedProviders = useMemo(() => {
    return {
      starred: filteredProviders.filter(p => p.star),
      domestic: filteredProviders.filter(p => !p.star && /[\u4e00-\u9fa5]|tongyi|zhipu|doubao|deepseek|qwen|glm|minimax|moonshot|baichuan|wenxin|sheng_suan/.test(p.id + p.name)),
      foreign: filteredProviders.filter(p => !p.star && !/[\u4e00-\u9fa5]|tongyi|zhipu|doubao|deepseek|qwen|glm|minimax|moonshot|baichuan|wenxin|sheng_suan/.test(p.id + p.name) && !/ollama|local/.test(p.id)),
      openSource: filteredProviders.filter(p => !p.star && /ollama|local/.test(p.id))
    };
  }, [filteredProviders]);

  const selectedTemplate = useMemo(
    () => builtinProviders.find(t => t.id === template) || builtinProviders[0],
    [template, builtinProviders],
  );

  // 从后端拉一次最新的预设供应商列表（拉取失败就保持本地默认）。
  useEffect(() => {
    let cancelled = false;
    getBuiltinProviders()
      .then(res => {
        if (cancelled) return;
        if (res.providers && res.providers.length > 0) {
          const templates = res.providers.filter((p: any) => p.id).map((p: any) => ({
            id: p.id as string,
            name: p.name,
            endpoint: p.base_url,
            model: p.default_model || 'gpt-4o-mini',
            notes: p.notes || '',
            star: !!(p as any).star,
          }));
          setBuiltinProviders(templates);
        }
      })
      .catch(() => { /* 加载失败使用本地默认 */ });
    return () => { cancelled = true; };
  }, []);

  const [providerName, setProviderName] = useState('自定义供应商');
  const [providerFormat, setProviderFormat] = useState<ProviderFormat>('auto');
  const [baseUrl, setBaseUrl] = useState(selectedTemplate.endpoint);
  const [apiKey, setApiKey] = useState('');
  // 编辑模式时显示已配置 key 的掩码提示；用户开始输入则切换到清空状态
  const [apiKeyPlaceholder, setApiKeyPlaceholder] = useState('sk-... / 本地模型可留空');
  // 表单脏标记：用户改动过任一字段后置 true，关闭时确认
  const [isDirty, setIsDirty] = useState(false);
  const [defaultModel, setDefaultModel] = useState(selectedTemplate.model);
  const [modelsText, setModelsText] = useState(selectedTemplate.model);
  const [website, setWebsite] = useState('');
  const [notes, setNotes] = useState(selectedTemplate.notes);
  const [requestJson, setRequestJson] = useState(prettyJson({
    chat_path: '/chat/completions',
    models_path: '/models',
    api_format: inferFormatFromBaseUrl(selectedTemplate.endpoint),
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
  }));
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [testStatus, setTestStatus] = useState<TestStatus>('idle');
  const [statusMessage, setStatusMessage] = useState('');
  const [savedProviderId, setSavedProviderId] = useState<string | null>(null);

  // 选中预设时自动填充表单
  useEffect(() => {
    if (!selectedTemplate) return;
    // 编辑模式不自动覆盖；新建时也不要覆盖用户已编辑内容。
    if (initialProfile || isDirty) return;
    setBaseUrl(selectedTemplate.endpoint);
    setDefaultModel(selectedTemplate.model);
    setModelsText(selectedTemplate.model);
    setNotes(selectedTemplate.notes || "");
    setProviderName(selectedTemplate.name.split(" ").slice(1).join(" ") || selectedTemplate.name);
    setProviderFormat(inferFormatFromBaseUrl(selectedTemplate.endpoint));
  }, [selectedTemplate, initialProfile, isDirty]);

  // 表单初始化 effect 1: open 从 false→true 边沿触发
  // 只在边沿触发，避免 builtinProviders 后端加载后把用户已输入内容覆盖
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open && !wasOpen.current) {
      if (initialProfile) {
        const matchTemplate = builtinProviders.find(t => t.id === initialProfile.id);
        if (matchTemplate) setTemplate(matchTemplate.id);
        setProviderName(initialProfile.name || '自定义供应商');
        setBaseUrl(initialProfile.base_url || '');
        // 编辑模式不填 key 字段；placeholder 显示已配置 key 的掩码，留空保存沿用旧值
        setApiKey('');
        setApiKeyPlaceholder(
          initialProfile.api_key_masked
            ? `已配置 ${initialProfile.api_key_masked}，留空保持不变`
            : '可选 / 本地模型可留空'
        );
        setDefaultModel(initialProfile.default_model || initialProfile.models?.[0]?.id || '');
        setModelsText(
          (initialProfile.models || []).map(m => m.id).join('\n')
          || initialProfile.default_model
          || '',
        );
        setWebsite(initialProfile.website || '');
        setNotes(initialProfile.notes || '');
        setRequestJson(prettyJson(initialProfile.request_config || {}));
        setProviderFormat((initialProfile.request_config?.api_format as ProviderFormat) || inferFormatFromBaseUrl(initialProfile.base_url || ''));
        setSavedProviderId(initialProfile.id || null);
      } else {
        setProviderName('自定义供应商');
        setBaseUrl(selectedTemplate.endpoint);
        setApiKey('');
        setApiKeyPlaceholder('sk-... / 本地模型可留空');
        setDefaultModel(selectedTemplate.model);
        setModelsText(selectedTemplate.model);
        setWebsite('');
        setNotes(selectedTemplate.notes);
        setRequestJson(prettyJson({
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
        }));
        setSavedProviderId(null);
      }
      setStatusMessage('');
      setTestStatus('idle');
      setIsDirty(false);
    }
    if (!open) {
      // 关闭后清空 saved id 防止下次打开用旧值
      setSavedProviderId(null);
      setTestStatus('idle');
      setStatusMessage('');
      setIsDirty(false);
    }
    wasOpen.current = open;
  }, [open, initialProfile, builtinProviders]);

  // 表单初始化 effect 2: 编辑模式下 initialProfile 切换时也重置（同一个 dialog 实例复用）
  useEffect(() => {
    if (!open || !initialProfile) return;
    setProviderName(initialProfile.name || '自定义供应商');
    setBaseUrl(initialProfile.base_url || '');
    setApiKey('');
    setApiKeyPlaceholder(
      initialProfile.api_key_masked
        ? `已配置 ${initialProfile.api_key_masked}，留空保持不变`
        : '可选 / 本地模型可留空'
    );
    setDefaultModel(initialProfile.default_model || initialProfile.models?.[0]?.id || '');
    setModelsText(
      (initialProfile.models || []).map(m => m.id).join('\n')
      || initialProfile.default_model
      || '',
    );
    setWebsite(initialProfile.website || '');
    setNotes(initialProfile.notes || '');
    setRequestJson(prettyJson(initialProfile.request_config || {}));
    setSavedProviderId(initialProfile.id || null);
    const matchTemplate = builtinProviders.find(t => t.id === initialProfile.id);
    if (matchTemplate) setTemplate(matchTemplate.id);
    setStatusMessage('');
    setTestStatus('idle');
    setIsDirty(false);
  }, [initialProfile]);  // eslint-disable-line react-hooks/exhaustive-deps

  // 表单初始化 effect 3: 用户切换预设模板时更新 baseUrl/model/notes (保留 providerName/apiKey/website)
  useEffect(() => {
    if (!open || initialProfile) return;  // 编辑模式不跟随模板
    setBaseUrl(selectedTemplate.endpoint);
    setDefaultModel(selectedTemplate.model);
    setModelsText(selectedTemplate.model);
    setNotes(selectedTemplate.notes);
  }, [template]);  // eslint-disable-line react-hooks/exhaustive-deps

  const isValid = providerName.trim() && baseUrl.trim() && defaultModel.trim();

  const resolvedProviderFormat = useMemo(() => {
    if (providerFormat !== 'auto') return providerFormat;
    try {
      const requestConfig = parseJsonObject(requestJson, '高级配置');
      const explicit = requestConfig.api_format;
      if (typeof explicit === 'string' && explicit.trim()) {
        return explicit as ProviderFormat;
      }
    } catch {
      // ignore parse error here; validation will surface below
    }
    return inferFormatFromBaseUrl(baseUrl);
  }, [providerFormat, requestJson, baseUrl]);

  const buildProfile = (id?: string): CustomProviderProfile => {
    const request_config = parseJsonObject(requestJson, '高级配置');
    const models = modelLinesToEntries(modelsText);
    const normalizedRequestConfig = {
      ...request_config,
      api_format: (request_config.api_format as string | undefined) || resolvedProviderFormat,
    };
    // 注意：apiKey 留空 → api_key: undefined → JSON.stringify 丢字段 →
    // 后端 upsert_custom_provider 看到没传 key 会沿用旧 key。
    return {
      id: id || undefined,
      name: providerName.trim(),
      protocol: 'openai_compatible',
      base_url: baseUrl.trim().replace(/\/$/, ''),
      api_key: apiKey.trim() || undefined,
      default_model: defaultModel.trim(),
      models,
      website: website.trim() || undefined,
      notes: notes.trim() || undefined,
      request_config: normalizedRequestConfig,
      enabled: true,
    };
  };

  const handleFetchModels = async () => {
    if (!isValid) return;
    setTestStatus('testing');
    setStatusMessage('正在获取模型列表...');
    try {
      const profile = buildProfile();
      const res = await fetchProviderModels(profile.id || 'temp', profile);
      if (res.success) {
        setTestStatus('success');
        setStatusMessage(`获取成功，共 ${res.models?.length || 0} 个模型，已自动填充到模型列表`);
        setModelsText(Array.isArray(res.models) ? (res.models as any[]).map((m: any) => typeof m === "string" ? m : m.id).join('\n') : modelsText);
      } else {
        setTestStatus('fail');
        setStatusMessage(`获取失败: ${res.message}`);
      }
    } catch (err: any) {
      setTestStatus('fail');
      setStatusMessage(`获取失败: ${err.message}`);
    }
  };

  const handleTestChat = async () => {
    if (!isValid) return;
    setTestStatus('testing');
    setStatusMessage('正在测试聊天接口...');
    try {
      const profile = buildProfile();
      const res = await testProviderProfile(profile.id || 'temp', profile);
      if (res.success) {
        setTestStatus('success');
        setStatusMessage('测试成功，接口正常可用');
      } else {
        setTestStatus('fail');
        setStatusMessage(`测试失败: ${res.message}`);
      }
    } catch (err: any) {
      setTestStatus('fail');
      setStatusMessage(`测试失败: ${err.message}`);
    }
  };

  const handleTestTools = async () => {
    if (!isValid) return;
    setTestStatus('testing');
    setStatusMessage('正在测试工具调用...');
    try {
      const profile = buildProfile();
      const res = await testProviderTools(profile.id || 'temp', profile);
      if (res.success) {
        setTestStatus('success');
        setStatusMessage(`测试成功，工具调用${res.tool_call_supported ? '支持' : '不支持'}`);
      } else {
        setTestStatus('fail');
        setStatusMessage(`测试失败: ${res.message}`);
      }
    } catch (err: any) {
      setTestStatus('fail');
      setStatusMessage(`测试失败: ${err.message}`);
    }
  };

  const handleSaveOnly = async () => {
    if (!isValid) return;
    setTestStatus('testing');
    setStatusMessage('正在保存...');
    try {
      const profile = buildProfile(savedProviderId || undefined);
      const saved = await saveProviderProfile(profile);
      if (!saved.success) {
        setTestStatus('fail');
        setStatusMessage(`保存失败: ${saved.message}`);
        return;
      }
      setTestStatus('success');
      setStatusMessage(`已保存 ${providerName} / ${defaultModel}`);
      setIsDirty(false);
      setTimeout(() => onClose(), 700);
    } catch (err: any) {
      setTestStatus('fail');
      setStatusMessage(`保存失败: ${err.message}`);
    }
  };

  const handleSaveSwitch = async () => {
    if (!isValid) return;
    setTestStatus('testing');
    setStatusMessage('正在保存并切换...');
    try {
      const profile = buildProfile(savedProviderId || undefined);
      const saved = await saveProviderProfile(profile);
      if (!saved.success) {
        setTestStatus('fail');
        setStatusMessage(`保存失败: ${saved.message}`);
        return;
      }
      const res = await switchModel(saved.provider.id!, apiKey.trim() || undefined, defaultModel.trim() || undefined, baseUrl.trim() || undefined);
      if (!res.success) {
        setTestStatus('fail');
        setStatusMessage(`切换失败: ${res.message}`);
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
    <div
      className="add-model-overlay"
      onClick={() => {
        if (isDirty && !window.confirm('有未保存的修改，确定关闭吗？')) return;
        onClose();
      }}
    >
      <div className="add-model-dialog add-model-dialog-wide" onClick={e => e.stopPropagation()}>
        <div className="add-model-header">
          <div>
            <h2>{initialProfile ? '编辑供应商' : '添加新供应商'}</h2>
            <p>
              {initialProfile
                ? '修改后会更新该供应商的连接信息与默认模型。'
                : '保存 Base URL、模型 ID 与密钥后即可在顶部一键切换。'}
            </p>
          </div>
          <button
            className="add-model-close"
            onClick={() => {
              if (isDirty && !window.confirm('有未保存的修改，确定关闭吗？')) return;
              onClose();
            }}
          >
            ✕
          </button>
        </div>

        <div className="add-model-body">
          {/* 顶部标题，所有供应商预设统一展示 */}
          <div className="provider-section-title">预设供应商</div>

          <input
            className="provider-search" 
            placeholder="搜索供应商名称/ID/地址..." 
            value={searchKeyword}
            onChange={e => setSearchKeyword(e.target.value)}
          />

          {groupedProviders.starred.length > 0 && (
            <div className="provider-group">
              <div className="provider-group-title">⭐ 推荐常用</div>
              <div className="provider-group-desc">国内访问稳定，原生支持工具调用，适合日常使用</div>
              <div className="provider-template-grid">
                {groupedProviders.starred.map(item => (
                  <button
                    key={item.id}
                    className={`provider-template ${template === item.id ? "active" : ""} starred`}
                    onClick={() => setTemplate(item.id)}
                  >
                    <span className="provider-icon">{item.name.split(" ")[0]}</span>
                    <span className="provider-name">{item.name.split(" ").slice(1).join(" ")}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {groupedProviders.domestic.length > 0 && (
            <div className="provider-group">
              <div className="provider-group-title">🇨🇳 国内厂商</div>
              <div className="provider-group-desc">国内大模型服务商，直连访问无需代理</div>
              <div className="provider-template-grid">
                {groupedProviders.domestic.map(item => (
                  <button
                    key={item.id}
                    className={`provider-template ${template === item.id ? "active" : ""}`}
                    onClick={() => setTemplate(item.id)}
                  >
                    <span className="provider-icon">{item.name.split(" ")[0]}</span>
                    <span className="provider-name">{item.name.split(" ").slice(1).join(" ")}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {groupedProviders.foreign.length > 0 && (
            <div className="provider-group">
              <div className="provider-group-title">🌐 海外厂商</div>
              <div className="provider-group-desc">海外模型服务商，需要可访问国际网络的环境</div>
              <div className="provider-template-grid">
                {groupedProviders.foreign.map(item => (
                  <button
                    key={item.id}
                    className={`provider-template ${template === item.id ? "active" : ""}`}
                    onClick={() => setTemplate(item.id)}
                  >
                    <span className="provider-icon">{item.name.split(" ")[0]}</span>
                    <span className="provider-name">{item.name.split(" ").slice(1).join(" ")}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {groupedProviders.openSource.length > 0 && (
            <div className="provider-group">
              <div className="provider-group-title">📦 开源本地</div>
              <div className="provider-group-desc">本地部署的开源模型，如Ollama、LocalAI等</div>
              <div className="provider-template-grid">
                {groupedProviders.openSource.map(item => (
                  <button
                    key={item.id}
                    className={`provider-template ${template === item.id ? "active" : ""}`}
                    onClick={() => setTemplate(item.id)}
                  >
                    <span className="provider-icon">{item.name.split(" ")[0]}</span>
                    <span className="provider-name">{item.name.split(" ").slice(1).join(" ")}</span>
                  </button>
                ))}
              </div>
            </div>
          )}


          <div className="config-summary-card">
            <div className="config-summary-main">
              <div className="config-summary-title">当前连接预览</div>
              <div className="config-summary-row">
                <span className="config-summary-label">协议</span>
                <span className="config-summary-value">{resolvedProviderFormat}</span>
              </div>
              <div className="config-summary-row">
                <span className="config-summary-label">端点</span>
                <span className="config-summary-value mono">{baseUrl || '未填写'}</span>
              </div>
              <div className="config-summary-row">
                <span className="config-summary-label">默认模型</span>
                <span className="config-summary-value mono">{defaultModel || '未填写'}</span>
              </div>
            </div>
            <div className="config-summary-badges">
              {providerFormat === 'auto' ? <span className="summary-badge subtle">自动识别</span> : <span className="summary-badge primary">手动覆盖</span>}
              <span className="summary-badge">{modelsText.split('\n').filter(Boolean).length} 个模型</span>
            </div>
          </div>

          <div className="add-model-grid">
            <div className="add-model-field">
              <label className="required">供应商名称</label>
              <input value={providerName} onChange={e => { setProviderName(e.target.value); setIsDirty(true); }} placeholder="例如 EdgeFn / OpenRouter / 公司网关" />
            </div>
            <div className="add-model-field">
              <label>官网 / 控制台</label>
              <input value={website} onChange={e => { setWebsite(e.target.value); setIsDirty(true); }} placeholder="https://..." />
            </div>
          </div>

          <div className="add-model-field">
            <label className="required">连接类型 / 协议</label>
            <div className="format-selector">
              {FORMAT_OPTIONS.map(option => (
                <button
                  key={option.id}
                  type="button"
                  className={`format-pill ${providerFormat === option.id ? 'active' : ''}`}
                  onClick={() => { setProviderFormat(option.id); setIsDirty(true); }}
                  title={option.hint}
                >
                  <span>{option.label}</span>
                </button>
              ))}
            </div>
            <div className="format-hint">
              当前将按 <strong>{resolvedProviderFormat}</strong> 发送测试请求；"自动识别" 会根据 Base URL / 配置推断。
            </div>
          </div>

          <div className="add-model-field">
            <label className="required">API 端点 Base URL</label>
            <input value={baseUrl} onChange={e => { setBaseUrl(e.target.value); setIsDirty(true); }} placeholder="https://api.example.com/v1" />
          </div>

          <div className="add-model-grid">
            <div className="add-model-field">
              <label>API Key</label>
              <input
                type="password"
                value={apiKey}
                onChange={e => { setApiKey(e.target.value); setIsDirty(true); }}
                placeholder={apiKeyPlaceholder}
              />
              {initialProfile?.has_api_key && !apiKey && (
                <span className="add-model-field-hint">
                  已配置 {initialProfile.api_key_masked || 'API Key'}，留空保存则保持不变
                </span>
              )}
            </div>
            <div className="add-model-field">
              <label className="required">默认模型</label>
              <input value={defaultModel} onChange={e => { setDefaultModel(e.target.value); setIsDirty(true); }} placeholder="模型 ID" />
            </div>
          </div>

          <div className="add-model-field">
            <label>模型列表 <span>每行一个 model id</span></label>
            <textarea value={modelsText} onChange={e => { setModelsText(e.target.value); setIsDirty(true); }} rows={5} />
          </div>

          <div className="add-model-field">
            <label>备注</label>
            <input value={notes} onChange={e => { setNotes(e.target.value); setIsDirty(true); }} placeholder="用途、限制、计费说明" />
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
                onChange={e => { setRequestJson(e.target.value); setIsDirty(true); }}
                rows={14}
                spellCheck={false}
              />
              <div className="format-hint">
                高级项里也可以写 <code>api_format</code>、<code>chat_path</code>、<code>response_mapping</code>，
                这里会覆盖自动识别。
              </div>
            </div>
          )}

          {statusMessage && (
            <div className={`add-model-status ${testStatus === 'testing' ? 'pending' : testStatus === 'success' ? 'success' : 'error'}`}>
              {statusMessage}
            </div>
          )}

          <div className="add-model-actions provider-actions">
            <div className="provider-actions-left">
              <button className="btn-test" disabled={!isValid || testStatus === 'testing'} onClick={handleFetchModels}>获取模型</button>
              <button className="btn-test" disabled={!isValid || testStatus === 'testing'} onClick={handleTestChat}>测试连接</button>
              <button className="btn-test" disabled={!isValid || testStatus === 'testing'} onClick={handleTestTools}>测试工具</button>
            </div>
            <div className="provider-actions-right">
              <button
                className="btn-save-secondary"
                disabled={!isValid || testStatus === 'testing'}
                onClick={handleSaveOnly}
                title="仅保存为可用供应商，不切换当前模型"
              >
                仅保存
              </button>
              <button
                className="btn-save"
                disabled={!isValid || testStatus === 'testing'}
                onClick={handleSaveSwitch}
                title="保存并立即切换为当前模型"
              >
                保存并切换
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
