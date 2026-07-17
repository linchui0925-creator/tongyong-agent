/**
 * TongYong Agent — Main Application
 */
import { useState, useEffect, useCallback } from 'react'
import { useTheme } from './theme/ThemeContext'
import { themes } from './theme/themes'
import ModernChatPanel from './components/Chat/ModernChatPanel'
import SessionSidebar from './components/Session/SessionSidebar'
import ModelSelector from './components/LLM/ModelSelector'
import SettingsView from './components/Settings/SettingsView'
import { TeamPanel } from './components/Team/TeamPanel'
import { MCPMarketplace } from './components/Skills/MCPMarketplace'
import ErrorBoundary from './components/common/ErrorBoundary'
import { ThemeSwitcher } from './components/Theme/ThemeSwitcher'
import SplashCursor from './components/effects/SplashCursor'
import TargetCursor from './components/effects/TargetCursor'
import { getSessions, createSession } from './api/memory'
import './App.css'

type View = 'chat' | 'team' | 'settings' | 'mcp'

function App() {
  const [view, setView] = useState<View>('chat')
  const [currentSessionId, setCurrentSessionId] = useState<string>('')
  const [sessionReload, setSessionReload] = useState(0)
  const { theme } = useTheme()
  const accent = themes[theme].tokens['--accent']

  const loadSessions = useCallback(async () => {
    try {
      const list = await getSessions()
      setCurrentSessionId(prev => !prev && list.length > 0 ? list[0].id : prev)
    } catch (error) {
      console.error('加载会话失败:', error)
    }
  }, [])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  const refreshSessions = useCallback(() => setSessionReload(v => v + 1), [])

  const handleNewChat = useCallback(async () => {
    try {
      const name = `新对话 ${new Date().toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}`
      const session = await createSession(name)
      setCurrentSessionId(session.id)
      setView('chat')
      refreshSessions()
    } catch (error) {
      console.error('新建会话失败:', error)
    }
  }, [refreshSessions])

  const handleSessionSelect = (sessionId: string) => {
    setCurrentSessionId(sessionId)
    setView('chat')
  }

  // 设置是独立整页, 不与主会话共用侧边栏布局
  if (view === 'settings') {
    return (
      <div className="app app--settings">
        <ErrorBoundary>
          <SettingsView
            currentSessionId={currentSessionId}
            onSessionChange={setCurrentSessionId}
            onRefreshSessions={refreshSessions}
            onBackToChat={() => setView('chat')}
          />
        </ErrorBoundary>
        <ModelSelector defaultHubVisible={false} />
      </div>
    )
  }

  return (
    <div className="app">
      <SplashCursor RAINBOW_MODE={false} COLOR={accent} SPLAT_RADIUS={0.16} DENSITY_DISSIPATION={4.2} />
      <TargetCursor targetSelector=".cursor-target, .btn, .theme-switcher-trigger" cursorColor={accent} cursorColorOnTarget="#ffffff" spinDuration={3} hideDefaultCursor={false} />
      <div className="app-container">
        <aside className="app-sidebar">
          <div className="sidebar-brand">
            <div className="brand-text"><h1>TongYong</h1></div>
            <ThemeSwitcher />
          </div>

          <div className="sidebar-actions">
            <button className="sidebar-newchat cursor-target" onClick={handleNewChat}>
              <span>新建对话</span>
            </button>
            <button
              className={`sidebar-newchat sidebar-newchat--ghost cursor-target ${view === 'team' ? 'is-active' : ''}`}
              onClick={() => setView('team')}
            >
              <span>团队</span>
            </button>
            <button
              className={`sidebar-newchat sidebar-newchat--ghost cursor-target ${view === 'mcp' ? 'is-active' : ''}`}
              onClick={() => setView('mcp')}
            >
              <span>MCP</span>
            </button>
          </div>

          <div className="sidebar-divider" />

          <div className="sidebar-section">
            <SessionSidebar
              currentSessionId={currentSessionId}
              onSessionSelect={handleSessionSelect}
              reloadSignal={sessionReload}
            />
          </div>

          <button
            className="sidebar-foot-item cursor-target"
            onClick={() => setView('settings')}
          >
            <span>设置</span>
          </button>
        </aside>

        <main className="app-main">
          <ErrorBoundary>
            {view === 'chat' && (
              <ModernChatPanel initialSessionId={currentSessionId} />
            )}
            {view === 'team' && <TeamPanel />}
            {view === 'mcp' && <MCPMarketplace />}
          </ErrorBoundary>
        </main>
      </div>
      {/* ModelSelector 默认不渲染内联 hub，仅作为事件 listener + 渲染 manager overlay 的载体 */}
      <ModelSelector defaultHubVisible={false} />
    </div>
  )
}

export default App
