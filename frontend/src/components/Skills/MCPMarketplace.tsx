import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { installMCPServer, listMCPServers, restartMCPServer, searchMCPMarketplace, type MCPInstalledServer, type MCPMarketplaceServer } from '../../api/mcp';
import './MCPMarketplace.css';

const CATEGORY_HINTS: Record<string, string> = {
  git: '代码仓库、提交、分支、变更管理',
  file: '文件系统、目录浏览、读写文件',
  browser: '浏览器自动化、网页交互、截图',
  docs: '文档读取、知识检索、站点内容提取',
  memory: '长期记忆、知识图谱、上下文保存',
};

function getCategory(server: MCPMarketplaceServer) {
  const text = `${server.id} ${server.name} ${server.description}`.toLowerCase();
  if (text.includes('git')) return 'git';
  if (text.includes('file') || text.includes('filesystem')) return 'file';
  if (text.includes('browser') || text.includes('playwright')) return 'browser';
  if (text.includes('doc') || text.includes('wiki') || text.includes('fetch')) return 'docs';
  if (text.includes('memory')) return 'memory';
  return 'other';
}

function prettyName(server: MCPMarketplaceServer) {
  return server.name || server.id.replace(/[\/_-]+/g, ' ').replace(/\b\w/g, s => s.toUpperCase());
}

function summarize(server: MCPMarketplaceServer) {
  return server.description?.trim() || '这个 MCP server 的官方描述暂时较少，但可以作为 agent 的扩展能力接入。';
}

function normalizeInstallError(err: any) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') return detail.message || JSON.stringify(detail);
  return err?.message || '安装失败';
}

