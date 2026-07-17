import { useState, useEffect, useRef } from 'react'
import type { MessageItem } from '../../api/team'
import { C } from './constants'

// ── TaskPayload parsing ─────────────────────────────────────────
interface TaskPayloadData {
  task_id?: string
  task_type?: string
  status?: string
  description?: string
  original_requirement?: string
  result?: string
  context?: string
  current_subtask?: string
  feedback?: Array<{ reason: string; suggestions: string[]; from_agent: string }>
  rejection_count?: number
}

function parseTaskPayload(content: string): TaskPayloadData | null {
  try {
    const data = JSON.parse(content)
    if (data && typeof data === 'object' && ('task_type' in data || 'task_id' in data || 'status' in data)) {
      return data as TaskPayloadData
    }
  } catch { /* not JSON */ }
  return null
}

function formatTaskContent(content: string): string {
  const payload = parseTaskPayload(content)
  if (!payload) return content

  if (payload.status === 'rejected') {
    const fb = payload.feedback?.[0]
    const lines = ['📋 任务被退回']
    if (fb?.reason) lines.push(`退回原因: ${fb.reason}`)
    if (fb?.suggestions?.length) lines.push(`修改建议: ${fb.suggestions.join('; ')}`)
    return lines.join('\n')
  }

  if (payload.status === 'pending') {
    const desc = payload.description || payload.current_subtask
    if (desc) return desc
  }

  if (payload.task_type === 'analyze' && payload.result) return payload.result
  if (payload.result) return payload.result
  if (payload.description) return payload.description
  if (payload.current_subtask) return payload.current_subtask

  return content
}

// ── Helpers ─────────────────────────────────────────
function splitCodeBlocks(text: string): Array<{ type: 'text' | 'code'; content: string }> {
  const parts: Array<{ type: 'text' | 'code'; content: string }> = []
  const regex = /```(\w*)\s*\n([\s\S]*?)```/g
  let lastIdx = 0
  let match: RegExpExecArray | null
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIdx) {
      parts.push({ type: 'text', content: text.slice(lastIdx, match.index).trim() })
    }
    parts.push({ type: 'code', content: match[2].trim() })
    lastIdx = match.index + match[0].length
  }
  if (lastIdx < text.length) {
    parts.push({ type: 'text', content: text.slice(lastIdx).trim() })
  }
  return parts
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatTimeShort(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  if (isToday) return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) + ' ' +
    d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function getEmoji(name: string): string {
  const n = name.toLowerCase()
  if (n.includes('alice') || n.includes('coder') || n.includes('程序')) return '👨‍💻'
  if (n.includes('bob') || n.includes('tester') || n.includes('测试')) return '🧪'
  if (n.includes('charlie') || n.includes('reviewer') || n.includes('审查')) return '🔍'
  if (n.includes('biden') || n.includes('democrat')) return '🇺🇸'
  if (n.includes('trump') || n.includes('republican')) return '🗽'
  if (n.includes('debate')) return '🎭'
  return '🤖'
}

// ── Avatar ─────────────────────────────────────────
function Avatar({ name, size = 40 }: { name: string; size?: number }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: 6,
      background: `linear-gradient(135deg, ${C.accent} 0%, #8B5E3C 100%)`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: size * 0.35, flexShrink: 0, color: '#fff',
    }}>
      {getEmoji(name)}
    </div>
  )
}

// ── Round Divider ─────────────────────────────────────
function RoundDivider({ round }: { round: number }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '16px 0 8px', userSelect: 'none',
    }}>
      <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
      <span style={{
        fontSize: 11, color: C.textMuted, fontWeight: 500,
        background: C.chatBg, padding: '2px 10px', borderRadius: 10,
      }}>
        第 {round} 轮
      </span>
      <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
    </div>
  )
}

// ── Time Separator ─────────────────────────────────────
function TimeSeparator({ time }: { time: string }) {
  return (
    <div style={{
      textAlign: 'center', padding: '8px 0 4px',
    }}>
      <span style={{
        fontSize: 11, color: 'var(--text-tertiary)', background: 'var(--bg-tertiary)',
        padding: '2px 8px', borderRadius: 4,
      }}>
        {formatTimeShort(time)}
      </span>
    </div>
  )
}

