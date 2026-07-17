import axios from 'axios';

const api = axios.create({ baseURL: '/api/mcp', timeout: 30000 });

export interface MCPPackage {
  registryType: string;
  identifier: string;
  version?: string;
  runtimeHint?: string;
  transport?: { type: string };
  runtimeArguments?: Array<{ value: string; type?: string }>;
  environmentVariables?: Array<{ name: string; description?: string; isRequired?: boolean; isSecret?: boolean }>;
}

export interface MCPMarketplaceServer {
  id: string;
  name: string;
  description: string;
  version: string;
  repository?: { url: string; source?: string; subfolder?: string };
  website_url?: string;
  packages: MCPPackage[];
  remotes: Array<{ type: string; url: string }>;
  updated_at?: string;
}

export interface MCPInstalledServer {
  id: string;
  connected: boolean;
  transport: string;
  command: string;
  tool_count: number;
  tools: string[];
}

export async function searchMCPMarketplace(search = '', limit = 24) {
  const response = await api.get('/marketplace', { params: { search, limit } });
  return response.data as { servers: MCPMarketplaceServer[]; next_cursor?: string; registry: string };
}

export async function listMCPServers() {
  const response = await api.get('/servers');
  return response.data as { servers: MCPInstalledServer[]; total: number };
}

export async function installMCPServer(config: { server_id: string; package?: MCPPackage; remote?: { type: string; url: string }; env: Record<string, string> }) {
  const response = await api.post('/servers/install', config);
  return response.data;
}

export async function deleteMCPServer(id: string) {
  const response = await api.delete(`/servers/${encodeURIComponent(id)}`);
  return response.data;
}

export async function restartMCPServer(id: string) {
  const response = await api.post(`/servers/${encodeURIComponent(id)}/restart`);
  return response.data;
}