export const MCPMarketplace: React.FC = () => {
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<MCPMarketplaceServer[]>([]);
  const [installed, setInstalled] = useState<MCPInstalledServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [installingId, setInstallingId] = useState('');
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<MCPMarketplaceServer | null>(null);

  const install = async (server: MCPMarketplaceServer) => {
    const pkg = server.packages?.[0];
    if (!pkg) return setError('该条目没有可安装的包');
    const command = pkg.registryType === 'npm' ? 'npx' : pkg.registryType === 'pypi' ? 'uvx' : '';
    if (!command) return setError(`暂不支持自动安装 ${pkg.registryType} 包`);
    const env: Record<string, string> = {};
    for (const item of pkg.environmentVariables || []) {
      const value = window.prompt(`${item.name}${item.description ? `：${item.description}` : ''}`, '');
      if (item.isRequired && !value) return setError(`缺少必填配置 ${item.name}`);
      if (value) env[item.name] = value;
    }
    const args = command === 'npx' ? ['-y', pkg.identifier] : [pkg.identifier];
    setInstallingId(server.id);
    setError('');
    try {
      const result = await installMCPServer({ server_id: server.id, command, args, env });
      if (result?.success === false) {
        setError(result?.server?.command ? `安装已保存，但启动失败：${result.server.command}` : result?.detail || '安装失败');
        return;
      }
      await load();
      setSelected(server);
    } catch (e: any) {
      setError(normalizeInstallError(e));
    } finally {
      setInstallingId('');
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const localPromise = listMCPServers().catch(() => ({ servers: [], total: 0 }));
      const marketPromise = searchMCPMarketplace(query).catch(() => ({ servers: [], registry: '', cached: true }));
      const local = await localPromise;
      setInstalled(local.servers);
      const market = await marketPromise;
      setItems(market.servers);
      if (!market.servers.length) {
        setError(query ? '未找到匹配的 MCP Server，已显示本地缓存（如有）' : '官方 MCP Registry 暂时不可用，已显示本地缓存（如有）');
      }
    } catch (e: any) {
      setError(normalizeInstallError(e));
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    const timer = window.setTimeout(load, query ? 300 : 0);
    return () => window.clearTimeout(timer);
  }, [load, query]);

  const recommended = useMemo(() => items.slice(0, 6), [items]);
  const filteredInstalled = useMemo(() => installed.filter(Boolean), [installed]);

  return <div className="mcp-market-page">
    <div className="mcp-market-hero">
      <div>
        <div className="mcp-market-kicker">MCP 能力市场</div>
        <h2>为你的 agent 选择可用能力</h2>
        <p>安装后，agent 就能直接访问文件、仓库、浏览器、文档等外部工具。我们优先展示稳定、可理解、可启用的能力，而不是一堆看不懂的包名。</p>
      </div>
      <div className="mcp-market-searchbox">
        <input className="input" placeholder="搜索能力名称，例如 git / browser / file..." value={query} onChange={e => setQuery(e.target.value)} />
        <button className="btn btn-ghost" onClick={load}>刷新</button>
      </div>
    </div>

    {filteredInstalled.length > 0 && <section className="mcp-section">
      <div className="mcp-section-title">已启用的能力</div>
      <div className="mcp-installed-grid">
        {filteredInstalled.map(server => (
          <div key={server.id} className="mcp-installed-card">
            <div>
              <strong>{server.id}</strong>
              <div className="mcp-muted">{server.connected ? '已连接' : '未连接'} · {server.tool_count} 个工具</div>
            </div>
            <button className="btn btn-ghost" onClick={() => restartMCPServer(server.id).then(load)}>重启</button>
          </div>
        ))}
      </div>
    </section>}

    {error && <div className="error-state">{error}</div>}

    <div className="mcp-market-layout">
      <div className="mcp-market-main">
        <section className="mcp-section">
          <div className="mcp-section-title">推荐能力</div>
          <div className="mcp-recommendation-strip">
            <div className="mcp-tip-card">Git：提交、分支、查看变更、仓库自动化</div>
            <div className="mcp-tip-card">File：读写文件、目录浏览、工作区产物管理</div>
            <div className="mcp-tip-card">Browser：打开网页、点击、输入、截图</div>
          </div>
        </section>

        <section className="mcp-section">
          <div className="mcp-section-title">可安装能力</div>
          {loading && items.length === 0 ? <div className="empty-state">正在加载能力市场…</div> : <div className="mcp-grid">
            {items.map(server => {
              const pkg = server.packages?.[0];
              const remote = server.remotes?.[0];
              const env = pkg?.environmentVariables || [];
              const category = getCategory(server);
              const isSelected = selected?.id === server.id;
              return <button key={server.id} className={`mcp-card ${isSelected ? 'is-selected' : ''}`} onClick={() => setSelected(server)}>
                <div className="mcp-card-topline">
                  <span className="mcp-pill">{category}</span>
                  {pkg && <span className="mcp-pill mcp-pill-soft">{pkg.registryType}</span>}
                </div>
                <div className="mcp-card-title">{prettyName(server)}</div>
                <div className="mcp-card-subtitle">{server.id} · v{server.version}</div>
                <div className="mcp-card-description">{summarize(server)}</div>
                <div className="mcp-card-footer">
                  <span className="mcp-muted">{env.length > 0 ? `${env.length} 个配置项` : '无需额外配置'}</span>
                  <span className="mcp-muted">{remote?.type || 'unknown'}</span>
                </div>
                <div className="mcp-card-actions">
                  {(server.website_url || server.repository?.url) && <a className="btn btn-ghost" href={server.website_url || server.repository?.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}>查看详情</a>}
                  <button className="btn btn-primary" disabled={!pkg || installingId === server.id} onClick={e => { e.stopPropagation(); install(server); }}>
                    {installingId === server.id ? '安装中…' : '安装并启用'}
                  </button>
                </div>
              </button>;
            })}
          </div>}
        </section>
      </div>

      <aside className="mcp-inspector">
        <div className="mcp-section-title">能力详情</div>
        {selected ? <div className="mcp-inspector-panel">
          <div className="mcp-inspector-name">{prettyName(selected)}</div>
          <div className="mcp-muted">{selected.id} · v{selected.version}</div>
          <p className="mcp-inspector-description">{summarize(selected)}</p>
          <div className="mcp-inspector-block">
            <div className="mcp-inspector-label">这是什么</div>
            <div>{CATEGORY_HINTS[getCategory(selected)] || '通用 MCP 能力，可扩展 agent 的外部工具访问范围。'}</div>
          </div>
          <div className="mcp-inspector-block">
            <div className="mcp-inspector-label">安装前需要</div>
            <div>{selected.packages?.[0]?.environmentVariables?.length ? '可能需要配置环境变量或 token。' : '通常可以直接安装。'}</div>
          </div>
          <div className="mcp-inspector-block">
            <div className="mcp-inspector-label">工具数量</div>
            <div>{selected.packages?.[0] ? '安装后会自动启动并加载工具。' : '该条目暂无可安装包。'}</div>
          </div>
          <div className="mcp-inspector-actions">
            <button className="btn btn-primary" disabled={installingId === selected.id || !selected.packages?.[0]} onClick={() => install(selected)}>{installingId === selected.id ? '安装中…' : '安装并启用'}</button>
            {(selected.website_url || selected.repository?.url) && <a className="btn btn-ghost" href={selected.website_url || selected.repository?.url} target="_blank" rel="noreferrer">查看来源</a>}
          </div>
        </div> : <div className="empty-state">选择一个能力查看详情、要求和安装方式。</div>}
      </aside>
    </div>

    {recommended.length > 0 && <section className="mcp-section">
      <div className="mcp-section-title">热门条目</div>
      <div className="mcp-mini-list">
        {recommended.map(server => (
          <div key={server.id} className="mcp-mini-item">
            <div>
              <strong>{prettyName(server)}</strong>
              <div className="mcp-muted">{summarize(server)}</div>
            </div>
            <button className="btn btn-ghost" onClick={() => setSelected(server)}>查看</button>
          </div>
        ))}
      </div>
    </section>}
  </div>;
};
