import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { MODELS_DATA, getModelsByCategory, searchModels, type ModelInfo } from './modelsData';
import { switchModel, getCurrentModel, getSavedModels, deleteSavedModel, switchToSavedModel, type SavedModel } from '../../api/llm';
import AddModelDialog from './AddModelDialog';
import './ModelSelector.css';

export default function ModelSelector() {
  const [isOpen, setIsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedModel, setSelectedModel] = useState<ModelInfo>(MODELS_DATA[0]);
  const [activeCategory, setActiveCategory] = useState<string>('all');
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [savedModels, setSavedModels] = useState<SavedModel[]>([]);
  const [currentProvider, setCurrentProvider] = useState('');
  const [currentBackendModel, setCurrentBackendModel] = useState<string>('');
  const [switchingId, setSwitchingId] = useState<string | null>(null);

  const dropdownRef = useRef<HTMLDivElement>(null);
  const modelGroups = useMemo(() => getModelsByCategory(), []);

  const loadSavedModels = useCallback(async () => {
    try {
      const data = await getSavedModels();
      setSavedModels(data.models);
    } catch (e) {
      console.error('[ModelSelector] 加载已保存模型失败:', e);
    }
  }, []);

  const loadCurrentModel = useCallback(async () => {
    try {
      const currentConfig = await getCurrentModel();
      setCurrentProvider(currentConfig.provider);
      setCurrentBackendModel(currentConfig.model || '');
      const modelName = currentConfig.model;
      // 优先精确匹配 provider + model
      const exact = MODELS_DATA.find(m =>
        m.provider === currentConfig.provider && m.name === modelName
      );
      if (exact) {
        setSelectedModel(exact);
        return;
      }
      // 其次按 provider 匹配（同一个提供商选第一个）
      const byProvider = MODELS_DATA.find(m => m.provider === currentConfig.provider);
      if (byProvider) {
        setSelectedModel(byProvider);
        return;
      }
      // 兜底：用后端返回的 provider/model 构建显示（适配所有第三方保存的模型）
      setSelectedModel({
        id: currentConfig.provider,
        name: modelName || '',
        displayName: modelName || currentConfig.provider,
        version: '',
        provider: currentConfig.provider,
        providerDisplayName: currentConfig.name || currentConfig.provider,
        category: 'commercial',
        description: '',
        capabilities: [],
        defaultEndpoint: '',
        docsUrl: '',
        icon: currentConfig.icon || '⚙',
        color: currentConfig.color || '#888',
      } as ModelInfo);
    } catch (error) {
      console.error('[ModelSelector] 加载当前模型失败:', error);
    }
  }, []);

  useEffect(() => {
    loadCurrentModel();
    loadSavedModels();
  }, [loadCurrentModel, loadSavedModels]);

  // Reload saved models + current model after closing the add dialog
  useEffect(() => {
    if (!showAddDialog) {
      loadSavedModels();
      loadCurrentModel();
    }
  }, [showAddDialog, loadSavedModels, loadCurrentModel]);

  const filteredGroups = useMemo(() => {
    if (!searchQuery.trim()) {
      if (activeCategory === 'all') return modelGroups;
      return modelGroups.filter(g => g.category === activeCategory);
    }
    const results = searchModels(searchQuery);
    const grouped: Record<string, typeof results> = {};
    results.forEach(m => {
      if (!grouped[m.category]) grouped[m.category] = [];
      grouped[m.category].push(m);
    });
    return Object.entries(grouped).map(([category, models]) => {
      const catInfo = modelGroups.find(g => g.category === category);
      return { category, models, displayName: catInfo?.displayName || category };
    });
  }, [searchQuery, activeCategory, modelGroups]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelect = async (model: ModelInfo) => {
    setSelectedModel(model);
    setIsOpen(false);
    try {
      const result = await switchModel(model.provider, undefined, model.name);
      if (result) {
        await Promise.all([loadCurrentModel(), loadSavedModels()]);
      }
    } catch (error) {
      console.error('切换模型失败:', error);
    }
  };

  const handleSavedModelClick = async (saved: SavedModel) => {
    setSwitchingId(saved.id);
    try {
      const result = await switchToSavedModel(saved.id);
      if (result.success) {
        // Reload current model + saved models from backend
        await Promise.all([loadCurrentModel(), loadSavedModels()]);
      }
    } catch (error) {
      console.error('切换到已保存模型失败:', error);
    } finally {
      setSwitchingId(null);
    }
  };

  const handleDeleteSaved = async (e: React.MouseEvent, saved: SavedModel) => {
    e.stopPropagation();
    try {
      await deleteSavedModel(saved.id);
      setSavedModels(prev => prev.filter(m => m.id !== saved.id));
    } catch (error) {
      console.error('删除模型失败:', error);
    }
  };

  return (
    <div className="model-selector" ref={dropdownRef} style={{ position: 'relative' }}>
      <div className="model-selector-header">
        <span>模型</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {savedModels.length > 0 && (
            <span style={{ fontSize: 10, color: 'var(--text-muted)', background: 'var(--bg-inset)', padding: '1px 6px', borderRadius: 4 }}>
              {savedModels.length}
            </span>
          )}
          <button className="model-add-btn" onClick={() => setShowAddDialog(true)} title="添加模型">+</button>
        </div>
      </div>

      <button
        className={`model-selector-current ${isOpen ? 'open' : ''}`}
        onClick={() => setIsOpen(!isOpen)}
      >
        <span>{selectedModel.displayName}</span>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" style={{
          transform: isOpen ? 'rotate(180deg)' : undefined,
          transition: 'transform 0.12s ease',
        }}>
          <path d="M3 5l3 3 3-3" />
        </svg>
      </button>

      {isOpen && (
        <div className="model-selector-dropdown">
          <div className="model-selector-search">
            <input
              type="text"
              placeholder="搜索模型..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <div className="model-categories">
            <button
              className={`model-category ${activeCategory === 'all' ? 'active' : ''}`}
              onClick={() => setActiveCategory('all')}
            >
              全部
            </button>
            {modelGroups.map(group => (
              <button
                key={group.category}
                className={`model-category ${activeCategory === group.category ? 'active' : ''}`}
                onClick={() => setActiveCategory(group.category)}
              >
                {group.displayName}
              </button>
            ))}
          </div>

          <div className="model-list">
            {/* ── Saved models section (inside dropdown) ── */}
            {savedModels.length > 0 && (
              <div className="dropdown-saved-models">
                <div className="model-group-header">
                  <span className="model-group-name">已添加</span>
                  <span className="model-group-count">{savedModels.length}</span>
                </div>
                <div className="model-group-items">
                  {savedModels.map(saved => {
                    const isCurrent = saved.provider === currentProvider &&
                      (saved.model === currentBackendModel);
                    const isSwitching = switchingId === saved.id;
                    return (
                      <div
                        key={saved.id}
                        className={`model-item saved-model-in-dropdown ${isCurrent ? 'selected' : ''} ${isSwitching ? 'switching' : ''}`}
                        onClick={() => { setIsOpen(false); handleSavedModelClick(saved); }}
                      >
                        <div className="model-item-icon" style={{ background: 'var(--accent-subtle)', color: 'var(--accent)' }}>
                          ★
                        </div>
                        <div className="model-item-info">
                          <div className="model-item-name">{saved.name || saved.model}</div>
                          <div className="model-item-provider">
                            {saved.provider}
                            {saved.api_endpoint && (
                              <span className="saved-model-endpoint"> · {saved.api_endpoint}</span>
                            )}
                          </div>
                        </div>
                        <div className="saved-model-actions">
                          {isCurrent && <span className="saved-model-badge">当前</span>}
                          {isSwitching && <span className="saved-model-spinner" />}
                          <button
                            className="saved-model-delete"
                            onClick={(e) => { e.stopPropagation(); handleDeleteSaved(e, saved); }}
                            title="删除"
                          >
                            ✕
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="dropdown-divider" />
              </div>
            )}

            {/* ── Built-in model groups ── */}
            {filteredGroups.length === 0 ? (
              <div className="model-list-empty">未找到匹配模型</div>
            ) : (
              filteredGroups.map(group => (
                <div key={group.category} className="model-group">
                  <div className="model-group-header">
                    <span className="model-group-name">{group.displayName}</span>
                    <span className="model-group-count">{group.models.length}</span>
                  </div>
                  <div className="model-group-items">
                    {group.models.map(model => (
                      <div
                        key={model.id}
                        className={`model-item ${model.id === selectedModel.id ? 'selected' : ''}`}
                        onClick={() => handleSelect(model)}
                      >
                        <div className="model-item-icon" style={{ background: model.color + '20', color: model.color }}>
                          {model.icon}
                        </div>
                        <div className="model-item-info">
                          <div className="model-item-name">{model.displayName}</div>
                          <div className="model-item-provider">{model.providerDisplayName}</div>
                        </div>
                        {model.id === selectedModel.id && (
                          <span className="model-item-check">✓</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      <AddModelDialog
        open={showAddDialog}
        onClose={() => setShowAddDialog(false)}
      />
    </div>
  );
}
