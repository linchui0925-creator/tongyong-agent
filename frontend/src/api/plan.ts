/** Plan API — W5-8 plan mode / 显式规划器 */
// API_BASE_URL 没有独立 config, 用 /api/plan 前缀

export interface PlanStep {
  index: number;
  action: string;
  tool: string | null;
  status: string;
  result: string | null;
  note: string | null;
}

export interface PlanData {
  plan_id: string;
  goal: string;
  steps: PlanStep[];
  progress: { completed: number; total: number };
  is_complete: boolean;
  has_failure: boolean;
}

export async function buildPlan(goal: string): Promise<PlanData> {
  const res = await fetch('/api/plan/build', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ goal }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
