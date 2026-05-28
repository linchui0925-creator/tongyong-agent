/**
 * TongYong Agent — Main Application
 */
import { useState, useEffect, useCallback } from 'react'
import ModernChatPanel from './components/Chat/ModernChatPanel'
import MemoryPanel from './components/Memory/MemoryPanel'
import SessionSidebar from './components/Session/SessionSidebar'
import ModelSelector from './components/LLM/ModelSelector'
import ProfileSelector from './components/LLM/ProfileSelector'
import DreamingPanel from './components/Dreaming/DreamingPanel'
import SkillManagement from './components/Skills/SkillManagement'
import PersonalityPanel from './components/Personality/PersonalityPanel'
import EvaluationDashboard from './components/Evaluation/EvaluationDashboard'
import { TeamPanel } from './components/Team/TeamPanel'
import { getSessions } from './api/memory'
import './App.css'

type Tab = 'chat' | 'memory' | 'skills' | 'personality' | 'dreaming' | 'profiles' | 'evaluation' | 'team'

const TABS: { key: Tab; label: string }[] = [
  { key: 'chat', label: '对话' },
  { key: 'memory', label: '记忆' },
  { key: 'skills', label: '技能' },
  { key: 'personality', label: '人格' },
  { key: 'dreaming', label: '梦境' },
  { key: 'profiles', label: 'Profiles' },
  { key: 'evaluation', label: '评估' },
  { key: 'team', label: '团队' },
]

function App() {
  const [activeTab, setActiveTab] = useState<Tab>('chat')
  const [currentSessionId, setCurrentSessionId] = useState<string>('')

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

  const handleSessionSelect = (sessionId: string) => {
    setCurrentSessionId(sessionId)
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>TongYong</h1>
        <nav className="app-nav">
          {TABS.map(tab => (
            <button
              key={tab.key}
              className={activeTab === tab.key ? 'active' : ''}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      <div className="app-container">
        <aside className="app-sidebar">
          <div className="sidebar-section">
            <SessionSidebar
              currentSessionId={currentSessionId}
              onSessionSelect={handleSessionSelect}
            />
          </div>
          <div className="sidebar-section">
            <ModelSelector />
          </div>
        </aside>

        <main className="app-main">
          {activeTab === 'chat' && (
            <ModernChatPanel initialSessionId={currentSessionId} />
          )}
          {activeTab === 'memory' && (
            <MemoryPanel
              currentSessionId={currentSessionId}
              onSessionChange={setCurrentSessionId}
              onRefreshSessions={loadSessions}
            />
          )}
          {activeTab === 'skills' && <SkillManagement />}
          {activeTab === 'personality' && <PersonalityPanel />}
          {activeTab === 'dreaming' && <DreamingPanel />}
          {activeTab === 'profiles' && <ProfileSelector />}
          {activeTab === 'evaluation' && (
            <EvaluationDashboard currentSessionId={currentSessionId} />
          )}
          {activeTab === 'team' && <TeamPanel />}
        </main>
      </div>
    </div>
  )
}

export default App
