export interface CozeSkill {
  id: string; name: string; description: string; icon?: string; author?: string;
  usage_count?: number; installed: boolean; prompt?: string; trigger_words?: string[];
  dependencies?: string[]; has_platform_dependency?: boolean; category?: string;
  source: 'builtin' | 'community' | 'official';
}
export interface SearchResult {
  success: boolean; total: number; page: number; page_size: number; categories: string[];
  sort_by: string; source_filter: string; official_available: boolean;
  community_available: boolean; community_loaded: boolean; community_loading: boolean;
  community_count: number; list: CozeSkill[];
}
export interface CozeConfig {
  success: boolean; coze_cookie_set: boolean; enable_community: boolean; official_available: boolean;
}
export interface InstallResult { success: boolean; message: string; skill: CozeSkill; }
export interface InstalledSkillBody { name: string; body: string; metadata: any; }

const API = '/api/skills/coze';

export async function getConfig(): Promise<CozeConfig> {
  const r = await fetch(`${API}/config`); if(!r.ok) throw new Error('获取配置失败'); return r.json();
}
export async function saveConfig(cookie: string, enableCommunity: boolean): Promise<CozeConfig> {
  const r = await fetch(`${API}/config`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({coze_cookie:cookie, enable_community:enableCommunity})});
  if(!r.ok) throw new Error('保存失败'); return r.json();
}
export async function loadCommunity(force = false): Promise<{success:boolean; count:number; message:string}> {
  const r = await fetch(`${API}/community/load?force=${force}`, {method:'POST'});
  if(!r.ok) throw new Error('加载失败'); return r.json();
}
export async function search(
  keyword='', page=1, pageSize=24, category?:string, sortBy='hot', sourceFilter='all', loadCommunity=false
): Promise<SearchResult> {
  const p = new URLSearchParams({keyword, page:String(page), page_size:String(pageSize), sort_by:sortBy, source_filter:sourceFilter, load_community:String(loadCommunity)});
  if(category && category!=='全部') p.append('category', category);
  const r = await fetch(`${API}/search?${p}`);
  if(!r.ok) {const e=await r.json().catch(()=>({detail:'搜索失败'})); throw new Error(e.detail||'搜索失败');}
  return r.json();
}
export async function getCategories(): Promise<string[]> {
  const r = await fetch(`${API}/categories`); if(!r.ok) throw new Error('获取分类失败'); return (await r.json()).categories;
}
export async function getDetail(id: string): Promise<CozeSkill> {
  const r = await fetch(`${API}/${id}`); if(!r.ok) {const e=await r.json().catch(()=>({detail:'获取详情失败'})); throw new Error(e.detail||'获取详情失败');}
  return (await r.json()).skill;
}
export async function translate(id: string, lang='英文'): Promise<CozeSkill> {
  const r = await fetch(`${API}/${id}/translate?target_lang=${encodeURIComponent(lang)}`, {method:'POST'});
  if(!r.ok) {const e=await r.json().catch(()=>({detail:'翻译失败'})); throw new Error(e.detail||'翻译失败');}
  return (await r.json()).skill;
}
export async function install(id: string, translateLang?: string): Promise<InstallResult> {
  let url = `${API}/${id}/install`;
  if(translateLang) url += `?translate_to_lang=${encodeURIComponent(translateLang)}`;
  const r = await fetch(url, {method:'POST'});
  if(!r.ok) {const e=await r.json().catch(()=>({detail:'安装失败'})); throw new Error(e.detail||'安装失败');}
  return r.json();
}
export async function getInstalledBody(id: string): Promise<InstalledSkillBody> {
  const r = await fetch(`${API}/installed/coze_${id}/body`);
  if(!r.ok) {const e=await r.json().catch(()=>({detail:'读取失败'})); throw new Error(e.detail||'读取失败');}
  return r.json();
}
