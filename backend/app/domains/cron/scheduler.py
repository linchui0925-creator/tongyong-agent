"""
Cron job scheduler - executes due jobs.

Provides tick() which checks for due jobs and runs them.
Uses a file-based lock to prevent concurrent ticks.
"""

import asyncio
import concurrent.futures
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# fcntl is Unix-only
try:
    import fcntl
except ImportError:
    fcntl = None

from app.domains.cron.jobs import (
    get_due_jobs, mark_job_run, save_job_output, advance_next_run,
    CRON_DIR, OUTPUT_DIR, _now
)

# File-based lock
_LOCK_FILE = CRON_DIR / ".tick.lock"

# Silent marker
SILENT_MARKER = "[SILENT]"


def _resolve_delivery_target(job: dict) -> Optional[dict]:
    """Resolve the delivery target for a cron job."""
    deliver = job.get("deliver", "local")

    if deliver == "local":
        return None

    # Parse platform:chat_id:thread_id format
    if ":" in deliver:
        parts = deliver.split(":")
        platform = parts[0]
        chat_id = parts[1] if len(parts) > 1 else None
        thread_id = parts[2] if len(parts) > 2 else None
        if platform and chat_id:
            return {"platform": platform, "chat_id": chat_id, "thread_id": thread_id}

    return None


def _deliver_result(job: dict, content: str) -> Optional[str]:
    """
    Deliver job output to the configured target.

    Returns None on success, or an error string on failure.
    """
    target = _resolve_delivery_target(job)
    if not target:
        return None

    platform = target.get("platform", "").lower()
    chat_id = target.get("chat_id")

    if not chat_id:
        return "No chat_id specified for delivery"

    # TODO: 实现实际的消息投递
    # 目前只记录日志
    logger.info(
        "Job '%s': would deliver to %s:%s (delivery not yet implemented)",
        job.get("id"),
        platform,
        chat_id
    )

    return None


def _build_job_prompt(job: dict) -> str:
    """Build the effective prompt for a cron job."""
    prompt = job.get("prompt", "")
    skills = job.get("skills")

    # Prepend cron execution guidance
    cron_hint = (
        "[SYSTEM: You are running as a scheduled cron job. "
        "Your final response will be automatically delivered to the user. "
        "If there is nothing new to report, respond with exactly \"[SILENT]\" "
        "to suppress delivery.]\n\n"
    )
    prompt = cron_hint + prompt

    # Load skills if configured
    skill_names = [str(name).strip() for name in (skills or []) if str(name).strip()]
    if not skill_names:
        return prompt

    # Try to load skill content
    parts = []
    skipped = []

    for skill_name in skill_names:
        try:
            from app.domains.tools.skill_executor import SkillExecutor
            executor = SkillExecutor()
            result = await_execute_sync(executor.execute, "view", {"name": skill_name})
            if result.get("success"):
                content = result.get("content", "").strip()
                if content:
                    parts.extend([
                        f'[SYSTEM: The "{skill_name}" skill is loaded.]',
                        "",
                        content,
                    ])
            else:
                skipped.append(skill_name)
        except Exception as e:
            logger.warning("Failed to load skill '%s': %s", skill_name, e)
            skipped.append(skill_name)

    if skipped:
        notice = f"[SYSTEM: Skill(s) not found and skipped: {', '.join(skipped)}]"
        parts.insert(0, notice)

    if prompt:
        parts.extend(["", f"Task: {prompt}"])

    return "\n".join(parts) if parts else prompt


def await_execute_sync(func, *args, **kwargs):
    """Execute async function synchronously."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Create a new loop in a thread if needed
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, func(*args, **kwargs))
                return future.result()
        else:
            return loop.run_until_complete(func(*args, **kwargs))
    except RuntimeError:
        return asyncio.run(func(*args, **kwargs))


def run_job(job: dict) -> tuple:
    """
    Execute a single cron job.

    Returns:
        Tuple of (success, full_output_doc, final_response, error_message)
    """
    job_id = job["id"]
    job_name = job["name"]

    logger.info("Running job '%s' (ID: %s)", job_name, job_id)

    try:
        prompt = _build_job_prompt(job)

        # 构建输出文档
        output = f"""# Cron Job: {job_name}

**Job ID:** {job_id}
**Run Time:** {_now().strftime('%Y-%m-%d %H:%M:%S')}
**Schedule:** {job.get('schedule_display', 'N/A')}

## Prompt

{prompt}

## Response

(Processing...)

"""

        # TODO: 实际运行 agent
        # 目前暂时模拟成功执行
        final_response = f"[模拟] Cron job '{job_name}' executed at {_now().strftime('%Y-%m-%d %H:%M:%S')}"
        logged_response = final_response

        output = f"""# Cron Job: {job_name}

**Job ID:** {job_id}
**Run Time:** {_now().strftime('%Y-%m-%d %H:%M:%S')}
**Schedule:** {job.get('schedule_display', 'N/A')}

## Prompt

{prompt}

## Response

{logged_response}
"""

        logger.info("Job '%s' completed successfully", job_name)
        return True, output, final_response, None

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.exception("Job '%s' failed: %s", job_name, error_msg)

        output = f"""# Cron Job: {job_name} (FAILED)

**Job ID:** {job_id}
**Run Time:** {_now().strftime('%Y-%m-%d %H:%M:%S')}
**Schedule:** {job.get('schedule_display', 'N/A')}

## Error

```
{error_msg}
```
"""
        return False, output, "", error_msg


def tick(verbose: bool = True) -> int:
    """
    Check and run all due jobs.

    Uses a file lock so only one tick runs at a time.

    Returns:
        Number of jobs executed (0 if another tick is already running)
    """
    CRON_DIR.mkdir(parents=True, exist_ok=True)

    lock_fd = None
    try:
        lock_fd = open(_LOCK_FILE, "w")
        if fcntl:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError):
        if verbose:
            logger.debug("Tick skipped — another instance holds the lock")
        if lock_fd is not None:
            lock_fd.close()
        return 0

    try:
        due_jobs = get_due_jobs()

        if verbose and not due_jobs:
            logger.info("%s - No jobs due", _now().strftime('%H:%M:%S'))
            return 0

        if verbose:
            logger.info("%s - %s job(s) due", _now().strftime('%H:%M:%S'), len(due_jobs))

        executed = 0
        for job in due_jobs:
            try:
                advance_next_run(job["id"])

                success, output, final_response, error = run_job(job)

                output_file = save_job_output(job["id"], output)
                if verbose:
                    logger.info("Output saved to: %s", output_file)

                deliver_content = final_response if success else f"Cron job '{job.get('name', job['id'])}' failed:\n{error}"
                should_deliver = bool(deliver_content)

                if should_deliver and success and SILENT_MARKER in deliver_content.strip().upper():
                    logger.info("Job '%s': agent returned SILENT — skipping delivery", job["id"])
                    should_deliver = False

                delivery_error = None
                if should_deliver:
                    try:
                        delivery_error = _deliver_result(job, deliver_content)
                    except Exception as de:
                        delivery_error = str(de)
                        logger.error("Delivery failed for job %s: %s", job["id"], de)

                if success and not final_response:
                    success = False
                    error = "Agent completed but produced empty response"

                mark_job_run(job["id"], success, error, delivery_error=delivery_error)
                executed += 1

            except Exception as e:
                logger.error("Error processing job %s: %s", job['id'], e)
                mark_job_run(job["id"], False, str(e))

        return executed

    finally:
        if fcntl:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


# CLI entry point
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    tick(verbose=True)