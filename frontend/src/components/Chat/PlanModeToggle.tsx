/**
 * PlanModeToggle — W5-8 plan mode 开关 pill
 * 放在输入框左工具栏, 跟 ComposerModelControl 并列。
 */
import './PlanModeToggle.css';

interface Props {
  planMode: boolean;
  onToggle: () => void;
  disabled?: boolean;
}

export default function PlanModeToggle({ planMode, onToggle, disabled }: Props) {
  return (
    <button
      type="button"
      className={`plan-mode-pill ${planMode ? 'plan-mode-pill--on' : ''}`}
      onClick={onToggle}
      disabled={disabled}
      title={planMode ? '计划模式已开启' : '开启计划模式'}
      aria-label="计划模式"
    >
      <span className="plan-mode-pill-icon">📋</span>
      <span className="plan-mode-pill-text">计划</span>
    </button>
  );
}
