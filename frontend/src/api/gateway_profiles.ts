const API_BASE = '/api/gateway';

export interface Profile {
    id: string;
    name: string;
    provider: string;
    model?: string;
    api_key?: string;
    api_endpoint?: string;
    temperature?: number;
    max_tokens?: number;
    top_p?: number;
    max_tool_rounds: number;
    gateway_port?: number;  // 独立网关端口，0表示未启动
    is_default: boolean;
    is_active?: boolean;
    created_at?: string;
    updated_at?: string;
}

export interface ProfileCreate {
    name: string;
    provider: string;
    model?: string;
    api_key?: string;
    api_endpoint?: string;
    temperature?: number;
    max_tokens?: number;
    top_p?: number;
    max_tool_rounds?: number;
    is_default?: boolean;
}

export interface ProfileUpdate {
    name?: string;
    provider?: string;
    model?: string;
    api_key?: string;
    api_endpoint?: string;
    temperature?: number;
    max_tokens?: number;
    top_p?: number;
    max_tool_rounds?: number;
    is_default?: boolean;
}

export interface ListProfilesResult {
    profiles: Profile[];
    active_profile_id: string | null;
}

export async function getProfiles(): Promise<ListProfilesResult> {
    const response = await fetch(`${API_BASE}/profiles`);
    if (!response.ok) throw new Error('获取Profile列表失败');
    return response.json();
}

export async function getProfile(profileId: string): Promise<{profile: Profile}> {
    const response = await fetch(`${API_BASE}/profiles/${profileId}`);
    if (!response.ok) throw new Error('获取Profile失败');
    return response.json();
}

export async function createProfile(profile: ProfileCreate): Promise<{success: boolean; profile: Profile}> {
    const response = await fetch(`${API_BASE}/profiles`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profile),
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '创建Profile失败');
    }
    return response.json();
}

export async function updateProfile(profileId: string, updates: ProfileUpdate): Promise<{success: boolean; profile: Profile}> {
    const response = await fetch(`${API_BASE}/profiles/${profileId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '更新Profile失败');
    }
    return response.json();
}

export async function deleteProfile(profileId: string): Promise<{success: boolean; message: string}> {
    const response = await fetch(`${API_BASE}/profiles/${profileId}`, {
        method: 'DELETE',
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '删除Profile失败');
    }
    return response.json();
}

export async function activateProfile(profileId: string): Promise<{success: boolean; active_profile_id: string}> {
    const response = await fetch(`${API_BASE}/profiles/${profileId}/activate`, {
        method: 'POST',
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '激活Profile失败');
    }
    return response.json();
}

export async function getActiveProfile(): Promise<{profile: Profile | null; message?: string}> {
    const response = await fetch(`${API_BASE}/profiles/active`);
    if (!response.ok) throw new Error('获取激活Profile失败');
    return response.json();
}

export async function testProfile(profileId: string): Promise<{success: boolean; message: string; model?: string}> {
    const response = await fetch(`${API_BASE}/profiles/${profileId}/test`, {
        method: 'POST',
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || '测试Profile失败');
    }
    return response.json();
}

// ── Gateway Management ───────────────────────────────────

export interface Gateway {
    profile_id: string;
    port: number;
    is_running: boolean;
    url: string;
}

export async function getGateways(): Promise<{gateways: Gateway[]}> {
    const response = await fetch(`${API_BASE}/gateways`);
    if (!response.ok) throw new Error('获取网关列表失败');
    return response.json();
}

export async function getGatewayStatus(profileId: string): Promise<Gateway> {
    const response = await fetch(`${API_BASE}/gateways/${profileId}`);
    if (!response.ok) throw new Error('获取网关状态失败');
    return response.json();
}

export async function startGateway(profileId: string): Promise<{success: boolean; profile_id: string; port: number; pid: number; url: string}> {
    const response = await fetch(`${API_BASE}/gateways/${profileId}/start`, {
        method: 'POST',
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.error || '启动网关失败');
    }
    return response.json();
}

export async function stopGateway(profileId: string): Promise<{success: boolean; profile_id: string; port: number}> {
    const response = await fetch(`${API_BASE}/gateways/${profileId}/stop`, {
        method: 'POST',
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.error || '停止网关失败');
    }
    return response.json();
}

export async function restartGateway(profileId: string): Promise<{success: boolean; profile_id: string; port: number; url: string}> {
    const response = await fetch(`${API_BASE}/gateways/${profileId}/restart`, {
        method: 'POST',
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.error || '重启网关失败');
    }
    return response.json();
}

export async function getProfileModels(profileId: string): Promise<{provider: string; models: Array<{id: string; name: string; context_window: number; max_output: number; capabilities: string}>}> {
    const response = await fetch(`${API_BASE}/profiles/${profileId}/models`);
    if (!response.ok) throw new Error('获取模型列表失败');
    return response.json();
}