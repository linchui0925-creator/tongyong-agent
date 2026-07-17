import type React from 'react'

// ── Warm Color Palette ─────────────────────────────────────────
export const C = {
  bg: 'var(--bg-secondary)',
  sidebarBg: 'var(--bg-inset)',
  sidebarCard: 'var(--bg-tertiary)',
  card: 'var(--bg-card)',
  accent: 'var(--accent)',
  accentLight: 'var(--accent-subtle)',
  amber: 'var(--warning)',
  amberBg: 'var(--warning-subtle)',
  text: 'var(--text-primary)',
  textLight: 'var(--text-secondary)',
  textMuted: 'var(--text-tertiary)',
  border: 'var(--border)',
  success: 'var(--success)',
  error: 'var(--danger)',
  running: 'var(--accent)',
  // Chat-specific
  chatBg: 'var(--bg-primary)',
  userBubble: 'var(--bubble-user-bg-end)',
  userBubbleText: 'var(--bubble-user-text)',
  agentBubble: 'var(--bubble-agent-bg)',
  agentBubbleBorder: 'var(--bubble-agent-border)',
  sendBtn: 'var(--accent)',
}

// ── Shared inline styles ─────────────────────────────────────
export const inputStyle: React.CSSProperties = {
  padding: '7px 10px', border: `1px solid ${C.border}`, borderRadius: 8,
  background: 'var(--bg-inset)', color: 'var(--text-primary)', fontSize: 13, width: '100%',
  boxSizing: 'border-box',
}

export const labelStyle: React.CSSProperties = {
  fontSize: 12, fontWeight: 600, color: C.textLight, marginBottom: 4, display: 'block',
}
