import React, { useState, useEffect } from 'react';

interface DreamingStatus {
  enabled: boolean;
  last_sweep: string | null;
  pending_candidates: number;
  total_promoted: number;
  total_candidates: number;
}

export const DreamingPanel: React.FC = () => {
  const [status, setStatus] = useState<DreamingStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  useEffect(() => {
    fetchDreamingStatus();
  }, []);

  const fetchDreamingStatus = async () => {
    try {
      const response = await fetch('/api/dreaming/status');
      const data = await response.json();
      setStatus(data);
    } catch (error) {
      console.error('获取梦境状态失败:', error);
    }
  };

  const triggerDreaming = async () => {
    setLoading(true);
    try {
      await fetch('/api/dreaming/trigger', { method: 'POST' });
      await fetchDreamingStatus();
    } catch (error) {
      console.error('触发梦境失败:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 16px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-surface)',
      }}>
        <span style={{
          fontSize: '11px',
          fontWeight: 600,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.8px',
        }}>
          梦境状态
        </span>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button className="btn btn-ghost" onClick={() => setShowHelp(!showHelp)}>
            {showHelp ? '收起帮助' : '帮助'}
          </button>
          <button
            onClick={triggerDreaming}
            disabled={loading}
            className="btn btn-ghost"
          >
            {loading ? '处理中...' : '触发梦境'}
          </button>
        </div>
      </div>

      {/* Help */}
      {showHelp && (
        <div style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-secondary)',
          fontSize: '13px',
          lineHeight: 1.6,
          color: 'var(--text-secondary)',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
        }}>
          <div>
            <strong style={{ color: 'var(--text-primary)', display: 'block', marginBottom: '4px' }}>📋 什么是梦境？</strong>
            <p style={{ margin: 0 }}>梦境是 Agent 的离线反思和归纳机制。系统会在后台自动扫描对话记录，提炼出有价值的模式、偏好和见解，并将它们提升为长期记忆。</p>
          </div>
          <div>
            <strong style={{ color: 'var(--text-primary)', display: 'block', marginBottom: '4px' }}>📖 使用说明</strong>
            <ul style={{ margin: 0, paddingLeft: '20px' }}>
              <li style={{ marginBottom: '4px' }}><strong>触发梦境</strong> — 手动触发一次反思扫描，系统会分析当前对话并提炼记忆</li>
              <li style={{ marginBottom: '4px' }}><strong>待处理</strong> — 等待分析的候选条目数量</li>
              <li style={{ marginBottom: '4px' }}><strong>已晋升</strong> — 已成功转化为长期记忆的条目数</li>
              <li style={{ marginBottom: '4px' }}>梦境也会定时自动运行，无需频繁手动触发</li>
            </ul>
          </div>
        </div>
      )}

      {/* Content */}
      <div style={{
        flex: 1,
        overflow: 'auto',
        padding: '16px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
      }}>
        {/* Stats */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: '8px',
        }}>
          {[
            { label: '待处理', value: status?.pending_candidates || 0 },
            { label: '已晋升', value: status?.total_promoted || 0 },
            { label: '总候选', value: status?.total_candidates || 0 },
          ].map(stat => (
            <div key={stat.label} style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--r-lg)',
              padding: '16px',
              textAlign: 'center',
            }}>
              <div style={{
                fontSize: '24px',
                fontWeight: 700,
                color: 'var(--text-primary)',
                marginBottom: '4px',
              }}>
                {stat.value}
              </div>
              <div style={{
                fontSize: '12px',
                color: 'var(--text-tertiary)',
              }}>
                {stat.label}
              </div>
            </div>
          ))}
        </div>

        {/* Info */}
        <div style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--r-lg)',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: '13px',
            color: 'var(--text-secondary)',
          }}>
            <span>状态</span>
            <span style={{ color: status?.enabled ? 'var(--success)' : 'var(--text-tertiary)' }}>
              {status?.enabled ? '已启用' : '已禁用'}
            </span>
          </div>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: '13px',
            color: 'var(--text-secondary)',
          }}>
            <span>最后扫描</span>
            <span style={{ color: 'var(--text-tertiary)' }}>
              {status?.last_sweep || '无'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DreamingPanel;
