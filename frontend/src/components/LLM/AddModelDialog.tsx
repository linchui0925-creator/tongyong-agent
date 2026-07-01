import { useState, useEffect, useMemo } from 'react';
import { testLLMConnection, switchModel, saveModelConfig } from '../../api/llm';
import './AddModelDialog.css';

/* ── Provider registry ─────────────────────────────── */

interface ProviderOption {
  key: string;
  provider: string;
  name: string;
  apiKeyUrl: string;
  defaultEndpoint: string;
  models: { id: string; name: string }[];
}

const PROVIDERS: ProviderOption[] = [
  {
    key: 'openai', provider: 'openai', name: 'OpenAI',
    apiKeyUrl: 'https://platform.openai.com/api-keys',
    defaultEndpoint: 'https://api.openai.com/v1',
    models: [
      { id: 'gpt-4o', name: 'GPT-4o' },
      { id: 'gpt-4o-mini', name: 'GPT-4o Mini' },
      { id: 'gpt-4-turbo', name: 'GPT-4 Turbo' },
      { id: 'gpt-4', name: 'GPT-4' },
      { id: 'gpt-3.5-turbo', name: 'GPT-3.5 Turbo' },
      { id: 'o1', name: 'o1' },
      { id: 'o3-mini', name: 'o3-mini' },
    ],
  },
  {
    key: 'anthropic', provider: 'anthropic', name: 'Anthropic Claude',
    apiKeyUrl: 'https://console.anthropic.com/settings/keys',
    defaultEndpoint: 'https://api.anthropic.com/v1',
    models: [
      { id: 'claude-sonnet-4-20250514', name: 'Claude Sonnet 4' },
      { id: 'claude-opus-4-20250514', name: 'Claude Opus 4' },
      { id: 'claude-3-5-sonnet-latest', name: 'Claude 3.5 Sonnet' },
      { id: 'claude-3-5-haiku-20241022', name: 'Claude 3.5 Haiku' },
      { id: 'claude-3-opus-latest', name: 'Claude 3 Opus' },
    ],
  },
  {
    key: 'tongyi', provider: 'tongyi', name: '通义千问 (阿里云)',
    apiKeyUrl: 'https://help.aliyun.com/zh/dashscope/',
    defaultEndpoint: 'https://dashscope.aliyuncs.com/api/v1',
    models: [
      { id: 'qwen-max', name: 'Qwen Max' },
      { id: 'qwen-plus', name: 'Qwen Plus' },
      { id: 'qwen-turbo', name: 'Qwen Turbo' },
      { id: 'qwen2.5-72b-instruct', name: 'Qwen2.5 72B' },
      { id: 'qwen2.5-32b-instruct', name: 'Qwen2.5 32B' },
      { id: 'qwen2.5-14b-instruct', name: 'Qwen2.5 14B' },
      { id: 'qwen2.5-7b-instruct', name: 'Qwen2.5 7B' },
    ],
  },
  {
    key: 'google', provider: 'google', name: 'Google Gemini',
    apiKeyUrl: 'https://aistudio.google.com/apikey',
    defaultEndpoint: 'https://generativelanguage.googleapis.com/v1beta',
    models: [
      { id: 'gemini-2.0-flash', name: 'Gemini 2.0 Flash' },
      { id: 'gemini-2.0-flash-lite', name: 'Gemini 2.0 Flash Lite' },
      { id: 'gemini-1.5-pro', name: 'Gemini 1.5 Pro' },
      { id: 'gemini-1.5-flash', name: 'Gemini 1.5 Flash' },
    ],
  },
  {
    key: 'deepseek', provider: 'deepseek', name: 'DeepSeek',
    apiKeyUrl: 'https://platform.deepseek.com/api_keys',
    defaultEndpoint: 'https://api.deepseek.com/v1',
    models: [
      { id: 'deepseek-chat', name: 'DeepSeek Chat (V3)' },
      { id: 'deepseek-reasoner', name: 'DeepSeek Reasoner (R1)' },
    ],
  },
  {
    key: 'zhipu', provider: 'zhipu', name: '智谱AI (ChatGLM)',
    apiKeyUrl: 'https://open.bigmodel.cn/usercenter/apikeys',
    defaultEndpoint: 'https://open.bigmodel.cn/api/paas/v4',
    models: [
      { id: 'glm-4-plus', name: 'GLM-4 Plus' },
      { id: 'glm-4', name: 'GLM-4' },
      { id: 'glm-4-air', name: 'GLM-4 Air' },
      { id: 'glm-4-flash', name: 'GLM-4 Flash' },
      { id: 'glm-4v-plus', name: 'GLM-4V Plus' },
    ],
  },
  {
    // W4-41: edgefn.net 聚合代理 (一个 key 多模型)
    key: 'edgefn', provider: 'edgefn', name: 'EdgeFn 聚合 (GLM/DeepSeek)',
    apiKeyUrl: 'https://api.edgefn.net',
    defaultEndpoint: 'https://api.edgefn.net/v1',
    models: [
      { id: 'GLM-5.2', name: '智谱 GLM-5.2 (reasoning + function call, 推荐)' },
      { id: 'GLM-4-flash', name: '智谱 GLM-4 Flash (非 reasoning, 工具调用稳定)' },
      { id: 'deepseek-chat', name: 'DeepSeek V3 Chat (非 reasoning, 工具调用稳定)' },
      { id: 'deepseek-v4-flash', name: 'DeepSeek V4 Flash (reasoning)' },
      { id: 'deepseek-v4-pro', name: 'DeepSeek V4 Pro (此 key 403, 仅展示)' },
    ],
  },
  {
    key: 'wenxin', provider: 'wenxin', name: '百度文心',
    apiKeyUrl: 'https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application',
    defaultEndpoint: 'https://qianfan.baidubce.com/v2',
    models: [
      { id: 'ERNIE-4.5-8K-Preview', name: 'ERNIE 4.5' },
      { id: 'ERNIE-4.0-8K', name: 'ERNIE 4.0' },
      { id: 'ERNIE-3.5-8K', name: 'ERNIE 3.5' },
      { id: 'ERNIE-Speed-128K', name: 'ERNIE Speed' },
    ],
  },
  {
    key: 'baichuan', provider: 'baichuan', name: '百川智能',
    apiKeyUrl: 'https://platform.baichuan-ai.com/console/apikey',
    defaultEndpoint: 'https://api.baichuan-ai.com/v1',
    models: [
      { id: 'baichuan4-turbo', name: 'Baichuan 4 Turbo' },
      { id: 'baichuan4', name: 'Baichuan 4' },
      { id: 'baichuan3-turbo', name: 'Baichuan 3 Turbo' },
    ],
  },
  {
    key: 'xfyun', provider: 'xfyun', name: '讯飞星火',
    apiKeyUrl: 'https://www.xfyun.cn/account/api',
    defaultEndpoint: 'https://spark-api.xf-yun.com/v4.0',
    models: [
      { id: '4.0Ultra', name: '星火 4.0 Ultra' },
      { id: '4.0Turbo', name: '星火 4.0 Turbo' },
      { id: '3.5Max', name: '星火 3.5 Max' },
      { id: 'lite', name: '星火 Lite' },
    ],
  },
  {
    key: 'yi', provider: 'yi', name: '零一万物 (Yi)',
    apiKeyUrl: 'https://platform.lingyiwanwu.com/api-keys',
    defaultEndpoint: 'https://api.lingyiwanwu.com/v1',
    models: [
      { id: 'yi-large', name: 'Yi Large' },
      { id: 'yi-large-turbo', name: 'Yi Large Turbo' },
      { id: 'yi-medium', name: 'Yi Medium' },
    ],
  },
  {
    key: 'ollama', provider: 'ollama', name: 'Ollama (本地)',
    apiKeyUrl: '',
    defaultEndpoint: 'http://localhost:11434',
    models: [
      { id: 'llama3.2', name: 'Llama 3.2' },
      { id: 'llama3.1', name: 'Llama 3.1' },
      { id: 'qwen2.5', name: 'Qwen 2.5' },
      { id: 'mistral', name: 'Mistral' },
      { id: 'deepseek-r1', name: 'DeepSeek R1' },
      { id: 'phi4', name: 'Phi-4' },
      { id: 'gemma2', name: 'Gemma 2' },
    ],
  },
  {
    key: 'minimax-cn', provider: 'minimax', name: 'MiniMax (中国站)',
    apiKeyUrl: 'https://platform.minimaxi.com/user-center/basic-information',
    defaultEndpoint: 'https://api.minimaxi.com/v1',
    models: [
      { id: 'MiniMax-Text-01', name: 'MiniMax-Text-01 (456B/4M上下文)' },
      { id: 'MiniMax-M1', name: 'MiniMax-M1 (推理模型)' },
      { id: 'MiniMax-M2', name: 'MiniMax-M2 (128K上下文)' },
      { id: 'MiniMax-M2.1', name: 'MiniMax-M2.1' },
      { id: 'MiniMax-M2.5', name: 'MiniMax-M2.5 (编程/工具调用)' },
      { id: 'MiniMax-M2.7', name: 'MiniMax-M2.7 (旗舰)' },
    ],
  },
  {
    key: 'minimax-intl', provider: 'minimax', name: 'MiniMax (国际版)',
    apiKeyUrl: 'https://platform.minimax.io/',
    defaultEndpoint: 'https://api.minimax.chat/v1',
    models: [
      { id: 'MiniMax-Text-01', name: 'MiniMax-Text-01 (456B/4M上下文)' },
      { id: 'MiniMax-M1', name: 'MiniMax-M1 (推理模型)' },
      { id: 'MiniMax-M2', name: 'MiniMax-M2 (128K上下文)' },
      { id: 'MiniMax-M2.1', name: 'MiniMax-M2.1' },
      { id: 'MiniMax-M2.5', name: 'MiniMax-M2.5' },
      { id: 'MiniMax-M2.7', name: 'MiniMax-M2.7' },
    ],
  },
  {
    key: 'moonshot', provider: 'moonshot', name: '月之暗面 (Kimi)',
    apiKeyUrl: 'https://platform.moonshot.cn/console/api-keys',
    defaultEndpoint: 'https://api.moonshot.cn/v1',
    models: [
      { id: 'moonshot-v1-8k', name: 'Moonshot v1 8K' },
      { id: 'moonshot-v1-32k', name: 'Moonshot v1 32K' },
      { id: 'moonshot-v1-128k', name: 'Moonshot v1 128K' },
    ],
  },
  {
    key: 'stepfun', provider: 'stepfun', name: '阶跃星辰',
    apiKeyUrl: 'https://platform.stepfun.com/api-keys',
    defaultEndpoint: 'https://api.stepfun.com/v1',
    models: [
      { id: 'step-2-16k-nightly', name: 'Step 2 16K' },
      { id: 'step-1-32k', name: 'Step 1 32K' },
      { id: 'step-1-flash', name: 'Step 1 Flash' },
    ],
  },
  {
    key: 'siliconflow', provider: 'siliconflow', name: '硅基流动',
    apiKeyUrl: 'https://cloud.siliconflow.cn/account/ak',
    defaultEndpoint: 'https://api.siliconflow.cn/v1',
    models: [
      { id: 'Qwen/Qwen2.5-72B-Instruct', name: 'Qwen2.5 72B' },
      { id: 'deepseek-ai/DeepSeek-V3', name: 'DeepSeek V3' },
      { id: 'deepseek-ai/DeepSeek-R1', name: 'DeepSeek R1' },
      { id: 'meta-llama/Llama-3.3-70B-Instruct', name: 'Llama 3.3 70B' },
    ],
  },
];

