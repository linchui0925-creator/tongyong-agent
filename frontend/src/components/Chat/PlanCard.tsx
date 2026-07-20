/**
 * PlanCard — W5-8 plan mode 计划步骤卡片
 *
 * 显示 LLM 生成的多步 Action 计划, 支持 Approve/Reject 操作。
 */
import { useState } from 'react';
import type { PlanData } from '../../api/plan';
import './PlanCard.css';

interface PlanCardProps {
  plan: PlanData;
  onApprove: () => void;
  onReject: () => void;
  busy?: boolean;
}

export default function PlanCard({ plan, onApprove, onReject, busy }: PlanCardProps) {
  const [collapsed, setCollapsed] = useState(false);
  const total = plan.steps.length;
  const done = plan.progress.completed;

  return (
    <div className="plan-card">
      <div className="plan-card-header">
        <span className="plan-card-icon">📋</span>
        <span className="plan-card-title">计划 · {total} 步</span>
        <button
          type="button"
          className="plan-card-toggle"
          onClick={() => setCollapsed(c => !c)}
          aria-label={collapsed ? '展开' : '收起'}
        >
          {collapsed ? '▶' : '▼'}
        </button>
      </div>

      <div className="plan-card-goal">{plan.goal}</div>

      {!collapsed && (
        <ol className="plan-card-steps">
          {plan.steps.map((s) => (
            <li key={s.index} className="plan-card-step">
              <div className="plan-card-step-num">{s.index}</div>
              <div className="plan-card-step-body">
                <div className="plan-card-step-action">{s.action}</div>
                {s.tool && <div className="plan-card-step-tool">🔧 {s.tool}</div>}
              </div>
            </li>
          ))}
        </ol>
      )}

      {done > 0 && (
        <div className="plan-card-progress">
          进度: {done}/{total} 步完成
        </div>
      )}

      <div className="plan-card-actions">
        <button
          type="button"
          className="plan-card-btn plan-card-btn--approve"
          onClick={onApprove}
          disabled={busy}
        >
          {busy ? '执行中...' : '✓ 批准执行'}
        </button>
        <button
          type="button"
          className="plan-card-btn plan-card-btn--reject"
          onClick={onReject}
          disabled={busy}
        >
          ✗ 重新规划
        </button>
      </div>
    </div>
  );
}
