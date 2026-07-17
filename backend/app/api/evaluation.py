"""
Evaluation API endpoints
Provides REST API for evaluation operations and task execution
"""
import os
import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
from app.paths import data_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


class CreateEvaluationTaskRequest(BaseModel):
    """Request to create and run an evaluation task"""
    name: str = Field(..., min_length=1, max_length=200)
    test_prompt: str = Field(..., min_length=1, max_length=5000)
    session_id: Optional[str] = Field(None)
    expected_tools: Optional[List[str]] = Field(default_factory=list)
    notes: Optional[str] = None


class EvaluationTaskResponse(BaseModel):
    """Response for evaluation task status"""
    id: str
    name: str
    status: str  # "pending", "running", "completed", "failed"
    test_prompt: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


class CreateEvaluationRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    tools_used: List[str] = Field(default_factory=list)
    commands_executed: List[str] = Field(default_factory=list)
    processing_time: float = 0.0
    usage: Dict[str, int] = Field(default_factory=dict)
    execution_summary: Optional[Dict[str, Any]] = None
    step_history: Optional[List[Dict[str, Any]]] = None
    notes: Optional[str] = None


class EvaluationResponse(BaseModel):
    id: str
    session_id: str
    created_at: str
    task_completed: bool
    task_completion_rate: float
    total_steps: int
    correct_steps: int
    step_accuracy_rate: float
    total_tool_calls: int
    correct_tool_calls: int
    tool_accuracy_rate: float
    redundant_operations: int
    redundancy_rate: float
    compliance_passed: bool
    compliance_violations: List[Any]
    errors_detected: int
    corrections_successful: int
    self_correction_rate: float
    total_rounds: int
    processing_time: float
    token_usage: Dict[str, int]
    tools_used: List[str]
    commands_executed: List[str]
    evaluation_notes: Optional[str]


class AggregateMetricsResponse(BaseModel):
    total_evaluations: int
    avg_task_completion: float
    avg_step_accuracy: float
    avg_tool_accuracy: float
    avg_redundancy: float
    avg_compliance: float
    avg_self_correction: float
    avg_processing_time: float
    avg_total_rounds: float
    total_errors: int
    total_corrections: int


_evaluation_service = None
_evaluation_tasks: Dict[str, Dict[str, Any]] = {}


def get_evaluation_service():
    global _evaluation_service
    if _evaluation_service is None:
        from app.evaluation.service import EvaluationService
        db_path = os.environ.get("DATABASE_PATH", data_path("tongyong.db"))
        _evaluation_service = EvaluationService(db_path=db_path)
    return _evaluation_service


async def run_evaluation_task(task_id: str, request: CreateEvaluationTaskRequest):
    """Background task to run evaluation against the agent"""
    from app.main import agent_engine

    _evaluation_tasks[task_id]["status"] = "running"
    logger.info(f"[Evaluation] Task {task_id} started: {request.name}")

    try:
        tools_used = []
        commands_executed = []
        processing_time = 0.0
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        response_text = ""
        tool_calls = []

        # Collect events from stream_chat
        async for item in agent_engine.stream_chat(
            session_id=request.session_id,
            message=request.test_prompt,
            use_memory=False,  # Evaluation runs without memory
        ):
            item_type = item.get("type", "")

            if item_type == "tool_start":
                tool_calls.append({
                    "tool_name": item.get("tool_name", ""),
                    "arguments": item.get("arguments", {}),
                    "emoji": item.get("emoji", "⚡"),
                })

            elif item_type == "tool_complete":
                tool_name = item.get("tool_name", "")
                if tool_name not in tools_used:
                    tools_used.append(tool_name)
                if tool_name == "terminal":
                    args = item.get("arguments", {})
                    cmd = args.get("command", "")
                    if cmd and cmd not in commands_executed:
                        commands_executed.append(cmd)

            elif item_type == "done":
                processing_time = item.get("processing_time", 0)
                usage = item.get("usage", {})

        # Create evaluation record with actual results
        service = get_evaluation_service()
        done_event_data = {
            "session_id": request.session_id or task_id,
            "tools_used": tools_used,
            "commands_executed": commands_executed,
            "processing_time": processing_time,
            "usage": usage,
        }

        evaluation_id = service.create_evaluation(
            session_id=request.session_id or task_id,
            done_event_data=done_event_data,
            notes=f"[评估任务] {request.name}\n测试 prompt: {request.test_prompt[:100]}..."
        )

        evaluation = service.get_evaluation(evaluation_id)

        _evaluation_tasks[task_id]["status"] = "completed"
        _evaluation_tasks[task_id]["result"] = evaluation
        _evaluation_tasks[task_id]["completed_at"] = datetime.now().isoformat()

        logger.info(f"[Evaluation] Task {task_id} completed, evaluation_id: {evaluation_id}")

    except Exception as e:
        logger.error(f"[Evaluation] Task {task_id} failed: {e}", exc_info=True)
        _evaluation_tasks[task_id]["status"] = "failed"
        _evaluation_tasks[task_id]["error"] = str(e)


