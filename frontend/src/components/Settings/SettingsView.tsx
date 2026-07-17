/**
 * SettingsView — Codex 风格设置页
 *
 * 左侧分组导航 (个人 / 功能), 右侧内容区。
 * 把原来散落在顶层 tab 的功能 (技能/记忆/人格/梦境/模型/评估/团队) 全部收进设置页,
 * 并新增「常规 / 外观 / 快捷键」三个原生设置分区。
 */
import { useState } from 'react'
import { themeList, type ThemeId } from '../../theme/themes'
import { useTheme } from '../../theme/ThemeContext'
import MemoryPanel from '../Memory/MemoryPanel'
import DreamingPanel from '../Dreaming/DreamingPanel'
import { SkillManagement } from '../Skills/SkillManagement'
import PersonalityPanel from '../Personality/PersonalityPanel'
import EvaluationDashboard from '../Evaluation/EvaluationDashboard'
import ProfileSelector from '../LLM/ProfileSelector'
import './SettingsView.css'

type SettingsKey =
  | 'general' | 'appearance' | 'shortcuts'
  | 'skills' | 'memory' | 'personality' | 'dreaming' | 'profiles' | 'evaluation'

interface SettingsGroup {
  title: string
  items: { key: SettingsKey; label: string }[]
}

const GROUPS: SettingsGroup[] = [
  {
    title: '个人',
    items: [
      { key: 'general', label: '常规' },
      { key: 'appearance', label: '外观' },
      { key: 'shortcuts', label: '键盘快捷键' },
    ],
  },
  {
    title: '功能',
    items: [
      { key: 'skills', label: '技能' },
      { key: 'memory', label: '记忆' },
      { key: 'personality', label: '人格' },
      { key: 'dreaming', label: '梦境' },
      { key: 'profiles', label: '模型' },
      { key: 'evaluation', label: '评估' },
    ],
  },
]

const SHORTCUTS: { keys: string; desc: string }[] = [
  { keys: '⌘ / Ctrl + Enter', desc: '发送消息' },
  { keys: 'Shift + Enter', desc: '换行' },
  { keys: 'Esc', desc: '停止生成 / 关闭弹层' },
  { keys: '⌘ / Ctrl + K', desc: '新建对话' },
  { keys: '⌘ / Ctrl + ,', desc: '打开设置' },
]

interface SettingsViewProps {
  currentSessionId: string
  onSessionChange: (id: string) => void
  onRefreshSessions: () => void
  onBackToChat: () => void
}

function ToggleRow({
  title, desc, value, onChange,
}: { title: string; desc: string; value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="set-row">
      <div className="set-row-text">
        <div className="set-row-title">{title}</div>
        <div className="set-row-desc">{desc}</div>
      </div>
      <button
        className={`set-toggle cursor-target ${value ? 'is-on' : ''}`}
        onClick={() => onChange(!value)}
        role="switch"
        aria-checked={value}
      >
        <span className="set-toggle-knob" />
      </button>
    </div>
  )
}

