import { useState, useEffect, useCallback } from 'react';
import {
  getAggregateMetrics,
  getRecentEvaluations,
  createEvaluationTask,
  listEvaluationTasks,
  getEvaluationTask,
  EvaluationTask,
  AggregateMetrics,
  EvaluationMetrics,
} from '../../api/evaluation';
import './EvaluationDashboard.css';

interface EvaluationDashboardProps {
  currentSessionId?: string;
}

interface TaskForm {
  name: string;
  test_prompt: string;
  expected_tools: string;
  notes: string;
}

const METRIC_LABELS = [
  { key: 'task_completion', label: '任务完成率', emoji: '🎯' },
  { key: 'step_accuracy', label: '步骤准确率', emoji: '✅' },
  { key: 'tool_accuracy', label: '工具调用正确率', emoji: '🔧' },
  { key: 'redundancy', label: '冗余行为率', emoji: '🔄' },
  { key: 'compliance', label: '响应合规率', emoji: '🛡️' },
  { key: 'self_correction', label: '纠错成功率', emoji: '🔄' },
  { key: 'efficiency', label: '耗时效率', emoji: '⏱️' },
];

function formatRate(rate: number | undefined | null): string {
  if (rate == null || isNaN(rate)) return '0%';
  return (rate * 100).toFixed(1) + '%';
}

function formatTime(seconds: number | undefined | null): string {
  if (seconds == null || isNaN(seconds)) return '0.00s';
  return seconds.toFixed(2) + 's';
}

function getMetricValue(aggregate: AggregateMetrics, key: string): number {
  switch (key) {
    case 'task_completion': return aggregate.avg_task_completion || 0;
    case 'step_accuracy': return aggregate.avg_step_accuracy || 0;
    case 'tool_accuracy': return aggregate.avg_tool_accuracy || 0;
    case 'redundancy': return aggregate.avg_redundancy || 0;
    case 'compliance': return aggregate.avg_compliance || 0;
    case 'self_correction': return aggregate.avg_self_correction || 0;
    case 'efficiency': return aggregate.avg_processing_time > 0 ? Math.max(0, 1 - aggregate.avg_processing_time / 60) : 0;
    default: return 0;
  }
}

