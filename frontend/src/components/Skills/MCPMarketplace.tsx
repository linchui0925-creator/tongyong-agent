import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { installMCPServer, listMCPServers, restartMCPServer, searchMCPMarketplace, type MCPInstalledServer, type MCPMarketplaceServer } from '../../api/mcp';
import './MCPMarketplace.css';

const MCP_CN_NOTES: Record<string, { name?: string; desc?: string }> = {
  'filesystem': {
    name: '本地文件系统',
    desc: '直接读写工作目录内的文件, 支持查看、创建、编辑、删除。agent 读代码、写脚本、保存产物的核心能力。',
  },
  'puppeteer': {
    name: '浏览器自动化',
    desc: '通过 Puppeteer 控制无头 Chrome, 可以打开网页、截图、抓取内容、填写表单、执行 JS。',
  },
  'brave-search': {
    name: 'Brave 网页搜索',
    desc: '匿名网页搜索, 不需要 API key 就能查实时信息。',
  },
  'sequential-thinking': {
    name: '结构化多步推理',
    desc: '把复杂任务拆解成连贯的推理链, 每一步都能回顾前面步骤再决定下一步, 适合复杂代码/架构任务。',
  },
  'memory': {
    name: '会话长期记忆',
    desc: '跨会话持久化存储关键事实、偏好、规则, 下次对话 agent 能记住之前约定的做事方式。',
  },
  'git': {
    name: 'Git 版本控制',
    desc: '在本地仓库执行 git 命令: status / add / commit / branch / checkout / log。不需要 API 接入。',
  },
  'github': {
    name: 'GitHub 平台',
    desc: '通过 GitHub API 操作 PR、issue、comment、label、milestone, 需要 GITHUB_TOKEN。',
  },
  'postgres': {
    name: 'PostgreSQL 查询',
    desc: '连接 Postgres 数据库执行 SQL 查询、查看表结构、分析数据。',
  },
  'sqlite': {
    name: 'SQLite 本地库',
    desc: '读写本地 SQLite 数据库文件, 轻量无需启动服务进程。',
  },
  'gmail': {
    name: 'Gmail 邮件',
    desc: '读取收件箱、搜索邮件、发送新邮件, 需要 OAuth 授权。',
  },
  'google-calendar': {
    name: 'Google Calendar',
    desc: '查看日程、创建会议、提醒、查看忙闲状态。',
  },
  'markdown-preview': {
    name: 'Markdown 实时预览',
    desc: '把 markdown 渲染成网页并截图, 写文档时可直观看到最终效果。',
  },
  'never-have-i-ever': {
    name: '变更影响探测',
    desc: '自动记录哪些文件被哪些命令修改过, 帮助回溯 "我刚才到底改了什么"。',
  },
  'exit-intent': {
    name: '终止意图检测',
    desc: '检测 agent 是否真的完成了任务还是卡在等待状态, 配合超时保护避免无限循环。',
  },
  'fetch': {
    name: 'HTTP 网页抓取',
    desc: '直接发起 GET/POST 请求读取网页或 API 返回内容, 不需要浏览器。',
  },
  'slack': {
    name: 'Slack 消息',
    desc: '发送、回复、搜索 Slack 消息, 需要 Bot token。',
  },
  'aws-s3': {
    name: 'AWS S3 对象存储',
    desc: '列出、读取、写入 S3 bucket 里的文件对象, 需要 AWS 凭据。',
  },
};

