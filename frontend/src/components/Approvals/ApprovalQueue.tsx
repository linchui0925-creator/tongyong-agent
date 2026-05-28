// 审批队列界面
import React, { useState, useEffect } from 'react';

interface ApprovalRequest {
  id: string;
  tool_id: string;
  session_id: string;
  user_id: string;
  risk_assessment: {
    risk_level: string;
    matched_patterns?: any[];
  };
  created_at: string;
}

export const ApprovalQueue: React.FC = () => {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [loading, setLoading] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [selectedApproval, setSelectedApproval] = useState<ApprovalRequest | null>(null);

  useEffect(() => {
    fetchApprovals();
    const interval = setInterval(fetchApprovals, 10000);
    return () => clearInterval(interval);
  }, []);

  const fetchApprovals = async () => {
    try {
      const response = await fetch('/api/tools/approvals/pending');
      const data = await response.json();
      setApprovals(data.approvals || []);
    } catch (error) {
      console.error('获取审批列表失败:', error);
    }
  };

  const handleApproval = async (approvalId: string, action: 'approve' | 'reject', reason?: string) => {
    setLoading(true);
    try {
      await fetch('/api/tools/approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approval_id: approvalId, action, reason })
      });
      fetchApprovals();
      setSelectedApproval(null);
      setRejectReason('');
    } catch (error) {
      console.error('处理审批失败:', error);
    } finally {
      setLoading(false);
    }
  };

  const getRiskColor = (level: string) => {
    switch (level) {
      case 'critical': return 'red';
      case 'high': return 'orange';
      case 'medium': return 'yellow';
      default: return 'green';
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString();
  };

  return (
    <div className="approval-queue">
      <div className="queue-header">
        <h2>⚠️ 待审批操作</h2>
        <span className="queue-count">{approvals.length} 项待审批</span>
      </div>

      {approvals.length === 0 ? (
        <div className="empty-state">
          <p>🎉 没有待审批的操作</p>
        </div>
      ) : (
        <div className="approvals-list">
          {approvals.map(approval => (
            <div key={approval.id} className="approval-card">
              <div className="approval-header">
                <span className={`risk-badge ${getRiskColor(approval.risk_assessment.risk_level)}`}>
                  {approval.risk_assessment.risk_level.toUpperCase()}
                </span>
                <span className="approval-time">{formatDate(approval.created_at)}</span>
              </div>
              
              <div className="approval-body">
                <div className="approval-info">
                  <span>工具: {approval.tool_id}</span>
                  <span>会话: {approval.session_id}</span>
                  <span>申请人: {approval.user_id}</span>
                </div>
                
                {approval.risk_assessment.matched_patterns && approval.risk_assessment.matched_patterns.length > 0 && (
                  <div className="risk-patterns">
                    <strong>检测到的风险模式:</strong>
                    <ul>
                      {approval.risk_assessment.matched_patterns.map((p: any, i: number) => (
                        <li key={i}>
                          {p.description} ({p.risk_level})
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
              
              <div className="approval-actions">
                <button
                  onClick={() => handleApproval(approval.id, 'approve')}
                  disabled={loading}
                  className="btn-approve"
                >
                  批准
                </button>
                <button
                  onClick={() => setSelectedApproval(approval)}
                  disabled={loading}
                  className="btn-reject"
                >
                  拒绝
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedApproval && (
        <div className="reject-modal" onClick={() => setSelectedApproval(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>拒绝审批</h3>
            <textarea
              placeholder="请输入拒绝原因..."
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="reject-reason"
            />
            <div className="modal-actions">
              <button
                onClick={() => setSelectedApproval(null)}
                className="btn-cancel"
              >
                取消
              </button>
              <button
                onClick={() => handleApproval(selectedApproval.id, 'reject', rejectReason)}
                disabled={!rejectReason}
                className="btn-confirm-reject"
              >
                确认拒绝
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ApprovalQueue;