// ── Code Block ──────────────────────────────────────
function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <div style={{
      background: '#2B2B2B', borderRadius: 6, overflow: 'hidden', margin: '6px 0',
      border: '1px solid #3E3E3E',
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '4px 10px', background: '#353535',
      }}>
        <span style={{ fontSize: 10, color: '#888' }}>python</span>
        <button onClick={handleCopy} style={{
          background: 'none', border: 'none', color: '#888',
          cursor: 'pointer', fontSize: 10, padding: '2px 6px', borderRadius: 3,
        }}>
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre style={{
        margin: 0, padding: '10px 12px', overflow: 'auto',
        fontSize: 12, lineHeight: 1.5, color: '#D4D4D4', maxHeight: 300,
      }}>{code}</pre>
    </div>
  )
}

// ── Typing Indicator ─────────────────────────────────────────
function TypingIndicator() {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, padding: '4px 0' }}>
      <div style={{
        width: 40, height: 40, borderRadius: 6,
        background: 'var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 14, flexShrink: 0,
      }}>
        ⏳
      </div>
      <div style={{
        background: C.agentBubble, borderRadius: '18px 18px 18px 4px',
        padding: '12px 16px', border: `1px solid ${C.agentBubbleBorder}`,
        display: 'flex', alignItems: 'center', gap: 4,
      }}>
        {[0, 1, 2].map(i => (
          <div key={i} style={{
            width: 7, height: 7, borderRadius: '50%', background: '#C0B8B0',
            animation: `bounce 1.2s infinite ${i * 0.2}s`,
          }} />
        ))}
      </div>
    </div>
  )
}

// ── Action tag colors ─────────────────────────────────────────
const actionColors: Record<string, string> = {
  UserRequirement: '#6366F1', WriteCode: '#059669', WriteTest: '#D97706',
  WriteReview: '#DC2626', SpeakAloud: '#8B5CF6',
}