function withCnNotes(server: MCPMarketplaceServer): MCPMarketplaceServer {
  const key = server.id.replace(/^.+?\//, '');
  const haystack = `${server.id} ${server.name} ${server.description}`.toLowerCase();
  const genericDesc = /file|filesystem|storage/.test(haystack)
    ? '提供文件或对象存储访问能力, 可用于读取、写入、整理和同步数据。'
    : /git|github|gitlab|code|repo/.test(haystack)
      ? '提供代码仓库和开发协作能力, 可用于读取代码、管理版本或处理研发流程。'
      : /browser|web|fetch|http|scrap|crawl/.test(haystack)
        ? '提供网页访问和浏览器自动化能力, 可用于打开页面、抓取内容或调用网络接口。'
        : /database|postgres|mysql|sqlite|mongo|redis|sql/.test(haystack)
          ? '提供数据库访问能力, 可用于查看结构、查询和分析业务数据。'
          : /search|knowledge|docs|wiki/.test(haystack)
            ? '提供搜索或知识库访问能力, 可用于检索文档、资料和实时信息。'
            : /memory|graph/.test(haystack)
              ? '提供持久化记忆或知识图谱能力, 帮助 agent 在任务之间保存和检索上下文。'
              : '这是一个 MCP 扩展服务, 用于把外部工具或数据源接入 agent。安装前请查看官方说明和所需凭据。';
  const notes = MCP_CN_NOTES[server.id] ?? MCP_CN_NOTES[key] ?? { desc: genericDesc };
  const cn = `【中文说明】${notes.desc ?? ''}`;
  return {
    ...server,
    name: notes.name || server.name,
    description: server.description
      ? `${server.description.trim()}\n\n${cn}`
      : cn,
    _cn_name: notes.name,
    _cn_desc: notes.desc,
  } as MCPMarketplaceServer & { _cn_name?: string; _cn_desc?: string };
}

// ── 分类 ──────────────────────────────────────
// 后端 registry 没有显式 category, 我们按 id/name/description 启发式打标,
// 用户也能看到这一段,所以标签文字要克制, 不要堆叠。
const CATEGORIES: Array<{ key: string; label: string; match: (s: MCPMarketplaceServer) => boolean }> = [
  { key: 'all',      label: '全部',  match: () => true },
  { key: 'git',      label: '代码仓库', match: s => /\bgit\b/i.test(`${s.id} ${s.name} ${s.description}`) },
  { key: 'file',     label: '文件系统', match: s => /file|filesystem|fs\b/i.test(`${s.id} ${s.name} ${s.description}`) },
  { key: 'browser',  label: '浏览器',   match: s => /browser|playwright|puppeteer|fetch/i.test(`${s.id} ${s.name} ${s.description}`) },
  { key: 'docs',     label: '文档知识', match: s => /\bdoc(s)?\b|\bwiki\b|\bknowledge\b|search/i.test(`${s.id} ${s.name} ${s.description}`) },
  { key: 'memory',   label: '记忆',     match: s => /memory|knowledge\s*graph/i.test(`${s.id} ${s.name} ${s.description}`) },
  { key: 'other',    label: '其他',     match: () => true },
];

function classify(server: MCPMarketplaceServer): string {
  for (const c of CATEGORIES) {
    if (c.key === 'all' || c.key === 'other') continue;
    if (c.match(server)) return c.key;
  }
  return 'other';
}

function prettyName(server: MCPMarketplaceServer) {
  return server.name || server.id.replace(/[\/_-]+/g, ' ').replace(/\b\w/g, s => s.toUpperCase());
}

function summarize(server: MCPMarketplaceServer) {
  const s = server as MCPMarketplaceServer & { _cn_name?: string; _cn_desc?: string };
  const official = server.description?.replace(/\n*【中文说明】.*$/, '').trim() || '';
  if (s._cn_desc) {
    return official
      ? `${s._cn_desc}\n\n官方原文: ${official}`
      : s._cn_desc;
  }
  return official || '官方描述暂时较少, 但作为 agent 的扩展能力接入仍然有效。';
}

function normalizeInstallError(err: any) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') return detail.message || JSON.stringify(detail);
  return err?.message || '安装失败';
}

// ── Inline SVG icons (瘦线条, 跟主题字风一致) ──
const SearchIcon = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
       strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="11" cy="11" r="7" />
    <path d="m21 21-4.3-4.3" />
  </svg>
);

const SparkIcon = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
       strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
  </svg>
);

const RefreshIcon = ({ spinning }: { spinning?: boolean }) => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
       strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"
       style={spinning ? { animation: 'mcp-spin 0.9s linear infinite' } : undefined}
       aria-hidden="true">
    <path d="M21 12a9 9 0 0 0-15.6-6.2L3 8" />
    <path d="M3 12a9 9 0 0 0 15.6 6.2L21 16" />
    <path d="M3 3v5h5" />
    <path d="M21 21v-5h-5" />
  </svg>
);

const Dot = ({ ok }: { ok: boolean }) => (
  <span
    aria-hidden
    style={{
      display: 'inline-block',
      width: 6,
      height: 6,
      borderRadius: '50%',
      background: ok ? 'var(--accent)' : 'var(--text-muted)',
      boxShadow: ok ? '0 0 8px var(--accent-subtle)' : 'none',
    }}
  />
);

// ── 主组件 ─────────────────────────────────────

