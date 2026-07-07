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
    api_key?: string;
    api_endpoint?: string;
    name?: string;
}

export interface ProviderModelEntry {
    id: string;
    name?: string;
    enabled?: boolean;
    supports_tools?: boolean | null;
    supports_vision?: boolean | null;
    supports_reasoning?: boolean | null;
    overrides?: Record<string, unknown>;
}

export interface CustomProviderProfile {
    id?: string;
    name: string;
    protocol: string;
    base_url: string;
    api_key?: string;
    api_key_masked?: string;
    has_api_key?: boolean;
    default_model?: string;
    enabled?: boolean;
    website?: string;
    notes?: string;
    icon?: string;
    color?: string;
    request_config: Record<string, unknown>;
    models: ProviderModelEntry[];
    model_overrides?: Record<string, unknown>;
}

export interface ProviderProfileResult {
    success: boolean;
    provider: CustomProviderProfile;
    message: string;
}

export async function getSavedModels(): Promise<{models: SavedModel[]}> {
    const response = await fetch(`${API_BASE}/saved-models`);
    if (!response.ok) throw new Error('获取已保存模型失败');
    return response.json();
}

export async function saveModelConfig(entry: {
    provider: string;
    model: string;
    api_key?: string;
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

export async function getProviderProfiles(): Promise<{providers: CustomProviderProfile[]}> {
    const response = await fetch(`${API_BASE}/provider-profiles`);
    if (!response.ok) throw new Error('获取自定义供应商失败');
    return response.json();
}

export async function saveProviderProfile(profile: CustomProviderProfile): Promise<ProviderProfileResult> {
    const method = profile.id ? 'PUT' : 'POST';
    const path = profile.id ? `${API_BASE}/provider-profiles/${profile.id}` : `${API_BASE}/provider-profiles`;
    const response = await fetch(path, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profile),
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '保存供应商失败');
    }
    return response.json();
}

export async function deleteProviderProfile(providerId: string): Promise<{success: boolean; message: string}> {
    const response = await fetch(`${API_BASE}/provider-profiles/${providerId}`, { method: 'DELETE' });
    if (!response.ok) throw new Error('删除供应商失败');
    return response.json();
}

export async function fetchProviderModels(providerId: string, body: {
    api_key?: string;
    model?: string;
    base_url?: string;
    request_config?: Record<string, unknown>;
}): Promise<{success: boolean; models: string[]; message: string}> {
    const response = await fetch(`${API_BASE}/provider-profiles/${providerId}/models/fetch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return response.json();
}

export async function testProviderProfile(providerId: string, body: {
    api_key?: string;
    model?: string;
    base_url?: string;
    request_config?: Record<string, unknown>;
}): Promise<TestResult> {
    const response = await fetch(`${API_BASE}/provider-profiles/${providerId}/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return response.json();
}

export async function testProviderTools(providerId: string, body: {
    api_key?: string;
    model?: string;
    base_url?: string;
    request_config?: Record<string, unknown>;
}): Promise<{success: boolean; message: string; tool_call_mode?: string; tool_calls?: unknown[]}> {
    const response = await fetch(`${API_BASE}/provider-profiles/${providerId}/test-tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return response.json();
}
