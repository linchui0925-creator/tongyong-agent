import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Balatro from './Balatro';
import DecryptedText from './DecryptedText';
import OrbitImages from './OrbitImages';
import AIAssistant from './AIAssistant';
import CapabilityOrb, { type CapabilityKind } from './CapabilityOrb';
import ContactModal from './ContactModal';
import './HomePage.css';

interface Capability {
  key: string;
  title: string;
  blurb: string;
}

const capabilities: Capability[] = [
  {
    key: 'chat',
    title: '多模型对话',
    blurb: '通义 · OpenAI · DeepSeek · 智谱 · edgefn 聚合 — 一个入口切换所有模型',
  },
  {
    key: 'team',
    title: '多 Agent 协作',
    blurb: 'Leader 调度 Researcher · Coder · Reviewer — 角色分工、自动接力',
  },
  {
    key: 'memory',
    title: '长期记忆',
    blurb: '会话历史 · 共享向量记忆 · 显式 memory_search / memory_list 工具',
  },
  {
    key: 'skills',
    title: '技能市场',
    blurb: '19 个内置工具 · 工作区隔离 · 高风险命令审批门禁 · todo 规划',
  },
  {
    key: 'personality',
    title: '人格系统',
    blurb: '可注入人格 · 用户偏好 · 梦境/自省循环 · 评估仪表盘',
  },
  {
    key: 'tools',
    title: '工具与脚本',
    blurb: '读写文件 · terminal · 联网检索 · 图片生成 · MCP 协议接入',
  },
];

const orbitKinds: CapabilityKind[] = [
  'chat',
  'code',
  'image',
  'search',
  'memory',
  'language',
  'music',
  'spark',
];

