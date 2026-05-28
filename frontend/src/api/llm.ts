const API_BASE = '/api/llm';

export interface ModelConfig {
    provider: string;
    api_key?: string;
    api_endpoint?: string;
    model?: string;
    temperature: number;
    max_tokens: number;
    top_p?: number;
}

export interface ModelStatus {
    provider: string;
    model: string;
    status: string;
    available: boolean;
    error?: string;
}

export interface LLMSettings {
    default_provider: string;
    available_providers: string[];
    current_config: ModelConfig;
}

export interface ConfigUpdateResult {
    success: boolean;
    config: ModelConfig;
    message: string;
}

export interface TestResult {
    success: boolean;
    message: string;
    model?: string;
    error?: string;
}

export async function getLLMConfig(): Promise<LLMSettings> {
    const response = await fetch(`${API_BASE}/config`);
    if (!response.ok) {
        throw new Error('获取LLM配置失败');
    }
    return response.json();
}

export async function getModelStatus(): Promise<ModelStatus[]> {
    const response = await fetch(`${API_BASE}/status`);
    if (!response.ok) {
        throw new Error('获取模型状态失败');
    }
    return response.json();
}

export async function updateLLMConfig(config: ModelConfig): Promise<ConfigUpdateResult> {
    const response = await fetch(`${API_BASE}/config`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(config),
    });
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || '更新LLM配置失败');
    }
    return response.json();
}

export async function testLLMConnection(config: ModelConfig): Promise<TestResult> {
    const response = await fetch(`${API_BASE}/test`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(config),
    });
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || '测试连接失败');
    }
    return response.json();
}

export async function switchModel(provider: string, apiKey?: string, model?: string, apiEndpoint?: string): Promise<ConfigUpdateResult> {
    const response = await fetch(`${API_BASE}/switch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            provider,
            api_key: apiKey || undefined,
            model: model || undefined,
            api_endpoint: apiEndpoint || undefined,
            skip_test: true,
        }),
    });
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || '切换模型失败');
    }
    return response.json();
}

export async function getCurrentModel(): Promise<{
  provider: string;
  name?: string;
  icon?: string;
  color?: string;
  model?: string;
  api_key_configured?: boolean;
}> {
    const response = await fetch(`${API_BASE}/current`);
    if (!response.ok) {
        throw new Error('获取当前模型失败');
    }
    return response.json();
}

export interface SavedModel {
    id: string;
    provider: string;
    model: string;
    api_key: string;
    api_endpoint?: string;
    name?: string;
}

export async function getSavedModels(): Promise<{models: SavedModel[]}> {
    const response = await fetch(`${API_BASE}/saved-models`);
    if (!response.ok) throw new Error('获取已保存模型失败');
    return response.json();
}

export async function saveModelConfig(entry: {
    provider: string;
    model: string;
    api_key: string;
    api_endpoint?: string;
    name?: string;
}): Promise<{success: boolean; id: string; message: string}> {
    const response = await fetch(`${API_BASE}/saved-models`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(entry),
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '保存失败');
    }
    return response.json();
}

export async function deleteSavedModel(modelId: string): Promise<void> {
    const response = await fetch(`${API_BASE}/saved-models/${modelId}`, {
        method: 'DELETE',
    });
    if (!response.ok) throw new Error('删除失败');
}

export async function switchToSavedModel(modelId: string): Promise<{success: boolean; message: string}> {
    const response = await fetch(`${API_BASE}/saved-models/${modelId}/switch`, {
        method: 'POST',
    });
    return response.json();
}
