import React, { useState, useEffect, useCallback } from 'react';
import { search, install, getInstalledBody, translate, getCategories, getConfig, saveConfig, loadCommunity, type CozeSkill, type CozeConfig } from '../../api/cozeSkills';
import './CozeSkillsMarket.css';

const PAGE_SIZE = 24;

const CozeSkillsMarket: React.FC<{onInstall?: ()=>void}> = ({onInstall}) => {
  const [keyword, setKeyword] = useState('');
  const [activeCategory, setActiveCategory] = useState('全部');
  const [sortBy, setSortBy] = useState('hot');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [categories, setCategories] = useState<string[]>([]);
  const [skills, setSkills] = useState<CozeSkill[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [installingId, setInstallingId] = useState<string|null>(null);
  const [selectedSkill, setSelectedSkill] = useState<CozeSkill|null>(null);
  const [translatedSkill, setTranslatedSkill] = useState<CozeSkill|null>(null);
  const [translating, setTranslating] = useState(false);
  const [translateTarget, setTranslateTarget] = useState('英文');
  const [toast, setToast] = useState<{type:'success'|'error', msg:string}|null>(null);
  const [installedBody, setInstalledBody] = useState<{name:string; body:string; metadata:any}|null>(null);
  const [loadingBody, setLoadingBody] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [config, setConfig] = useState<CozeConfig|null>(null);
  const [cookieInput, setCookieInput] = useState('');
  const [enableCommunity, setEnableCommunity] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [communityLoading, setCommunityLoading] = useState(false);

  const showToast = (t:'success'|'error', m:string) => {setToast({type:t,msg:m}); setTimeout(()=>setToast(null),3000);};

  useEffect(()=>{getConfig().then(c=>{setConfig(c); setEnableCommunity(c.enable_community);}).catch(()=>{});},[]);
  useEffect(()=>{if(config) getCategories().then(setCategories).catch(()=>{});},[config]);

  const load = useCallback(async(kw='', cat='全部', sort='hot', src='all', pg=1, append=false, loadComm=false) => {
    if(!append) setLoading(true);
    setError('');
    try {
      const res = await search(kw, pg, PAGE_SIZE, cat, sort, src, loadComm);
      setSkills(prev => append ? [...prev, ...res.list] : res.list);
      setPage(res.page); setTotal(res.total);
      setCommunityLoading(res.community_loading);
      setConfig(prev=>prev?{...prev, official_available: res.official_available, enable_community: res.community_available}:null);
    } catch(e:any) {setError(e.message); if(!append) setSkills([]);}
    finally {setLoading(false);}
  }, []);

  useEffect(()=>{
    if(config) {
      const t = setTimeout(()=>{load(keyword, activeCategory, sortBy, sourceFilter, 1, false); setTranslatedSkill(null);}, keyword?300:0);
      return ()=>clearTimeout(t);
    }
  },[keyword, activeCategory, sortBy, sourceFilter, config, load]);

  const handleLoadCommunity = async () => {
    setCommunityLoading(true);
    try {
      const res = await loadCommunity(true);
      showToast('success', res.message);
      load(keyword, activeCategory, sortBy, sourceFilter, 1, false, true);
    } catch(e:any) {showToast('error', e.message||'加载失败');}
    finally {setCommunityLoading(false);}
  };

  const handleSaveConfig = async () => {
    setSavingConfig(true);
    try {
      const c = await saveConfig(cookieInput, enableCommunity);
      setConfig(c);
      showToast('success', '配置保存成功');
      setShowSettings(false);
      load(keyword, activeCategory, sortBy, sourceFilter, 1, false);
    } catch(e:any) {showToast('error', e.message||'保存失败');}
    finally {setSavingConfig(false);}
  };

  const handleInstall = async (id:string, tl?:string) => {
    setInstallingId(id);
    try {
      const r = await install(id, tl);
      showToast('success', r.message);
      setSkills(prev=>prev.map(s=>s.id===id?{...s, installed:true}:s));
      if(selectedSkill?.id===id) setSelectedSkill(prev=>prev?{...prev, installed:true}:null);
      onInstall?.();
    } catch(e:any) {showToast('error', e.message||'安装失败');}
    finally {setInstallingId(null);}
  };

  const handleViewInstalled = async (id:string) => {
    setLoadingBody(true);
    try {const d = await getInstalledBody(id); setInstalledBody({name:d.name, body:d.body, metadata:d.metadata});}
    catch(e:any) {showToast('error', e.message||'读取失败');}
    finally {setLoadingBody(false);}
  };

  const handleTranslate = async () => {
    if(!selectedSkill) return;
    setTranslating(true);
    try {const t = await translate(selectedSkill.id, translateTarget); setTranslatedSkill(t); showToast('success', `已翻译为${translateTarget}`);}
    catch(e:any) {showToast('error', e.message||'翻译失败');}
    finally {setTranslating(false);}
  };

  const srcLabel = (s:string) => s==='official'?'🏛️ 官方':s==='community'?'🌐 社区':'⭐ 内置';
  const hasMore = skills.length < total;
  const ds = translatedSkill || selectedSkill;

  return (
    <div className="coze-market-container">
      <div className="market-header">
        <div className="search-bar-row">
          <div className="search-bar">
            <span className="search-icon">🔍</span>
            <input type="text" placeholder="搜索技能，秒开无等待..." value={keyword} onChange={e=>setKeyword(e.target.value)} className="search-input"/>
            {keyword && <button className="clear-btn" onClick={()=>setKeyword('')}>✕</button>}
          </div>
          <select className="sort-select" value={sortBy} onChange={e=>setSortBy(e.target.value)}>
            <option value="hot">🔥 最热</option><option value="relevance">🎯 相关</option>
          </select>
          <button className="settings-btn" onClick={()=>setShowSettings(true)}>⚙️</button>
        </div>
        <div className="result-hint">
          {loading ? '加载中...' : `共${total}个技能`}
          {config?.enable_community && !communityLoading && config.enable_community && (
            <button className="load-community-btn" onClick={handleLoadCommunity} disabled={communityLoading}>
              {communityLoading?'⏳ 加载社区中...':'🌐 加载社区技能'}
            </button>
          )}
          {config?.official_available && <span className="official-badge">✅ 官方实时对接</span>}
        </div>
        <div className="source-tabs">
          <button className={`source-tab ${sourceFilter==='all'?'active':''}`} onClick={()=>setSourceFilter('all')}>全部</button>
          <button className={`source-tab ${sourceFilter==='builtin'?'active':''}`} onClick={()=>setSourceFilter('builtin')}>⭐ 精选</button>
          {config?.enable_community && <button className={`source-tab ${sourceFilter==='community'?'active':''}`} onClick={()=>{setSourceFilter('community'); if(skills.filter(s=>s.source==='community').length===0) handleLoadCommunity();}}>🌐 社区</button>}
          {config?.official_available && <button className={`source-tab ${sourceFilter==='official'?'active':''}`} onClick={()=>setSourceFilter('official')}>🏛️ 官方</button>}
        </div>
      </div>

      <div className="category-tabs">
        {categories.map(c=><button key={c} className={`category-tab ${activeCategory===c?'active':''}`} onClick={()=>setActiveCategory(c)}>{c}</button>)}
      </div>

      {error && <div className="error-state">{error}</div>}
      {loading && skills.length===0 && <div className="loading-state">加载精选技能中...</div>}

      <div className="skills-grid">
        {skills.map(s=>(
          <div key={s.id} className={`skill-card ${s.installed?'installed':''}`}>
            <div className="skill-card-header">
              <span className="skill-icon">{s.icon||'🤖'}</span>
              <div className="skill-meta">
                <h3 className="skill-name">{s.name}</h3>
                <div className="skill-info">
                  <span className="skill-source">{srcLabel(s.source)}</span>
                  <span className="skill-category">{s.category}</span>
                  <span className="skill-usage">👥{(s.usage_count||0).toLocaleString()}</span>
                </div>
              </div>
              {s.installed && <span className="installed-badge">已安装</span>}
            </div>
            <p className="skill-desc">{s.description}</p>
            {s.trigger_words && s.trigger_words.length>0 && (
              <div className="skill-trigger-preview">
                {s.trigger_words.slice(0,3).map((tw,i)=><span key={i} className="trigger-tag-small">{tw}</span>)}
                {s.trigger_words.length>3 && <span className="trigger-more">+{s.trigger_words.length-3}</span>}
              </div>
            )}
            <div className="skill-card-actions">
              <button className="detail-btn" onClick={()=>{setSelectedSkill(s); setTranslatedSkill(null);}}>详情</button>
              {s.installed ? (
                <button className="view-btn" onClick={()=>handleViewInstalled(s.id)}>查看</button>
              ) : (
                <button className="install-btn" disabled={installingId===s.id} onClick={()=>handleInstall(s.id)}>
                  {installingId===s.id?'安装中...':'安装'}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {!loading && skills.length===0 && !error && keyword && (
        <div className="empty-state">
          <div className="empty-icon">🔍</div><p>没找到「{keyword}」</p>
          <p className="empty-hint">{!config?.official_available?'配置Cookie可搜索官方全量技能':'换个关键词试试'}</p>
        </div>
      )}

      {hasMore && (
        <div className="load-more-row">
          <button className="load-more-btn" disabled={loading} onClick={()=>load(keyword,activeCategory,sortBy,sourceFilter,page+1,true)}>
            {loading?'加载中...':`加载更多 (${skills.length}/${total})`}
          </button>
        </div>
      )}

      {/* 详情弹窗 */}
      {selectedSkill && ds && (
        <div className="detail-modal-overlay" onClick={()=>setSelectedSkill(null)}>
          <div className="detail-modal" onClick={e=>e.stopPropagation()}>
            <div className="detail-header">
              <span className="detail-icon">{ds.icon||'🤖'}</span>
              <div className="detail-title">
                <h3>{ds.name}</h3>
                <div className="detail-meta">
                  <span>{srcLabel(ds.source)}</span><span>•</span><span>{ds.author}</span><span>•</span><span>{ds.category}</span><span>•</span><span>{(ds.usage_count||0).toLocaleString()}次</span>
                </div>
              </div>
              <button className="close-btn" onClick={()=>setSelectedSkill(null)}>✕</button>
            </div>
            <div className="detail-body">
              <p className="detail-desc">{ds.description}</p>
              {ds.has_platform_dependency && <div className="dependency-warning">⚠️ 部分功能可能依赖平台专属工具</div>}
              {ds.trigger_words && ds.trigger_words.length>0 && (
                <div className="trigger-section"><h4>触发词</h4>
                  <div className="trigger-tags">{ds.trigger_words.map((tw,i)=><span key={i} className="trigger-tag">{tw}</span>)}</div>
                </div>
              )}
              {ds.prompt && (
                <div className="prompt-section"><h4>完整技能规则（可直接运行）</h4>
                  <div className="prompt-content">{ds.prompt}</div>
                </div>
              )}
            </div>
            <div className="detail-footer">
              <div className="translate-row">
                <select className="lang-select" value={translateTarget} onChange={e=>setTranslateTarget(e.target.value)}>
                  <option value="英文">英文</option><option value="日文">日文</option><option value="韩文">韩文</option><option value="繁体中文">繁体中文</option>
                </select>
                <button className="translate-btn" disabled={translating} onClick={handleTranslate}>{translating?'翻译中...':`🌐 翻译为${translateTarget}`}</button>
                {translatedSkill && <button className="reset-translate-btn" onClick={()=>setTranslatedSkill(null)}>恢复原文</button>}
              </div>
              <div className="action-row">
                {ds.installed ? (
                  <button className="view-btn large" onClick={()=>handleViewInstalled(selectedSkill.id)}>📄 查看本地SKILL.md</button>
                ) : (
                  <>
                    <button className="install-btn large" disabled={installingId===selectedSkill.id} onClick={()=>handleInstall(selectedSkill.id)}>
                      {installingId===selectedSkill.id?'安装中...':'安装（中文版）'}
                    </button>
                    <button className="install-btn outline large" disabled={installingId===selectedSkill.id} onClick={()=>handleInstall(selectedSkill.id, translateTarget)}>
                      安装（{translateTarget}版）
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 本地SKILL查看 */}
      {installedBody && (
        <div className="detail-modal-overlay" onClick={()=>setInstalledBody(null)}>
          <div className="detail-modal" onClick={e=>e.stopPropagation()}>
            <div className="detail-header">
              <span className="detail-icon">📄</span>
              <div className="detail-title"><h3>{installedBody.metadata?.name||installedBody.name}</h3><span className="detail-author">本地完整SKILL.md</span></div>
              <button className="close-btn" onClick={()=>setInstalledBody(null)}>✕</button>
            </div>
            <div className="detail-body"><pre className="skill-md-preview">{installedBody.body}</pre></div>
            <div className="detail-footer"><button className="install-btn large" onClick={()=>setInstalledBody(null)}>关闭</button></div>
          </div>
        </div>
      )}

      {/* 设置弹窗 */}
      {showSettings && (
        <div className="detail-modal-overlay" onClick={()=>setShowSettings(false)}>
          <div className="detail-modal settings-modal" onClick={e=>e.stopPropagation()}>
            <div className="detail-header">
              <span className="detail-icon">⚙️</span>
              <div className="detail-title"><h3>技能市场设置</h3><span className="detail-author">配置后可搜索官方全量技能</span></div>
              <button className="close-btn" onClick={()=>setShowSettings(false)}>✕</button>
            </div>
            <div className="detail-body">
              <div className="setting-item">
                <label><input type="checkbox" checked={enableCommunity} onChange={e=>setEnableCommunity(e.target.checked)}/> 启用SkillHub社区技能</label>
                <p className="setting-hint">开启后可手动加载数千个社区公开技能</p>
              </div>
              <div className="setting-item">
                <label>Coze官网Cookie（可选）</label>
                <textarea className="cookie-input" rows={4} placeholder="登录www.coze.cn后，F12复制Cookie粘贴到这里可实时搜索官网全量技能..." value={cookieInput} onChange={e=>setCookieInput(e.target.value)}/>
                <p className="setting-hint">状态：{config?.official_available?'✅ 已配置官方搜索':'❌ 未配置'}</p>
                <p className="setting-hint">💡 Cookie仅保存在本地，不会上传</p>
              </div>
            </div>
            <div className="detail-footer"><button className="install-btn large" disabled={savingConfig} onClick={handleSaveConfig}>{savingConfig?'保存中...':'保存配置'}</button></div>
          </div>
        </div>
      )}

      {loadingBody && <div className="toast">读取中...</div>}
      {toast && <div className={`toast ${toast.type}`}>{toast.msg}</div>}
    </div>
  );
};
export default CozeSkillsMarket;
