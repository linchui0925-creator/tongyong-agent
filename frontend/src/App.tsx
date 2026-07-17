/**
 * App — 维知 · The Thinking Loom (W5-3)
 *
 * 居中聊天 + 左侧控制脊柱 + 顶部可编辑会话标题
 * AmbientScene 拓扑线场背景 + 维知 飘逸 wordmark
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useTheme } from './theme/ThemeContext';
import { themes } from './theme/themes';
import ModernChatPanel from './components/Chat/ModernChatPanel';
import SessionSidebar from './components/Session/SessionSidebar';
import ModelSelector from './components/LLM/ModelSelector';
import SettingsView from './components/Settings/SettingsView';
import { TeamPanel } from './components/Team/TeamPanel';
import { MCPMarketplace } from './components/Skills/MCPMarketplace';
import ErrorBoundary from './components/common/ErrorBoundary';
import AmbientScene from './components/common/AmbientScene';
import { ThemeSwitcher } from './components/Theme/ThemeSwitcher';
import SplashCursor from './components/effects/SplashCursor';
import { getSessions, createSession, updateSession } from './api/memory';
import type { Session } from './types';
import './App.css'

type View = 'chat' | 'team' | 'settings' | 'mcp'

function App() {
  const [view, setView] = useState<View>('chat')
  const [currentSessionId, setCurrentSessionId] = useState<string>('')
  const [sessionReload, setSessionReload] = useState(0)
  const [sessions, setSessions] = useState<Session[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const { theme } = useTheme()
  const accent = themes[theme].tokens['--accent']

  // 当前会话对象 (用于顶部标题)
  const currentSession = useMemo(
    () => sessions.find(s => s.id === currentSessionId) || null,
    [sessions, currentSessionId]
  )

  const loadSessions = useCallback(async () => {
    try {
      const list = await getSessions()
      setSessions(list)
      setCurrentSessionId(prev => !prev && list.length > 0 ? list[0].id : prev)
    } catch (error) {
      console.error('加载会话失败:', error)
    }
  }, [])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  // 监听全局流式状态 (ModernChatPanel 写入)
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ streaming?: boolean }>).detail
      if (detail && typeof detail.streaming === 'boolean') {
        setIsStreaming(detail.streaming)
      }
    }
    window.addEventListener('weizhi:streaming', handler as EventListener)
    return () => window.removeEventListener('weizhi:streaming', handler as EventListener)
  }, [])

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

  // ── 顶部标题栏: 维知 + 可编辑会话名 ──
  const renderTitleBar = () => (
    <header className="app-titlebar">
      <div className="app-titlebar-inner">
        <div className="app-titlebar-left">
          <ThemeSwitcher />
        </div>
        <SessionTitleEditor
          session={currentSession}
          onRename={async (name) => {
            if (!currentSession) return
            try {
              await updateSession(currentSession.id, name)
              refreshSessions()
            } catch (e) {
              console.error('重命名会话失败:', e)
            }
          }}
        />
        <div className="app-titlebar-right">
          <span className="app-titlebar-chip" title="当前主题">
            <span className="app-titlebar-chip-dot" />
            {themes[theme].glyph} · {themes[theme].name}
          </span>
        </div>
      </div>
      {isStreaming && <div className="app-titlebar-progress" aria-hidden="true" />}
    </header>
  )

  // 设置是独立整页
  if (view === 'settings') {
    return (
      <div className="app app--settings" data-theme={theme}>
        <AmbientScene />
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
    <div className="app" data-theme={theme}>
      <AmbientScene />
      {/* SplashCursor 调低密度/小半径, 仅作边缘装饰 */}
      <SplashCursor RAINBOW_MODE={false} COLOR={accent} SPLAT_RADIUS={0.08} DENSITY_DISSIPATION={9} DYE_RESOLUTION={640} />

      <div className="app-container">
        <aside className="app-sidebar">
          <div className="sidebar-brand">
            <div className="brand-text">
              <h1><span className="brand-mark">维</span>知</h1>
              <span className="brand-sub">Weizhi</span>
            </div>
          </div>

          <div className="sidebar-actions">
            <button className="sidebar-newchat cursor-target" onClick={handleNewChat}>
              <span className="sidebar-nav-index">+</span>
              <span>新建对话</span>
            </button>
            <button
              className={`sidebar-newchat sidebar-newchat--ghost cursor-target ${view === 'team' ? 'is-active' : ''}`}
              onClick={() => setView('team')}
            >
              <span className="sidebar-nav-index">02</span>
              <span>团队协作</span>
            </button>
            <button
              className={`sidebar-newchat sidebar-newchat--ghost cursor-target ${view === 'mcp' ? 'is-active' : ''}`}
              onClick={() => setView('mcp')}
            >
              <span className="sidebar-nav-index">03</span>
              <span>MCP 技能市场</span>
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
            <span className="sidebar-nav-index">04</span>
            <span>设置</span>
          </button>
        </aside>

        <main className="app-main">
          {renderTitleBar()}
          <ErrorBoundary>
            {view === 'chat' && (
              <ModernChatPanel initialSessionId={currentSessionId} />
            )}
            {view === 'team' && <TeamPanel />}
            {view === 'mcp' && <MCPMarketplace />}
          </ErrorBoundary>
        </main>
      </div>
      <ModelSelector defaultHubVisible={false} />
    </div>
  )
}

// ── 顶部可编辑会话标题 ──────────────────────────
function SessionTitleEditor({
  session,
  onRename,
}: {
  session: Session | null
  onRename: (name: string) => Promise<void> | void
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(session?.name || '')

  useEffect(() => {
    if (!editing) setValue(session?.name || '')
  }, [session?.name, editing])

  const startEdit = () => {
    if (!session) return
    setEditing(true)
    setValue(session.name)
    // 等下一拍 focus
    setTimeout(() => {
      const el = ref.current
      if (el) {
        el.focus()
        // 选中全文
        const range = document.createRange()
        range.selectNodeContents(el)
        const sel = window.getSelection()
        sel?.removeAllRanges()
        sel?.addRange(range)
      }
    }, 0)
  }

  const commit = async () => {
    setEditing(false)
    const next = value.trim()
    if (!next || !session) return
    if (next === session.name) return
    await onRename(next)
  }

  const cancel = () => {
    setEditing(false)
    setValue(session?.name || '')
  }

  if (!session) {
    return (
      <span
        className="app-titlebar-name is-placeholder"
        data-placeholder="新会话"
        title="新建或选择一个会话"
      >
        维知 · 新会话
      </span>
    )
  }

  return (
    <span
      ref={ref}
      className={`app-titlebar-name ${editing ? 'is-editing' : ''} ${!session ? 'is-placeholder' : ''}`}
      contentEditable={editing}
      suppressContentEditableWarning
      onClick={startEdit}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          ;(e.target as HTMLElement).blur()
        } else if (e.key === 'Escape') {
          e.preventDefault()
          cancel()
          ;(e.target as HTMLElement).blur()
        }
      }}
      title={editing ? '' : '点击编辑会话名'}
    >
      {editing ? value : (session.name || '未命名会话')}
    </span>
  )
}

export default App
