import type React from 'react'

// ── Warm Color Palette ─────────────────────────────────────────
export const C = {
  bg: '#FEF7F0',
  sidebarBg: '#3D2B1F',
  sidebarCard: '#4A3728',
  card: '#FFFFFF',
  accent: '#C4703A',
  accentLight: '#F5E6D3',
  amber: '#D97706',
  amberBg: '#FEF3C7',
  text: '#7C4A2D',
  textLight: '#A0674A',
  textMuted: '#B88B6A',
  border: '#E8D5C4',
  success: '#65A30D',
  error: '#DC2626',
  running: '#1D4ED8',
  // Chat-specific (WeChat style)
  chatBg: '#F5F0EB',
  userBubble: '#A8D08D',
  userBubbleText: '#4A3728',
  agentBubble: '#FFFFFF',
  agentBubbleBorder: '#E8D5C4',
  sendBtn: '#8CB369',
}

// ── Shared inline styles ─────────────────────────────────────
export const inputStyle: React.CSSProperties = {
  padding: '7px 10px', border: `1px solid ${C.border}`, borderRadius: 8,
  background: '#2A1F14', color: '#fff', fontSize: 13, width: '100%',
  boxSizing: 'border-box',
}

export const labelStyle: React.CSSProperties = {
  fontSize: 12, fontWeight: 600, color: C.textLight, marginBottom: 4, display: 'block',
}