export const MCPMarketplace: React.FC = () => {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<string>('all');
  const [items, setItems] = useState<MCPMarketplaceServer[]>([]);
  const [installed, setInstalled] = useState<MCPInstalledServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [installingId, setInstallingId] = useState('');
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<MCPMarketplaceServer | null>(null);

  const install = async (server: MCPMarketplaceServer) => {
    const pkg = server.packages?.[0];
    const remote = server.remotes?.[0];
    if (!pkg && !remote) return setError('该条目没有可安装包或远程连接地址');
    const env: Record<string, string> = {};
    for (const item of pkg?.environmentVariables || []) {
      const value = window.prompt(`${item.name}${item.description ? ` · ${item.description}` : ''}`, '');
      if (item.isRequired && !value) return setError(`缺少必填配置 ${item.name}`);
      if (value) env[item.name] = value;
    }
    setInstallingId(server.id);
    setError('');
    try {
      const result = await installMCPServer({ server_id: server.id, package: pkg, remote: pkg ? undefined : remote, env });
      if (result?.success === false) {
        setError(result?.server?.command ? `安装已保存, 但启动失败: ${result.server.command}` : result?.detail || '安装失败');
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
      const marketPromise = searchMCPMarketplace('').catch(() => ({ servers: [], registry: '', cached: true }));
      const local = await localPromise;
      setInstalled(local.servers);
      const market = await marketPromise;
      setItems(market.servers.map(withCnNotes));
      if (!market.servers.length) {
        setError(query ? '未找到匹配的 MCP Server, 已显示本地缓存(如有)' : '官方 MCP Registry 暂时不可用, 已显示本地缓存(如有)');
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

  const visibleItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    let result = items;
    if (q) {
      result = result.filter(s =>
        `${s.id} ${s.name} ${s.description}`.toLowerCase().includes(q)
      );
    }
    if (category !== 'all') {
      result = result.filter(s => classify(s) === category);
    }
    return result;
  }, [items, category, query]);

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const c of CATEGORIES) counts[c.key] = 0;
    for (const s of items) counts[classify(s)] = (counts[classify(s)] ?? 0) + 1;
    counts.all = items.length;
    return counts;
  }, [items]);

  const filteredInstalled = useMemo(() => installed.filter(Boolean), [installed]);

  return (
    <div className="mcp-market-page">
      {/* ─── Hero: kicker + 大标题 + 描述 + 巨型搜索框 ─── */}
      <section className="mcp-hero">
        <div className="mcp-hero-head">
          <div className="mcp-kicker">
            <SparkIcon />
            <span>MCP 能力市场</span>
          </div>
          <h1 className="mcp-hero-title">为 agent 选择可用能力</h1>
          <p className="mcp-hero-lead">
            装好之后, agent 就能直接访问文件、仓库、浏览器、知识库等外部工具。
            我们优先展示稳定、可理解、可启用的能力, 而不是堆一堆看不懂的包名。
          </p>
        </div>

        <div className={`mcp-hero-search ${query ? 'has-value' : ''}`}>
          <span className="mcp-hero-search-icon"><SearchIcon /></span>
          <input
            className="mcp-hero-search-input"
            placeholder="搜索能力名称、关键词, 例如 git · browser · knowledge..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
          {query
            ? <button
                className="mcp-hero-search-clear"
                onClick={() => setQuery('')}
                aria-label="清空搜索"
                title="清空"
              >×</button>
            : <kbd className="mcp-hero-search-kbd" aria-hidden>⌘ K</kbd>
          }
        </div>

        <div className="mcp-hero-pills" role="tablist" aria-label="能力分类">
          {CATEGORIES.map(c => (
            <button
              key={c.key}
              role="tab"
              aria-selected={category === c.key}
              className={`mcp-pill ${category === c.key ? 'is-active' : ''}`}
              onClick={() => setCategory(c.key)}
            >
              <span>{c.label}</span>
              <span className="mcp-pill-count">{categoryCounts[c.key] ?? 0}</span>
            </button>
          ))}
          <button
            className="mcp-pill mcp-pill-refresh"
            onClick={load}
            disabled={loading}
            title="刷新"
          >
            <RefreshIcon spinning={loading} />
            <span>刷新</span>
          </button>
        </div>
      </section>

      {/* ─── 已启用 ─── */}
      {filteredInstalled.length > 0 && (
        <section className="mcp-section">
          <header className="mcp-section-head">
            <span className="mcp-section-title">已启用</span>
            <span className="mcp-section-meta">
              {filteredInstalled.length} 个能力 · <Dot ok /> 表示已连接
            </span>
          </header>
          <div className="mcp-installed-row">
            {filteredInstalled.map(server => (
              <article key={server.id} className="mcp-installed-card">
                <div className="mcp-installed-meta">
                  <Dot ok={server.connected} />
                  <strong>{server.id}</strong>
                  <span className="mcp-muted">{server.tool_count} 个工具</span>
                </div>
                <button
                  className="mcp-btn mcp-btn-ghost"
                  onClick={() => restartMCPServer(server.id).then(load)}
                >
                  重启
                </button>
              </article>
            ))}
          </div>
        </section>
      )}

      {error && <div className="mcp-error">{error}</div>}

      {/* ─── 主体: 卡片网格 + 详情 ─── */}
      <section className="mcp-section mcp-section-grow">
        <header className="mcp-section-head">
          <span className="mcp-section-title">可安装能力</span>
          <span className="mcp-section-meta">
            {loading ? '加载中…' : `${visibleItems.length} / ${items.length} 条`}
          </span>
        </header>

        <div className="mcp-market-layout">
          <div className="mcp-market-main">
            {loading && items.length === 0 ? (
              <div className="mcp-empty">正在加载能力市场…</div>
            ) : visibleItems.length === 0 ? (
              <div className="mcp-empty">
                <span>没有匹配的能力</span>
                <button className="mcp-btn mcp-btn-ghost" onClick={() => { setQuery(''); setCategory('all'); }}>
                  清空筛选
                </button>
              </div>
            ) : (
              <div className="mcp-grid">
                {visibleItems.map(server => {
                  const pkg = server.packages?.[0];
                  const remote = server.remotes?.[0];
                  const env = pkg?.environmentVariables || [];
                  const cat = classify(server);
                  const isSelected = selected?.id === server.id;
                  return (
                    <button
                      key={server.id}
                      className={`mcp-card ${isSelected ? 'is-selected' : ''}`}
                      onClick={() => setSelected(server)}
                    >
                      <div className="mcp-card-head">
                        <span className="mcp-card-cat">{cat}</span>
                        <span className="mcp-card-id">{server.id}</span>
                      </div>
                      <div className="mcp-card-title">{prettyName(server)}</div>
                      <div className="mcp-card-desc">{summarize(server)}</div>
                      <div className="mcp-card-foot">
                        <span className="mcp-muted">
                          {pkg ? `${pkg.registryType} · ${env.length > 0 ? `${env.length} 配置项` : '免配置'}` : remote ? `${remote.type || 'remote'} · 远程连接` : '不可安装'}
                        </span>
                        <span
                          className={`mcp-btn mcp-btn-primary mcp-btn-sm ${((!pkg && !remote) || installingId === server.id) ? 'is-disabled' : ''}`}
                          onClick={e => { e.stopPropagation(); if (pkg || remote) install(server); }}
                        >
                          {installingId === server.id ? '安装中' : '安装'}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <aside className="mcp-inspector">
            {selected ? (
              <div className="mcp-inspector-panel">
                <div className="mcp-inspector-head">
                  <span className="mcp-card-cat">{classify(selected)}</span>
                  <span className="mcp-card-id">{selected.id} · v{selected.version}</span>
                </div>
                <div className="mcp-inspector-title">{prettyName(selected)}</div>
                <p className="mcp-inspector-desc">{summarize(selected)}</p>

                <div className="mcp-inspector-block">
                  <div className="mcp-inspector-label">来源</div>
                  <div className="mcp-inspector-row">
                    {selected.website_url && (
                      <a href={selected.website_url} target="_blank" rel="noreferrer" className="mcp-link">官网 ↗</a>
                    )}
                    {selected.repository?.url && (
                      <a href={selected.repository.url} target="_blank" rel="noreferrer" className="mcp-link">仓库 ↗</a>
                    )}
                    <span className="mcp-muted">{selected.remotes?.[0]?.type ?? 'stdio'}</span>
                  </div>
                </div>

                <div className="mcp-inspector-block">
                  <div className="mcp-inspector-label">安装前</div>
                  <div className="mcp-inspector-row">
                    <span className="mcp-muted">
                      {selected.packages?.[0]?.environmentVariables?.length
                        ? `${selected.packages[0].environmentVariables.length} 个环境变量可能需要配置`
                        : '通常可直接安装, 无额外配置'}
                    </span>
                  </div>
                </div>

                <div className="mcp-inspector-actions">
                  <button
                    className={`mcp-btn mcp-btn-primary ${(installingId === selected.id || (!selected.packages?.[0] && !selected.remotes?.[0])) ? 'is-disabled' : ''}`}
                    disabled={installingId === selected.id || (!selected.packages?.[0] && !selected.remotes?.[0])}
                    onClick={() => install(selected)}
                  >
                    {installingId === selected.id ? '安装中…' : '安装并启用'}
                  </button>
                </div>
              </div>
            ) : (
              <div className="mcp-inspector-empty">
                <div className="mcp-inspector-eyebrow">能力详情</div>
                <p>从左侧选一个能力, 这里会显示安装方式、来源、配置要求。</p>
              </div>
            )}
          </aside>
        </div>
      </section>
    </div>
  );
};