// ── Message Bubble ─────────────────────────────────────────
function MessageBubble({ msg, isUser, isFirstInGroup, isLastInGroup }: {
  msg: MessageItem; isUser: boolean; isFirstInGroup: boolean; isLastInGroup: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const rawContent = formatTaskContent(msg.content)
  const codeWrapped = (msg.cause_by === 'WriteCode' || msg.cause_by === 'WriteTest') && !rawContent.includes('```')
    ? '```python\n' + rawContent + '\n```' : rawContent
  const blocks = splitCodeBlocks(codeWrapped)
  const textOnly = blocks.filter(b => b.type === 'text').map(b => b.content).join('\n')
  const CONTENT_LIMIT = 500
  const isLong = textOnly.length > CONTENT_LIMIT
  const displayText = isLong && !expanded ? textOnly.slice(0, CONTENT_LIMIT) + '...' : textOnly
  const actionColor = actionColors[msg.cause_by]

  // Bubble styling
  const bubbleStyle: React.CSSProperties = isUser
    ? {
        background: C.userBubble,
        color: C.userBubbleText,
        borderRadius: isFirstInGroup ? '18px 18px 4px 18px' : '18px 4px 4px 18px',
        border: 'none',
      }
    : {
        background: C.agentBubble,
        color: C.text,
        borderRadius: isFirstInGroup ? '4px 18px 18px 18px' : '4px 18px 18px 4px',
        border: `1px solid ${C.agentBubbleBorder}`,
      }

  return (
    <div style={{
      display: 'flex', flexDirection: isUser ? 'row-reverse' : 'row',
      alignItems: 'flex-end', gap: 8,
      marginBottom: isLastInGroup ? 16 : 3,
    }}>
      {/* Avatar: only show on first message of group */}
      {isFirstInGroup ? (
        <Avatar name={msg.sent_from} size={40} />
      ) : (
        <div style={{ width: 40, flexShrink: 0 }} />
      )}

      <div style={{
        maxWidth: '70%', display: 'flex', flexDirection: 'column',
        alignItems: isUser ? 'flex-end' : 'flex-start',
      }}>
        {/* Sender name: only on first message of group, non-user */}
        {!isUser && isFirstInGroup && (
          <span style={{
            fontSize: 12, color: C.textLight, fontWeight: 500,
            marginLeft: 4, marginBottom: 4,
          }}>
            {msg.sent_from}
          </span>
        )}

        {/* Bubble */}
        <div style={{
          ...bubbleStyle,
          padding: '10px 14px', fontSize: 14, lineHeight: 1.6,
          wordBreak: 'break-word', whiteSpace: 'pre-wrap',
        }}>
          {blocks.length === 1 && blocks[0].type === 'text' ? (
            displayText
          ) : (
            isLong && !expanded ? displayText : (
              blocks.map((b, i) => b.type === 'code'
                ? <CodeBlock key={i} code={b.content} />
                : <span key={i}>{b.content}</span>
              )
            )
          )}
        </div>

        {/* Expand/collapse */}
        {isLong && (
          <button onClick={() => setExpanded(!expanded)} style={{
            background: 'none', border: 'none', color: C.textMuted,
            cursor: 'pointer', fontSize: 11, padding: '2px 4px', marginTop: 2,
          }}>
            {expanded ? '收起' : '展开全文'}
          </button>
        )}

        {/* Action tag + time on last message */}
        {isLastInGroup && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            marginTop: 4,
            marginLeft: isUser ? 0 : 4, marginRight: isUser ? 4 : 0,
            flexDirection: isUser ? 'row-reverse' : 'row',
          }}>
            {actionColor && (
              <span style={{
                fontSize: 10, color: actionColor, fontWeight: 500,
                opacity: 0.8,
              }}>
                {msg.cause_by}
              </span>
            )}
            <span style={{ fontSize: 10, color: 'var(--text-tertiary)' }}>{formatTime(msg.created_at)}</span>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Round message detection ─────────────────────────────────────────
function isRoundMsg(msg: MessageItem): boolean {
  return msg.sent_from === 'Team' && /^\[Round\s*\d+\]$/.test(msg.content.trim())
}

function extractRound(msg: MessageItem): number {
  const m = msg.content.trim().match(/\[Round\s*(\d+)\]/)
  return m ? parseInt(m[1]) : 0
}

// ── Should show time separator ─────────────────────────────────
function shouldShowTime(msgs: MessageItem[], idx: number): boolean {
  if (idx === 0) return true
  const prev = msgs[idx - 1]
  const curr = msgs[idx]
  if (isRoundMsg(prev) || isRoundMsg(curr)) return false
  const diff = new Date(curr.created_at).getTime() - new Date(prev.created_at).getTime()
  return diff > 5 * 60 * 1000 // 5 minutes gap
}

// ── Message List ─────────────────────────────────────────
export function MessageList({ messages, isRunning }: { messages: MessageItem[]; isRunning: boolean }) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  if (messages.length === 0) {
    return (
      <div style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 16,
        background: C.chatBg,
      }}>
        <div style={{
          width: 80, height: 80, borderRadius: 20,
          background: 'var(--bg-tertiary)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 36,
        }}>💬</div>
        <div style={{ fontSize: 14, color: 'var(--text-tertiary)', textAlign: 'center', lineHeight: 1.8 }}>
          添加 Agent，输入任务<br/>即可开始协作
        </div>
      </div>
    )
  }

  const isUser = (msg: MessageItem) => msg.role === 'user' || msg.sent_from === 'user'

  // Filter out round messages for grouping logic
  const visibleMsgs = messages.filter(m => !isRoundMsg(m))

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '8px 16px', background: C.chatBg }}>
      {messages.map((msg, i) => {
        // Round divider
        if (isRoundMsg(msg)) {
          return <RoundDivider key={msg.id || i} round={extractRound(msg)} />
        }

        // Find position among visible messages
        const visibleIdx = visibleMsgs.indexOf(msg)
        const prev = visibleIdx > 0 ? visibleMsgs[visibleIdx - 1] : null
        const next = visibleIdx < visibleMsgs.length - 1 ? visibleMsgs[visibleIdx + 1] : null

        const isFirstInGroup = !prev || prev.sent_from !== msg.sent_from || isRoundMsg(prev)
        const isLastInGroup = !next || next.sent_from !== msg.sent_from || isRoundMsg(next)

        const result: JSX.Element[] = []

        // Time separator
        if (shouldShowTime(messages, i)) {
          result.push(<TimeSeparator key={`time-${msg.id || i}`} time={msg.created_at} />)
        }

        result.push(
          <MessageBubble
            key={msg.id || i} msg={msg} isUser={isUser(msg)}
            isFirstInGroup={isFirstInGroup} isLastInGroup={isLastInGroup}
          />
        )

        return result
      })}
      {isRunning && <TypingIndicator />}
      <div ref={bottomRef} />
    </div>
  )
}