export default function SettingsView({
  currentSessionId, onSessionChange, onRefreshSessions, onBackToChat,
}: SettingsViewProps) {
  const [active, setActive] = useState<SettingsKey>('general')
  const [query, setQuery] = useState('')
  const { theme, setTheme } = useTheme()

  const [autoReview, setAutoReview] = useState(true)
  const [fullAccess, setFullAccess] = useState(false)
  const [menuBar, setMenuBar] = useState(true)

  const filteredGroups = GROUPS.map(g => ({
    ...g,
    items: g.items.filter(it => it.label.includes(query.trim())),
  })).filter(g => g.items.length > 0)

  const renderContent = () => {
    switch (active) {
      case 'general':
        return (
          <div className="set-content">
            <h2 className="set-h2">常规</h2>
            <p className="set-lede">管理权限、语言与基础行为。</p>
            <div className="set-section-label">权限</div>
            <div className="set-card">
              <ToggleRow
                title="自动审核"
                desc="维知 可以自动审查工具的额外访问请求；自动审查可能会出错。"
                value={autoReview}
                onChange={setAutoReview}
              />
              <div className="set-divider" />
              <ToggleRow
                title="完全访问权限"
                desc="允许无需批准即可编辑文件并运行访问网络的命令，会显著增加风险。"
                value={fullAccess}
                onChange={setFullAccess}
              />
            </div>
            <div className="set-section-label">常规</div>
            <div className="set-card">
              <div className="set-row">
                <div className="set-row-text">
                  <div className="set-row-title">语言</div>
                  <div className="set-row-desc">应用界面语言</div>
                </div>
                <span className="set-row-value">简体中文</span>
              </div>
              <div className="set-divider" />
              <ToggleRow
                title="在菜单栏中显示"
                desc="关闭主窗口后仍在系统菜单栏中保留 维知。"
                value={menuBar}
                onChange={setMenuBar}
              />
            </div>
          </div>
        )
      case 'appearance':
        return (
          <div className="set-content">
            <h2 className="set-h2">外观</h2>
            <p className="set-lede">选择配色主题，随四季切换整体氛围。</p>
            <div className="set-section-label">主题（绿野四季）</div>
            <div className="set-theme-grid">
              {themeList.map(t => (
                <button
                  key={t.id}
                  className={`set-theme-card cursor-target ${t.id === theme ? 'is-active' : ''}`}
                  onClick={() => setTheme(t.id as ThemeId)}
                >
                  <span
                    className="set-theme-swatch"
                    style={{
                      background: `linear-gradient(135deg, ${t.tokens['--accent']} 0%, ${t.tokens['--bg-primary']} 100%)`,
                    }}
                  />
                  <span className="set-theme-name"><span className="set-theme-name-glyph">{t.glyph}</span>{t.name}</span>
                  <span className="set-theme-desc">{t.description}</span>
                  {t.id === theme && <span className="set-theme-check">✓</span>}
                </button>
              ))}
            </div>
          </div>
        )
      case 'shortcuts':
        return (
          <div className="set-content">
            <h2 className="set-h2">键盘快捷键</h2>
            <p className="set-lede">常用操作快捷键一览。</p>
            <div className="set-card">
              {SHORTCUTS.map((s, i) => (
                <div key={s.keys}>
                  {i > 0 && <div className="set-divider" />}
                  <div className="set-row">
                    <div className="set-row-text">
                      <div className="set-row-title">{s.desc}</div>
                    </div>
                    <span className="set-kbd">{s.keys}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      case 'skills':
        return <div className="set-embed"><SkillManagement /></div>
      case 'memory':
        return (
          <div className="set-embed">
            <MemoryPanel
              currentSessionId={currentSessionId}
              onSessionChange={onSessionChange}
              onRefreshSessions={onRefreshSessions}
            />
          </div>
        )
      case 'personality':
        return <div className="set-embed"><PersonalityPanel /></div>
      case 'dreaming':
        return <div className="set-embed"><DreamingPanel /></div>
      case 'profiles':
        return <div className="set-embed"><ProfileSelector /></div>
      case 'evaluation':
        return <div className="set-embed"><EvaluationDashboard currentSessionId={currentSessionId} /></div>
      default:
        return null
    }
  }

  return (
    <div className="settings-view">
      <aside className="settings-nav">
        <button className="settings-back cursor-target" onClick={onBackToChat}>
          ‹ 返回对话
        </button>
        <input
          className="settings-search"
          placeholder="搜索设置…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="settings-nav-scroll">
          {filteredGroups.map(group => (
            <div key={group.title} className="settings-nav-group">
              <div className="settings-nav-grouptitle">{group.title}</div>
              {group.items.map(it => (
                <button
                  key={it.key}
                  className={`settings-nav-item cursor-target ${active === it.key ? 'is-active' : ''}`}
                  onClick={() => setActive(it.key)}
                >
                  {it.label}
                </button>
              ))}
            </div>
          ))}
        </div>
      </aside>
      <div className="settings-body">
        {renderContent()}
      </div>
    </div>
  )
}