@router.post("/tasks", response_model=EvaluationTaskResponse)
async def create_evaluation_task(
    request: CreateEvaluationTaskRequest,
    background_tasks: BackgroundTasks
):
    """Create and execute an evaluation task against the agent"""
    from uuid import uuid4

    task_id = str(uuid4())
    created_at = datetime.now().isoformat()

    # Store task info
    _evaluation_tasks[task_id] = {
        "id": task_id,
        "name": request.name,
        "status": "pending",
        "test_prompt": request.test_prompt,
        "expected_tools": request.expected_tools,
        "notes": request.notes,
        "created_at": created_at,
    }

    # Run evaluation in background
    background_tasks.add_task(run_evaluation_task, task_id, request)

    return EvaluationTaskResponse(
        id=task_id,
        name=request.name,
        status="pending",
        test_prompt=request.test_prompt,
        created_at=created_at,
    )


@router.get("/tasks/{task_id}", response_model=EvaluationTaskResponse)
async def get_evaluation_task(task_id: str):
    """Get status of an evaluation task"""
    if task_id not in _evaluation_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = _evaluation_tasks[task_id]
    return EvaluationTaskResponse(
        id=task["id"],
        name=task["name"],
        status=task["status"],
        test_prompt=task["test_prompt"],
        result=task.get("result"),
        error=task.get("error"),
        created_at=task["created_at"],
        completed_at=task.get("completed_at"),
    )


@router.get("/tasks", response_model=List[EvaluationTaskResponse])
async def list_evaluation_tasks(limit: int = 20):
    """List all evaluation tasks"""
    tasks = list(_evaluation_tasks.values())[-limit:]
    return [EvaluationTaskResponse(
        id=t["id"],
        name=t["name"],
        status=t["status"],
        test_prompt=t["test_prompt"],
        result=t.get("result"),
        error=t.get("error"),
        created_at=t["created_at"],
        completed_at=t.get("completed_at"),
    ) for t in reversed(tasks)]


@router.post("", response_model=EvaluationResponse)
async def create_evaluation(request: CreateEvaluationRequest):
    """Create a new evaluation record."""
    service = get_evaluation_service()

    done_event_data = {
        "session_id": request.session_id,
        "tools_used": request.tools_used,
        "commands_executed": request.commands_executed,
        "processing_time": request.processing_time,
        "usage": request.usage,
    }

    evaluation_id = service.create_evaluation(
        session_id=request.session_id,
        done_event_data=done_event_data,
        constraint_engine_summary=request.execution_summary,
        step_history=request.step_history,
        notes=request.notes,
    )

    evaluation = service.get_evaluation(evaluation_id)
    if not evaluation:
        raise HTTPException(status_code=500, detail="Failed to create evaluation")

    return EvaluationResponse(**evaluation)


@router.get("/recent")
async def get_recent_evaluations(limit: int = 10) -> List[EvaluationResponse]:
    """Get recent evaluations across all sessions."""
    service = get_evaluation_service()
    evaluations = service.get_recent_evaluations(limit=limit)
    return [EvaluationResponse(**e) for e in evaluations]


@router.get("/metrics")
async def get_aggregate_metrics(
    session_id: Optional[str] = None,
    limit: int = 100
) -> AggregateMetricsResponse:
    """Get aggregated metrics across evaluations."""
    service = get_evaluation_service()

    metrics = service.get_aggregate_metrics(session_id=session_id, limit=limit)
    return AggregateMetricsResponse(**metrics)


@router.get("/session/{session_id}", response_model=List[EvaluationResponse])
async def get_session_evaluations(session_id: str):
    """Get all evaluations for a session."""
    service = get_evaluation_service()

    evaluations = service.get_session_evaluations(session_id)
    return [EvaluationResponse(**e) for e in evaluations]


@router.get("/{evaluation_id}", response_model=EvaluationResponse)
async def get_evaluation(evaluation_id: str):
    """Get a specific evaluation by ID."""
    service = get_evaluation_service()

    evaluation = service.get_evaluation(evaluation_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    return EvaluationResponse(**evaluation)


@router.delete("/{evaluation_id}")
async def delete_evaluation(evaluation_id: str):
    """Delete an evaluation."""
    service = get_evaluation_service()

    success = service.delete_evaluation(evaluation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    return {"success": True, "message": "Evaluation deleted"}