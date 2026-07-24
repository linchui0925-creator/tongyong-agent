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

function deriveCollectedItems(plan: PlanData) {
  const collected: string[] = [];
  collected.push(`目标：${plan.goal}`);
  collected.push(`计划步骤：${plan.steps.length} 步`);

  const tools = Array.from(new Set(plan.steps.map((s) => s.tool).filter((t): t is string => Boolean(t))));
  if (tools.length > 0) {
    collected.push(`涉及工具：${tools.join('、')}`);
  }

  const completed = plan.steps.filter((s) => s.status === 'done' || s.status === 'completed' || s.status === 'success');
  if (completed.length > 0) {
    collected.push(`已完成步骤：${completed.map((s) => s.index).join('、')}`);
  }

  return collected;
}

function deriveMissingItems(plan: PlanData) {
  const missing: string[] = [];
  if (!plan.goal.trim()) missing.push('缺少明确目标');

  const noToolSteps = plan.steps.filter((s) => !s.tool).map((s) => `第 ${s.index} 步未指定工具`);
  missing.push(...noToolSteps);

  const noNoteSteps = plan.steps.filter((s) => !s.note).map((s) => `第 ${s.index} 步缺少补充说明`);
  if (noNoteSteps.length === plan.steps.length) {
    missing.push('缺少执行依据、约束或验收标准');
  }

  const noResultSteps = plan.steps.filter((s) => !s.result).map((s) => `第 ${s.index} 步尚无结果`);
  if (noResultSteps.length > 0 && noResultSteps.length < plan.steps.length) {
    missing.push(`仍有 ${noResultSteps.length} 步未产出结果`);
  }

  return Array.from(new Set(missing));
}

export default function PlanCard({ plan, onApprove, onReject, busy }: PlanCardProps) {
  const [collapsed, setCollapsed] = useState(false);
  const total = plan.steps.length;
  const done = plan.progress.completed;
  const collectedItems = deriveCollectedItems(plan);
  const missingItems = deriveMissingItems(plan);

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
          {collapsed ? '展开' : '收起'}
        </button>
      </div>

      <div className="plan-card-goal">{plan.goal}</div>

      <div className="plan-card-grid">
        <section className="plan-card-section">
          <div className="plan-card-section-title">已收集资料</div>
          <ul className="plan-card-list">
            {collectedItems.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>
        <section className="plan-card-section plan-card-section--warn">
          <div className="plan-card-section-title">缺少信息</div>
          <ul className="plan-card-list">
            {missingItems.length > 0 ? missingItems.map((item) => <li key={item}>{item}</li>) : <li>暂无明显缺口</li>}
          </ul>
        </section>
      </div>

      {!collapsed && (
        <ol className="plan-card-steps">
          {plan.steps.map((s) => (
            <li key={s.index} className="plan-card-step">
              <div className="plan-card-step-num">{s.index}</div>
              <div className="plan-card-step-body">
                <div className="plan-card-step-action">{s.action}</div>
                {s.tool && <div className="plan-card-step-tool">🔧 {s.tool}</div>}
                {s.note && <div className="plan-card-step-note">{s.note}</div>}
              </div>
              <div className={`plan-card-step-status plan-card-step-status--${s.status}`}>{s.status}</div>
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