export default function HomePage() {
  const navigate = useNavigate();
  const [contactOpen, setContactOpen] = useState(false);

  const openApp = () => navigate('/app');
  const openContact = () => setContactOpen(true);
  const closeContact = () => setContactOpen(false);

  const scrollToCapabilities = () => {
    document.getElementById('home-capabilities')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const orbitItems = orbitKinds.map(k => <CapabilityOrb key={k} kind={k} />);

  return (
    <div className="home-page">
      <div className="home-bg">
        <Balatro
          color1="#FF7A1A"
          color2="#E63946"
          color3="#0B0908"
          contrast={3.2}
          lighting={0.45}
          spinAmount={0.22}
          spinSpeed={5.5}
          pixelFilter={760}
          mouseInteraction={true}
          isRotate={false}
        />
        <div className="home-bg-fade" aria-hidden="true" />
      </div>

      <header className="home-nav">
        <a className="home-brand" href="/" onClick={(e) => { e.preventDefault(); window.scrollTo({ top: 0, behavior: 'smooth' }); }}>
          <span className="home-brand-mark">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5z"/>
              <path d="M2 17l10 5 10-5"/>
              <path d="M2 12l10 5 10-5"/>
            </svg>
          </span>
          <span className="home-brand-text">TongYong</span>
        </a>

        <nav className="home-nav-links">
          <a href="#home-capabilities" onClick={(e) => { e.preventDefault(); scrollToCapabilities(); }}>能力</a>
          <button type="button" className="home-nav-contact" onClick={openContact}>联系我们</button>
        </nav>

        <button type="button" className="home-nav-cta" onClick={openApp}>
          <span>进入对话</span>
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="5" y1="12" x2="19" y2="12"/>
            <polyline points="12 5 19 12 12 19"/>
          </svg>
        </button>
      </header>

      <main className="home-main">
        <section className="home-hero">
          <div className="home-hero-text">
            <div className="home-hero-eyebrow">TongYong Agent · 通用 AI 工作台</div>
            <h1 className="home-hero-title">TongYong</h1>
            <p className="home-hero-lead dx-text">
              <DecryptedText
                text="多模型 · 多 Agent · 可记忆的通用 AI 助手"
                animateOn="view"
                sequential
                revealDirection="start"
                speed={42}
                maxIterations={12}
                className="dx-revealed"
                encryptedClassName="dx-encrypted"
              />
            </p>
            <p className="home-hero-sub">
              把对话、研究、写作、代码、规划放进同一个工作流。模型随任务切换，Agent 分工协作，会话之间留下可检索的记忆。
            </p>

            <div className="home-hero-ctas">
              <button type="button" className="home-cta-primary" onClick={openApp}>
                <span>开始对话</span>
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="5" y1="12" x2="19" y2="12"/>
                  <polyline points="12 5 19 12 12 19"/>
                </svg>
              </button>
              <button type="button" className="home-cta-secondary" onClick={scrollToCapabilities}>
                <span>查看能力</span>
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
              </button>
            </div>

            <div className="home-hero-stats" role="list">
              <div className="home-hero-stat" role="listitem">
                <span className="home-hero-stat-num">5+</span>
                <span className="home-hero-stat-label">LLM 提供商</span>
              </div>
              <span className="home-hero-stat-divider" aria-hidden="true" />
              <div className="home-hero-stat" role="listitem">
                <span className="home-hero-stat-num">19</span>
                <span className="home-hero-stat-label">内置工具</span>
              </div>
              <span className="home-hero-stat-divider" aria-hidden="true" />
              <div className="home-hero-stat" role="listitem">
                <span className="home-hero-stat-num">4</span>
                <span className="home-hero-stat-label">主题皮肤</span>
              </div>
            </div>
          </div>

          <div className="ai-showcase" aria-label="TongYong AI 助手示意图">
            <div className="ai-showcase-corner">
              <span className="dot" aria-hidden="true" />
              <span>在线</span>
            </div>
            <div className="ai-showcase-orbiter">
              <OrbitImages
                customItems={orbitItems}
                shape="ellipse"
                radiusX={300}
                radiusY={120}
                rotation={-8}
                duration={36}
                itemSize={56}
                responsive={true}
                baseWidth={720}
              />
            </div>
            <div className="ai-showcase-center">
              <AIAssistant size={300} />
            </div>
          </div>
        </section>

        <section id="home-capabilities" className="home-capabilities">
          <header className="home-capabilities-head">
            <h2>一站式的 AI 工作流</h2>
            <p>不是又一个聊天框 — 是把模型、Agent、记忆、工具组合在一起的工作台。</p>
          </header>

          <div className="home-capabilities-grid">
            {capabilities.map((cap) => (
              <article key={cap.key} className="home-capability">
                <h3 className="home-capability-title">{cap.title}</h3>
                <p className="home-capability-blurb">{cap.blurb}</p>
              </article>
            ))}
          </div>

          <div className="home-capabilities-foot">
            <button type="button" className="home-cta-primary home-cta-primary-lg" onClick={openApp}>
              <span>打开工作台</span>
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="5" y1="12" x2="19" y2="12"/>
                <polyline points="12 5 19 12 12 19"/>
              </svg>
            </button>
          </div>
        </section>

        <section className="home-contact" aria-labelledby="home-contact-title">
          <div className="home-contact-inner">
            <span className="home-contact-eyebrow">
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                <polyline points="22,6 12,13 2,6" />
              </svg>
              联系我们
            </span>
            <h2 id="home-contact-title" className="home-contact-title">想把 TongYong 用到团队场景里？</h2>
            <p className="home-contact-sub">
              合作落地、技术支持、功能建议，都欢迎告诉我们 — 留下邮箱，1–2 个工作日内回信。
            </p>
            <div className="home-contact-actions">
              <button type="button" className="home-cta-primary home-cta-primary-lg" onClick={openContact}>
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                  <polyline points="22,6 12,13 2,6" />
                </svg>
                <span>填写表单</span>
              </button>
              <button type="button" className="home-cta-secondary" onClick={openApp}>
                <span>先试用一下</span>
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="5" y1="12" x2="19" y2="12"/>
                  <polyline points="12 5 19 12 12 19"/>
                </svg>
              </button>
            </div>
          </div>
        </section>

        <footer className="home-footer">
          <span>Built with FastAPI · React · ogl · motion</span>
          <span className="home-footer-dot" aria-hidden="true">·</span>
          <span>默认模型 edgefn/GLM-5.2</span>
        </footer>
      </main>

      <ContactModal open={contactOpen} onClose={closeContact} />
    </div>
  );
}
