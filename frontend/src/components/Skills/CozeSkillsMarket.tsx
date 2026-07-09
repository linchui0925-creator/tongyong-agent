import React, { useState, useEffect, useCallback } from 'react';
import { searchCozeSkills, installCozeSkill, type CozeSkill } from '../../api/cozeSkills';
import './CozeSkillsMarket.css';

const CozeSkillsMarket: React.FC<{ onInstall?: () => void }> = ({ onInstall }) => {
  const [keyword, setKeyword] = useState('');
  const [skills, setSkills] = useState<CozeSkill[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [installingId, setInstallingId] = useState<string | null>(null);
  const [selectedSkill, setSelectedSkill] = useState<CozeSkill | null>(null);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const showToast = (type: 'success' | 'error', message: string) => {
    setToast({ type, message });
    setTimeout(() => setToast(null), 3000);
  };

  const loadSkills = useCallback(async (searchKw = '') => {
    setLoading(true);
    setError('');
    try {
      const res = await searchCozeSkills(searchKw);
      setSkills(res.list);
    } catch (e: any) {
      setError(e.message || '加载技能列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSkills();
  }, [loadSkills]);

  // 防抖搜索
  useEffect(() => {
    const timer = setTimeout(() => {
      loadSkills(keyword);
    }, 300);
    return () => clearTimeout(timer);
  }, [keyword, loadSkills]);

  const handleInstall = async (skillId: string) => {
    setInstallingId(skillId);
    try {
      const res = await installCozeSkill(skillId);
      showToast('success', res.message);
      // 更新本地状态
      setSkills(prev => prev.map(s => s.id === skillId ? { ...s, installed: true } : s));
      if (selectedSkill?.id === skillId) {
        setSelectedSkill(prev => prev ? { ...prev, installed: true } : null);
      }
      // 刷新本地技能列表
      if (onInstall) onInstall();
    } catch (e: any) {
      showToast('error', e.message || '安装失败');
    } finally {
      setInstallingId(null);
    }
  };

  return (
    <div className="coze-market-container">
      <div className="market-header">
        <h3>扣子技能市场</h3>
        <p className="market-desc">实时搜索扣子公开技能，一键安装到本地使用</p>
        <div className="search-bar">
          <input
            type="text"
            placeholder="搜索技能名称/功能/触发词..."
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
            className="search-input"
          />
        </div>
      </div>

      {error && <div className="error-tip">{error}</div>}
      {loading && <div className="loading-state">加载中...</div>}

      <div className="skills-grid">
        {skills.map(skill => (
          <div key={skill.id} className="skill-card">
            <div className="skill-card-header">
              <span className="skill-icon">{skill.icon || '🤖'}</span>
              <div className="skill-title-area">
                <h4 className="skill-name">{skill.name}</h4>
                <span className="skill-author">{skill.author || '扣子官方'}</span>
              </div>
              {skill.installed && <span className="installed-badge">已安装</span>}
            </div>
            <p className="skill-desc">{skill.description}</p>
            <div className="skill-meta">
              <span className="usage-count">🔥 {(skill.usage_count || 0).toLocaleString()} 人使用</span>
              <div className="skill-actions">
                <button
                  className="detail-btn"
                  onClick={() => setSelectedSkill(skill)}
                >
                  详情
                </button>
                <button
                  className={`install-btn ${skill.installed ? 'installed' : ''}`}
                  disabled={skill.installed || installingId === skill.id}
                  onClick={() => handleInstall(skill.id)}
                >
                  {installingId === skill.id ? '安装中...' : skill.installed ? '已安装' : '安装'}
                </button>
              </div>
            </div>
          </div>
        ))}
        {!loading && skills.length === 0 && !error && (
          <div className="empty-state">没有找到相关技能，试试其他关键词吧</div>
        )}
      </div>

      {/* 详情弹窗 */}
      {selectedSkill && (
        <div className="detail-modal-overlay" onClick={() => setSelectedSkill(null)}>
          <div className="detail-modal" onClick={e => e.stopPropagation()}>
            <div className="detail-header">
              <span className="detail-icon">{selectedSkill.icon || '🤖'}</span>
              <div>
                <h3>{selectedSkill.name}</h3>
                <span className="detail-author">{selectedSkill.author || '扣子官方'}</span>
              </div>
              <button className="close-btn" onClick={() => setSelectedSkill(null)}>✕</button>
            </div>
            <div className="detail-body">
              <p className="detail-desc">{selectedSkill.description}</p>
              {selectedSkill.has_platform_dependency && (
                <div className="dependency-warning">
                  ⚠️ 提示：本技能部分能力依赖扣子平台专属工具，安装后部分功能可能需要手动适配
                </div>
              )}
              {selectedSkill.trigger_words && selectedSkill.trigger_words.length > 0 && (
                <div className="trigger-section">
                  <h4>触发词示例</h4>
                  <div className="trigger-tags">
                    {selectedSkill.trigger_words.map((tw, i) => (
                      <span key={i} className="trigger-tag">{tw}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
            <div className="detail-footer">
              <button
                className={`install-btn large ${selectedSkill.installed ? 'installed' : ''}`}
                disabled={selectedSkill.installed || installingId === selectedSkill.id}
                onClick={() => handleInstall(selectedSkill.id)}
              >
                {installingId === selectedSkill.id ? '安装中...' : selectedSkill.installed ? '已安装' : '立即安装'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast提示 */}
      {toast && (
        <div className={`toast ${toast.type}`}>{toast.message}</div>
      )}
    </div>
  );
};

export default CozeSkillsMarket;