export default function EvaluationDashboard(_props: EvaluationDashboardProps) {
  const [aggregate, setAggregate] = useState<AggregateMetrics | null>(null);
  const [recentEvals, setRecentEvals] = useState<EvaluationMetrics[]>([]);
  const [tasks, setTasks] = useState<EvaluationTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showTaskModal, setShowTaskModal] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [taskForm, setTaskForm] = useState<TaskForm>({
    name: '',
    test_prompt: '',
    expected_tools: '',
    notes: '',
  });

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const agg = await getAggregateMetrics();
      setAggregate(agg);

      const recent = await getRecentEvaluations(20);
      setRecentEvals(recent);

      const taskList = await listEvaluationTasks(10);
      setTasks(taskList);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Poll task status for running tasks
  useEffect(() => {
    const runningTasks = tasks.filter(t => t.status === 'pending' || t.status === 'running');
    if (runningTasks.length === 0) return;

    const interval = setInterval(async () => {
      const updatedTasks = await Promise.all(
        runningTasks.map(async (t) => {
          try {
            return await getEvaluationTask(t.id);
          } catch {
            return t;
          }
        })
      );

      setTasks(prev => prev.map(t => {
        const updated = updatedTasks.find(u => u.id === t.id);
        return updated || t;
      }));

      // Refresh data if any task completed
      if (updatedTasks.some(t => t.status === 'completed' || t.status === 'failed')) {
        const agg = await getAggregateMetrics();
        setAggregate(agg);
        const recent = await getRecentEvaluations(20);
        setRecentEvals(recent);
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [tasks]);

  const handleSubmitTask = async () => {
    if (!taskForm.name || !taskForm.test_prompt) {
      alert('请填写任务名称和测试提示');
      return;
    }
    setSubmitting(true);
    try {
      const expected = taskForm.expected_tools.split(',').map(t => t.trim()).filter(Boolean);
      await createEvaluationTask({
        name: taskForm.name,
        test_prompt: taskForm.test_prompt,
        expected_tools: expected,
        notes: taskForm.notes || undefined,
      });
      setShowTaskModal(false);
      setTaskForm({ name: '', test_prompt: '', expected_tools: '', notes: '' });
      fetchData();
    } catch (err) {
      alert('创建任务失败: ' + (err instanceof Error ? err.message : 'Unknown error'));
    } finally {
      setSubmitting(false);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'completed': return <span className="status-badge success">✅ 完成</span>;
      case 'running': return <span className="status-badge running">🔄 运行中</span>;
      case 'failed': return <span className="status-badge danger">❌ 失败</span>;
      default: return <span className="status-badge warning">⏳ 等待</span>;
    }
  };

  if (loading && !aggregate) {
    return <div className="evaluation-dashboard loading">加载中...</div>;
  }

  return (
    <div className="evaluation-dashboard">
      <div className="dashboard-header">
        <h2>📊 Agent 评估面板</h2>
        <div className="header-actions">
          <button
            className="btn btn-primary"
            onClick={() => setShowTaskModal(true)}
          >
            + 新建评估任务
          </button>
          <button
            className="btn btn-refresh"
            onClick={fetchData}
            disabled={loading}
          >
            {loading ? '刷新中...' : '🔄 刷新'}
          </button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {/* Metrics Overview */}
      {aggregate && aggregate.total_evaluations > 0 && (
        <>
          <div className="metrics-overview">
            <div className="total-evaluations">
              <span className="big-number">{aggregate.total_evaluations}</span>
              <span className="label">次评估</span>
            </div>
            <div className="metrics-grid">
              {METRIC_LABELS.map(m => {
                const value = getMetricValue(aggregate, m.key);
                const isHigh = value >= 0.8;
                const isLow = value < 0.5;
                return (
                  <div key={m.key} className={`metric-mini ${isHigh ? 'high' : ''} ${isLow ? 'low' : ''}`}>
                    <span className="metric-emoji">{m.emoji}</span>
                    <span className="metric-label">{m.label}</span>
                    <span className="metric-value">{formatRate(value)}</span>
                    <div className="metric-bar">
                      <div className="metric-bar-fill" style={{ width: `${value * 100}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="stats-row">
            <div className="stat-item">
              <span className="stat-value">{aggregate.avg_total_rounds.toFixed(1)}</span>
              <span className="stat-label">平均轮次</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{formatTime(aggregate.avg_processing_time)}</span>
              <span className="stat-label">平均耗时</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{aggregate.total_errors}</span>
              <span className="stat-label">检测错误</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{aggregate.total_corrections}</span>
              <span className="stat-label">成功修正</span>
            </div>
          </div>
        </>
      )}

      {aggregate && aggregate.total_evaluations === 0 && (
        <div className="empty-state">
          <div className="empty-icon">📊</div>
          <div className="empty-title">暂无评估数据</div>
          <div className="empty-desc">
            点击"新建评估任务"按钮，创建一个测试任务来评估 Agent 性能。
          </div>
          <button className="btn btn-primary" onClick={() => setShowTaskModal(true)}>
            + 创建第一个评估任务
          </button>
        </div>
      )}

      {/* Evaluation Tasks */}
      {tasks.length > 0 && (
        <div className="evaluation-section">
          <h3>📋 评估任务</h3>
          <table className="evaluation-table">
            <thead>
              <tr>
                <th>任务名称</th>
                <th>状态</th>
                <th>创建时间</th>
                <th>结果</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.id}>
                  <td>
                    <div className="task-name">{t.name}</div>
                    <div className="task-prompt-preview">{t.test_prompt.slice(0, 60)}...</div>
                  </td>
                  <td>{getStatusBadge(t.status)}</td>
                  <td>{new Date(t.created_at).toLocaleString()}</td>
                  <td>
                    {t.status === 'completed' && t.result ? (
                      <div className="task-result">
                        <span className={`status-badge ${t.result.task_completed ? 'success' : 'warning'}`}>
                          {t.result.task_completed ? '完成' : '部分'}
                        </span>
                        <span className="result-tools">
                          {t.result.tools_used?.join(', ') || '-'}
                        </span>
                      </div>
                    ) : t.status === 'failed' ? (
                      <span className="error-text">{t.error?.slice(0, 50)}</span>
                    ) : t.status === 'running' ? (
                      <span className="running-text">处理中...</span>
                    ) : (
                      <span className="pending-text">等待开始</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Recent Evaluations */}
      {recentEvals.length > 0 && (
        <div className="evaluation-section">
          <h3>📜 评估结果记录</h3>
          <table className="evaluation-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>会话</th>
                <th>完成</th>
                <th>步骤</th>
                <th>工具</th>
                <th>冗余</th>
                <th>合规</th>
                <th>耗时</th>
              </tr>
            </thead>
            <tbody>
              {recentEvals.map((e) => (
                <tr key={e.id}>
                  <td>{new Date(e.created_at).toLocaleString()}</td>
                  <td className="session-id">{e.session_id.slice(0, 8)}...</td>
                  <td>
                    <span className={`status-badge ${e.task_completed ? 'success' : 'warning'}`}>
                      {e.task_completed ? '✅' : '⚠️'}
                    </span>
                  </td>
                  <td>{formatRate(e.step_accuracy_rate)}</td>
                  <td>{formatRate(e.tool_accuracy_rate)}</td>
                  <td className={e.redundancy_rate > 0.2 ? 'warning' : ''}>
                    {formatRate(e.redundancy_rate)}
                  </td>
                  <td>
                    <span className={`status-badge ${e.compliance_passed ? 'success' : 'danger'}`}>
                      {e.compliance_passed ? '✅' : '❌'}
                    </span>
                  </td>
                  <td>{formatTime(e.processing_time)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Task Creation Modal */}
      {showTaskModal && (
        <div className="modal-overlay" onClick={() => setShowTaskModal(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>📋 新建评估任务</h3>
              <button className="modal-close" onClick={() => setShowTaskModal(false)}>×</button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label>任务名称 *</label>
                <input
                  type="text"
                  placeholder="例如: 天气查询测试"
                  value={taskForm.name}
                  onChange={(e) => setTaskForm(prev => ({ ...prev, name: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <label>测试 Prompt *</label>
                <textarea
                  placeholder="输入要测试的指令，例如: 请用 terminal 执行 ls -la 命令，然后告诉我当前目录的文件列表"
                  value={taskForm.test_prompt}
                  onChange={(e) => setTaskForm(prev => ({ ...prev, test_prompt: e.target.value }))}
                  rows={4}
                />
              </div>
              <div className="form-group">
                <label>期望使用的工具 (逗号分隔，可选)</label>
                <input
                  type="text"
                  placeholder="terminal, web_search, ..."
                  value={taskForm.expected_tools}
                  onChange={(e) => setTaskForm(prev => ({ ...prev, expected_tools: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <label>备注</label>
                <textarea
                  placeholder="其他说明..."
                  value={taskForm.notes}
                  onChange={(e) => setTaskForm(prev => ({ ...prev, notes: e.target.value }))}
                  rows={2}
                />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setShowTaskModal(false)}>
                取消
              </button>
              <button
                className="btn btn-primary"
                onClick={handleSubmitTask}
                disabled={submitting || !taskForm.name || !taskForm.test_prompt}
              >
                {submitting ? '创建中...' : '创建并执行'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}