/* ── Component ──────────────────────────────────────── */

interface AddModelDialogProps {
  open: boolean;
  onClose: () => void;
}

type TestStatus = 'idle' | 'testing' | 'success' | 'fail';

export default function AddModelDialog({ open, onClose }: AddModelDialogProps) {
  const [selectionKey, setSelectionKey] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [customEndpoint, setCustomEndpoint] = useState('');
  const [testStatus, setTestStatus] = useState<TestStatus>('idle');
  const [statusMessage, setStatusMessage] = useState('');
  const [saved, setSaved] = useState(false);

  const selectedProvider = useMemo(
    () => PROVIDERS.find(p => p.key === selectionKey),
    [selectionKey],
  );

  const providerId = selectedProvider?.provider ?? '';

  const availableModels = useMemo(
    () => selectedProvider?.models ?? [],
    [selectedProvider],
  );

  // Reset model when provider changes
  useEffect(() => {
    setModel('');
    setCustomEndpoint(selectedProvider?.defaultEndpoint ?? '');
    setTestStatus('idle');
    setStatusMessage('');
    setSaved(false);
  }, [selectionKey, selectedProvider]);

  const isValid = providerId && model && apiKey;

  const handleTest = async () => {
    if (!isValid) return;
    setTestStatus('testing');
    setStatusMessage('测试连接中...');
    try {
      const result = await testLLMConnection({
        provider: providerId,
        api_key: apiKey,
        api_endpoint: customEndpoint || undefined,
        model,
        temperature: 0.7,
        max_tokens: 2000,
      });
      if (result.success) {
        setTestStatus('success');
        setStatusMessage(`✅ 连接成功 — ${model}`);
      } else {
        setTestStatus('fail');
        setStatusMessage(`❌ 连接失败: ${result.message}`);
      }
    } catch (err: any) {
      setTestStatus('fail');
      setStatusMessage(`❌ 测试出错: ${err.message}`);
    }
  };

  const handleSaveSwitch = async () => {
    if (!isValid) return;

    // Test if not already successful
    if (testStatus !== 'success') {
      setTestStatus('testing');
      setStatusMessage('测试连接中...');
      try {
        const result = await testLLMConnection({
          provider: providerId,
          api_key: apiKey,
          api_endpoint: customEndpoint || undefined,
          model,
          temperature: 0.7,
          max_tokens: 2000,
        });
        if (!result.success) {
          setTestStatus('fail');
          setStatusMessage(`❌ 连接失败: ${result.message}`);
          return;
        }
        setTestStatus('success');
      } catch (err: any) {
        setTestStatus('fail');
        setStatusMessage(`❌ 测试出错: ${err.message}`);
        return;
      }
    }

    // Save to backend
    setStatusMessage('正在保存配置...');
    try {
      const saveResult = await saveModelConfig({
        provider: providerId,
        model,
        api_key: apiKey,
        api_endpoint: customEndpoint || undefined,
        name: `${selectedProvider?.name ?? providerId} — ${model}`,
      });
      if (!saveResult.success) {
        setStatusMessage(`❌ 保存失败: ${saveResult.message}`);
        return;
      }
    } catch (err: any) {
      setStatusMessage(`❌ 保存出错: ${err.message}`);
      return;
    }

    // Switch to the saved model
    setStatusMessage('正在切换到模型...');
    try {
      const result = await switchModel(providerId, apiKey, model, customEndpoint || undefined);
      if (result.success) {
        setSaved(true);
        setStatusMessage(`✅ 已保存并切换到 ${selectedProvider?.name ?? providerId} / ${model}`);
        setTimeout(() => onClose(), 1500);
      } else {
        setStatusMessage(`❌ 切换失败: ${result.message}`);
      }
    } catch (err: any) {
      setStatusMessage(`❌ 切换出错: ${err.message}`);
    }
  };

  if (!open) return null;

  return (
    <div className="add-model-overlay" onClick={onClose}>
      <div className="add-model-dialog" onClick={e => e.stopPropagation()}>
        <div className="add-model-header">
          <h2>添加模型</h2>
          <button className="add-model-close" onClick={onClose}>✕</button>
        </div>

        <div className="add-model-body">
          {/* Provider */}
          <div className="add-model-field">
            <label className="required">服务商</label>
            <select value={selectionKey} onChange={e => setSelectionKey(e.target.value)}>
              <option value="">— 请选择服务商 —</option>
              {PROVIDERS.map(p => (
                <option key={p.key} value={p.key}>{p.name}</option>
              ))}
            </select>
          </div>

          {/* Model */}
          <div className="add-model-field">
            <label className="required">模型</label>
            <select
              value={model}
              onChange={e => setModel(e.target.value)}
              disabled={!selectionKey}
            >
              <option value="">— 请选择模型 —</option>
              {availableModels.map(m => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          </div>

          {/* API Key */}
          <div className="add-model-field">
            <label className="required">API 密钥</label>
            <div className="api-key-wrapper">
              <input
                type="password"
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder="sk-..."
              />
              {selectedProvider?.apiKeyUrl && (
                <a
                  className="api-key-link"
                  href={selectedProvider.apiKeyUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  获取密钥 ↗
                </a>
              )}
            </div>
          </div>

          {/* Custom endpoint */}
          <div className="add-model-field">
            <label>自定义请求地址 <span style={{ color: 'var(--text-muted)', fontWeight: 400, textTransform: 'none' }}>（选填）</span></label>
            <input
              type="url"
              value={customEndpoint}
              onChange={e => setCustomEndpoint(e.target.value)}
              placeholder={selectedProvider?.defaultEndpoint ?? 'API 端点 URL'}
            />
          </div>

          {/* Status message */}
          {statusMessage && (
            <div className={`add-model-status ${testStatus === 'testing' ? 'pending' : testStatus === 'success' ? 'success' : 'error'}`}>
              {statusMessage}
            </div>
          )}

          {/* Actions */}
          <div className="add-model-actions">
            <button
              className={`btn-test ${testStatus === 'success' ? 'success' : testStatus === 'fail' ? 'fail' : ''}`}
              disabled={!isValid || testStatus === 'testing'}
              onClick={handleTest}
            >
              {testStatus === 'testing' ? '测试中...' : testStatus === 'success' ? '✓ 连接成功' : testStatus === 'fail' ? '✗ 重试测试' : '测试连接'}
            </button>
            <button
              className="btn-save"
              disabled={!isValid || testStatus === 'testing'}
              onClick={handleSaveSwitch}
            >
              {saved ? '✓ 已保存' : '保存并切换'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
