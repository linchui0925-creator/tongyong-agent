"""
Evaluation Service for TongYong Agent
Calculates and stores evaluation metrics for agent sessions
"""
import os
import sqlite3
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from uuid import uuid4
import logging
from app.paths import data_path

logger = logging.getLogger(__name__)


class EvaluationService:
    def __init__(self, db_path: str = data_path("tongyong.db")):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else "./data", exist_ok=True)
        self._init_tables()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_tables(self):
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                task_completed BOOLEAN DEFAULT 0,
                task_completion_rate REAL DEFAULT 0.0,
                total_steps INTEGER DEFAULT 0,
                correct_steps INTEGER DEFAULT 0,
                step_accuracy_rate REAL DEFAULT 0.0,
                total_tool_calls INTEGER DEFAULT 0,
                correct_tool_calls INTEGER DEFAULT 0,
                tool_accuracy_rate REAL DEFAULT 0.0,
                redundant_operations INTEGER DEFAULT 0,
                redundancy_rate REAL DEFAULT 0.0,
                compliance_passed BOOLEAN DEFAULT 1,
                compliance_violations TEXT DEFAULT '[]',
                errors_detected INTEGER DEFAULT 0,
                corrections_successful INTEGER DEFAULT 0,
                self_correction_rate REAL DEFAULT 0.0,
                total_rounds INTEGER DEFAULT 0,
                processing_time REAL DEFAULT 0.0,
                token_usage TEXT DEFAULT '{}',
                tools_used TEXT DEFAULT '[]',
                commands_executed TEXT DEFAULT '[]',
                execution_summary TEXT DEFAULT '{}',
                evaluation_notes TEXT
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_session_id ON evaluations(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_created_at ON evaluations(created_at DESC)")

        conn.commit()
        conn.close()

    def calculate_metrics(
        self,
        session_id: str,
        done_event_data: Dict[str, Any],
        constraint_engine_summary: Optional[Dict[str, Any]] = None,
        step_history: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        Calculate all evaluation metrics from session data.
        """
        metrics = {}

        tools_used = done_event_data.get("tools_used", [])
        commands_executed = done_event_data.get("commands_executed", [])
        processing_time = done_event_data.get("processing_time", 0.0)
        usage = done_event_data.get("usage", {})

        # 1. Task Completion Rate
        has_meaningful_action = len(tools_used) > 0 or len(commands_executed) > 0
        metrics["task_completed"] = has_meaningful_action
        metrics["task_completion_rate"] = 1.0 if has_meaningful_action else 0.0

        # 2. Step Accuracy Rate
        total_steps = 0
        correct_steps = 0
        if constraint_engine_summary:
            execution_log = constraint_engine_summary.get("execution_log", [])
            total_steps = len(execution_log)
            correct_steps = sum(1 for record in execution_log if record.get("success", False))
        elif step_history:
            total_steps = len(step_history)
            correct_steps = sum(1 for step in step_history if step.get("status") == "done")
        metrics["total_steps"] = total_steps
        metrics["correct_steps"] = correct_steps
        metrics["step_accuracy_rate"] = correct_steps / total_steps if total_steps > 0 else 0.0

        # 3. Tool Call Accuracy Rate
        total_tool_calls = len(tools_used)
        correct_tool_calls = total_tool_calls
        if constraint_engine_summary:
            execution_log = constraint_engine_summary.get("execution_log", [])
            correct_tool_calls = sum(1 for record in execution_log if record.get("success", False))
        metrics["total_tool_calls"] = total_tool_calls
        metrics["correct_tool_calls"] = correct_tool_calls
        metrics["tool_accuracy_rate"] = correct_tool_calls / total_tool_calls if total_tool_calls > 0 else 0.0

        # 4. Redundancy Rate
        redundant_ops = 0
        if constraint_engine_summary:
            execution_log = constraint_engine_summary.get("execution_log", [])
            seen = {}
            for record in execution_log:
                key = (record.get("tool_name"), str(record.get("arguments", {})))
                if key in seen:
                    redundant_ops += 1
                seen[key] = True
        metrics["redundant_operations"] = redundant_ops
        metrics["redundancy_rate"] = redundant_ops / total_steps if total_steps > 0 else 0.0

        # 5. Compliance Rate
        compliance_passed = True
        violations = []
        if constraint_engine_summary:
            commitments = constraint_engine_summary.get("commitments", [])
            for commitment in commitments:
                if not commitment.get("fulfilled", True):
                    compliance_passed = False
                    violations.append(commitment)
        metrics["compliance_passed"] = compliance_passed
        metrics["compliance_violations"] = violations

        # 6. Self-Correction Rate
        errors_detected = 0
        corrections_successful = 0
        if constraint_engine_summary:
            execution_log = constraint_engine_summary.get("execution_log", [])
            for record in execution_log:
                if not record.get("success", True):
                    errors_detected += 1
                if record.get("corrected", False):
                    corrections_successful += 1
        metrics["errors_detected"] = errors_detected
        metrics["corrections_successful"] = corrections_successful
        metrics["self_correction_rate"] = corrections_successful / errors_detected if errors_detected > 0 else 0.0

        # 7. Time Efficiency
        metrics["total_rounds"] = constraint_engine_summary.get("total_rounds", 1) if constraint_engine_summary else 1
        metrics["processing_time"] = processing_time
        metrics["token_usage"] = usage

        return metrics

    def create_evaluation(
        self,
        session_id: str,
        done_event_data: Dict[str, Any],
        constraint_engine_summary: Optional[Dict[str, Any]] = None,
        step_history: Optional[List[Dict]] = None,
        notes: Optional[str] = None,
    ) -> str:
        """Create a new evaluation record for a session."""
        evaluation_id = str(uuid4())
        created_at = datetime.now().isoformat()

        metrics = self.calculate_metrics(
            session_id,
            done_event_data,
            constraint_engine_summary,
            step_history
        )

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO evaluations (
                id, session_id, created_at, task_completed, task_completion_rate,
                total_steps, correct_steps, step_accuracy_rate,
                total_tool_calls, correct_tool_calls, tool_accuracy_rate,
                redundant_operations, redundancy_rate,
                compliance_passed, compliance_violations,
                errors_detected, corrections_successful, self_correction_rate,
                total_rounds, processing_time, token_usage,
                tools_used, commands_executed, execution_summary,
                evaluation_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            evaluation_id,
            session_id,
            created_at,
            metrics.get("task_completed", False),
            metrics.get("task_completion_rate", 0.0),
            metrics.get("total_steps", 0),
            metrics.get("correct_steps", 0),
            metrics.get("step_accuracy_rate", 0.0),
            metrics.get("total_tool_calls", 0),
            metrics.get("correct_tool_calls", 0),
            metrics.get("tool_accuracy_rate", 0.0),
            metrics.get("redundant_operations", 0),
            metrics.get("redundancy_rate", 0.0),
            metrics.get("compliance_passed", True),
            json.dumps(metrics.get("compliance_violations", [])),
            metrics.get("errors_detected", 0),
            metrics.get("corrections_successful", 0),
            metrics.get("self_correction_rate", 0.0),
            metrics.get("total_rounds", 0),
            metrics.get("processing_time", 0.0),
            json.dumps(metrics.get("token_usage", {})),
            json.dumps(done_event_data.get("tools_used", [])),
            json.dumps(done_event_data.get("commands_executed", [])),
            json.dumps(constraint_engine_summary) if constraint_engine_summary else "{}",
            notes or None
        ))

        conn.commit()
        conn.close()

        logger.info(f"Created evaluation {evaluation_id} for session {session_id}")
        return evaluation_id

    def get_evaluation(self, evaluation_id: str) -> Optional[Dict[str, Any]]:
        """Get a single evaluation by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM evaluations WHERE id = ?", (evaluation_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return self._row_to_dict(cursor.description, row)

    def get_session_evaluations(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all evaluations for a session."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM evaluations WHERE session_id = ? ORDER BY created_at DESC",
            (session_id,)
        )
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(cursor.description, row) for row in rows]

    def get_aggregate_metrics(
        self,
        session_id: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """Get aggregated metrics across sessions."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if session_id:
            cursor.execute("""
                SELECT
                    COUNT(*) as total_evaluations,
                    AVG(task_completion_rate) as avg_task_completion,
                    AVG(step_accuracy_rate) as avg_step_accuracy,
                    AVG(tool_accuracy_rate) as avg_tool_accuracy,
                    AVG(redundancy_rate) as avg_redundancy,
                    AVG(CASE WHEN compliance_passed THEN 1.0 ELSE 0.0 END) as avg_compliance,
                    AVG(self_correction_rate) as avg_self_correction,
                    AVG(processing_time) as avg_processing_time,
                    AVG(total_rounds) as avg_total_rounds,
                    SUM(errors_detected) as total_errors,
                    SUM(corrections_successful) as total_corrections
                FROM evaluations
                WHERE session_id = ?
            """, (session_id,))
        else:
            cursor.execute("""
                SELECT
                    COUNT(*) as total_evaluations,
                    AVG(task_completion_rate) as avg_task_completion,
                    AVG(step_accuracy_rate) as avg_step_accuracy,
                    AVG(tool_accuracy_rate) as avg_tool_accuracy,
                    AVG(redundancy_rate) as avg_redundancy,
                    AVG(CASE WHEN compliance_passed THEN 1.0 ELSE 0.0 END) as avg_compliance,
                    AVG(self_correction_rate) as avg_self_correction,
                    AVG(processing_time) as avg_processing_time,
                    AVG(total_rounds) as avg_total_rounds,
                    SUM(errors_detected) as total_errors,
                    SUM(corrections_successful) as total_corrections
                FROM evaluations
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return {
                "total_evaluations": 0,
                "avg_task_completion": 0.0,
                "avg_step_accuracy": 0.0,
                "avg_tool_accuracy": 0.0,
                "avg_redundancy": 0.0,
                "avg_compliance": 0.0,
                "avg_self_correction": 0.0,
                "avg_processing_time": 0.0,
                "avg_total_rounds": 0.0,
                "total_errors": 0,
                "total_corrections": 0,
            }

        columns = [desc[0] for desc in cursor.description]
        result = dict(zip(columns, row))

        # Handle None values
        for key in result:
            if result[key] is None:
                result[key] = 0.0

        return result

    def get_recent_evaluations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent evaluations across all sessions."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM evaluations
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_dict(cursor.description, row) for row in rows]

    def delete_evaluation(self, evaluation_id: str) -> bool:
        """Delete an evaluation record."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM evaluations WHERE id = ?", (evaluation_id,))
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def _row_to_dict(self, description, row) -> Dict[str, Any]:
        """Convert SQL row to dictionary."""
        columns = [desc[0] for desc in description]
        result = dict(zip(columns, row))

        if result.get("tools_used"):
            try:
                result["tools_used"] = json.loads(result["tools_used"])
            except json.JSONDecodeError:
                result["tools_used"] = []
        if result.get("commands_executed"):
            try:
                result["commands_executed"] = json.loads(result["commands_executed"])
            except json.JSONDecodeError:
                result["commands_executed"] = []
        if result.get("compliance_violations"):
            try:
                result["compliance_violations"] = json.loads(result["compliance_violations"])
            except json.JSONDecodeError:
                result["compliance_violations"] = []
        if result.get("execution_summary"):
            try:
                result["execution_summary"] = json.loads(result["execution_summary"])
            except json.JSONDecodeError:
                result["execution_summary"] = {}
        if result.get("token_usage"):
            try:
                result["token_usage"] = json.loads(result["token_usage"])
            except json.JSONDecodeError:
                result["token_usage"] = {}

        return result