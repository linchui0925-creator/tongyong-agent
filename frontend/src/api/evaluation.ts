/**
 * Evaluation API module
 * Provides functions to create and fetch evaluations, and run evaluation tasks
 */

const API_BASE_URL = '/api/evaluation';

export interface CreateEvaluationRequest {
  session_id: string;
  tools_used: string[];
  commands_executed: string[];
  processing_time: number;
  usage?: { input_tokens?: number; output_tokens?: number; total_tokens?: number };
  execution_summary?: Record<string, unknown>;
  step_history?: Array<{ id: string; text: string; status: string }>;
  notes?: string;
}

export interface CreateEvaluationTaskRequest {
  name: string;
  test_prompt: string;
  session_id?: string;
  expected_tools?: string[];
  notes?: string;
}

export interface EvaluationTask {
  id: string;
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  test_prompt: string;
  result?: EvaluationMetrics;
  error?: string;
  created_at: string;
  completed_at?: string;
}

export interface EvaluationMetrics {
  id: string;
  session_id: string;
  created_at: string;
  task_completed: boolean;
  task_completion_rate: number;
  step_accuracy_rate: number;
  tool_accuracy_rate: number;
  redundancy_rate: number;
  compliance_passed: boolean;
  compliance_violations: unknown[];
  errors_detected: number;
  corrections_successful: number;
  self_correction_rate: number;
  total_rounds: number;
  processing_time: number;
  token_usage: { input_tokens?: number; output_tokens?: number; total_tokens?: number };
  tools_used: string[];
  commands_executed: string[];
  evaluation_notes?: string;
}

export interface AggregateMetrics {
  total_evaluations: number;
  avg_task_completion: number;
  avg_step_accuracy: number;
  avg_tool_accuracy: number;
  avg_redundancy: number;
  avg_compliance: number;
  avg_self_correction: number;
  avg_processing_time: number;
  avg_total_rounds: number;
  total_errors: number;
  total_corrections: number;
}

/**
 * Create an evaluation task and run it against the agent
 */
export async function createEvaluationTask(request: CreateEvaluationTaskRequest): Promise<EvaluationTask> {
  const response = await fetch(`${API_BASE_URL}/tasks`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Failed to create evaluation task: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Get status of an evaluation task
 */
export async function getEvaluationTask(taskId: string): Promise<EvaluationTask> {
  const response = await fetch(`${API_BASE_URL}/tasks/${taskId}`);

  if (!response.ok) {
    throw new Error(`Failed to get evaluation task: ${response.statusText}`);
  }

  return response.json();
}

/**
 * List all evaluation tasks
 */
export async function listEvaluationTasks(limit: number = 20): Promise<EvaluationTask[]> {
  const response = await fetch(`${API_BASE_URL}/tasks?limit=${limit}`);

  if (!response.ok) {
    throw new Error(`Failed to list evaluation tasks: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Create a new evaluation record
 */
export async function createEvaluation(request: CreateEvaluationRequest): Promise<EvaluationMetrics> {
  const response = await fetch(`${API_BASE_URL}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Failed to create evaluation: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Get evaluations for a specific session
 */
export async function getSessionEvaluations(sessionId: string): Promise<EvaluationMetrics[]> {
  const response = await fetch(`${API_BASE_URL}/session/${sessionId}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch evaluations: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Get aggregated metrics
 */
export async function getAggregateMetrics(
  sessionId?: string,
  limit: number = 100
): Promise<AggregateMetrics> {
  const params = new URLSearchParams();
  if (sessionId) params.append('session_id', sessionId);
  params.append('limit', String(limit));

  const response = await fetch(`${API_BASE_URL}/metrics?${params.toString()}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch aggregate metrics: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Get recent evaluations
 */
export async function getRecentEvaluations(limit: number = 10): Promise<EvaluationMetrics[]> {
  const response = await fetch(`${API_BASE_URL}/recent?limit=${limit}`);

  if (!response.ok) {
    throw new Error(`Failed to fetch recent evaluations: ${response.statusText}`);
  }

  return response.json();
}

/**
 * Delete an evaluation
 */
export async function deleteEvaluation(evaluationId: string): Promise<boolean> {
  const response = await fetch(`${API_BASE_URL}/${evaluationId}`, {
    method: 'DELETE',
  });

  return response.ok;
}