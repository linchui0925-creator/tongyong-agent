const API_BASE = '/api/skills/coze';

export interface CozeSkill {
  id: string;
  name: string;
  description: string;
  icon?: string;
  author?: string;
  usage_count?: number;
  installed: boolean;
  prompt?: string;
  trigger_words?: string[];
  dependencies?: string[];
  has_platform_dependency?: boolean;
}

export interface SearchResult {
  success: boolean;
  total: number;
  page: number;
  page_size: number;
  list: CozeSkill[];
}

export async function searchCozeSkills(keyword = '', page = 1, pageSize = 20): Promise<SearchResult> {
  try {
    const params = new URLSearchParams({ keyword, page: String(page), page_size: String(pageSize) });
    const res = await fetch(`${API_BASE}/search?${params}`);
    if (!res.ok) {
      let msg = '搜索技能失败';
      try { const e = await res.json(); msg = e.detail || msg; } catch {}
      throw new Error(msg);
    }
    return res.json();
  } catch (e) {
    if (e instanceof Error) throw e;
    throw new Error('网络请求失败，请检查网络连接');
  }
}

export async function getCozeSkillDetail(skillId: string): Promise<{ success: boolean; skill: CozeSkill }> {
  const res = await fetch(`${API_BASE}/${skillId}`);
  if (!res.ok) {
    let msg = '获取技能详情失败';
    try { const e = await res.json(); msg = e.detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

export async function installCozeSkill(skillId: string): Promise<{ success: boolean; message: string; skill: CozeSkill }> {
  try {
    const res = await fetch(`${API_BASE}/${skillId}/install`, { method: 'POST' });
    if (!res.ok) {
      let msg = '安装技能失败';
      try { const e = await res.json(); msg = e.detail || msg; } catch {}
      throw new Error(msg);
    }
    return res.json();
  } catch (e) {
    if (e instanceof Error) throw e;
    throw new Error('网络请求失败，请检查网络连接');
  }
}
