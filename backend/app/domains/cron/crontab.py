"""
Cron CLI - 命令行界面

提供 cron 命令的 CLI 接口：
- cron list: 列出所有任务
- cron create: 创建新任务
- cron pause/resume/remove: 管理任务
- cron tick: 手动触发调度
"""

import argparse
import json
import sys
from typing import Optional

from app.domains.cron import jobs as cron_jobs
from app.domains.cron.scheduler import tick


def format_job(job: dict) -> str:
    """格式化任务显示"""
    repeat = job.get("repeat", {})
    repeat_times = repeat.get("times")
    repeat_completed = repeat.get("completed", 0)

    if repeat_times is None:
        repeat_display = "forever"
    elif repeat_times == 1:
        repeat_display = "once"
    else:
        repeat_display = f"{repeat_completed}/{repeat_times}"

    status = "enabled" if job.get("enabled", True) else "paused"
    next_run = job.get("next_run_at", "N/A")
    last_status = job.get("last_status", "never")

    return (
        f"  [{job['id']}] {job.get('name', 'unnamed')}\n"
        f"      Schedule: {job.get('schedule_display', 'N/A')} ({status})\n"
        f"      Repeat: {repeat_display}\n"
        f"      Next run: {next_run}\n"
        f"      Last status: {last_status}"
    )


def cmd_list(args) -> int:
    """列出所有任务"""
    jobs = cron_jobs.list_jobs(include_disabled=args.include_disabled)

    if not jobs:
        print("No cron jobs found.")
        return 0

    print(f"Cron Jobs ({len(jobs)}):\n")
    for job in jobs:
        print(format_job(job))
        print()

    return 0


def cmd_create(args) -> int:
    """创建新任务"""
    if not args.schedule:
        print("Error: --schedule is required", file=sys.stderr)
        return 1

    if not args.prompt and not args.skills:
        print("Error: --prompt or --skills is required", file=sys.stderr)
        return 1

    skills = None
    if args.skills:
        skills = [s.strip() for s in args.skills.split(",")]

    try:
        job = cron_jobs.create_job(
            prompt=args.prompt or "",
            schedule=args.schedule,
            name=args.name,
            repeat=args.repeat,
            deliver=args.deliver,
            skills=skills,
        )

        print(f"Cron job created: {job['id']}")
        print(f"  Name: {job['name']}")
        print(f"  Schedule: {job['schedule_display']}")
        print(f"  Next run: {job['next_run_at']}")

        return 0

    except Exception as e:
        print(f"Error creating cron job: {e}", file=sys.stderr)
        return 1


def cmd_pause(args) -> int:
    """暂停任务"""
    if not args.job_id:
        print("Error: --job-id is required", file=sys.stderr)
        return 1

    try:
        job = cron_jobs.pause_job(args.job_id, reason=args.reason)
        if not job:
            print(f"Error: Job '{args.job_id}' not found", file=sys.stderr)
            return 1

        print(f"Job paused: {job['name']}")
        return 0

    except Exception as e:
        print(f"Error pausing job: {e}", file=sys.stderr)
        return 1


def cmd_resume(args) -> int:
    """恢复任务"""
    if not args.job_id:
        print("Error: --job-id is required", file=sys.stderr)
        return 1

    try:
        job = cron_jobs.resume_job(args.job_id)
        if not job:
            print(f"Error: Job '{args.job_id}' not found", file=sys.stderr)
            return 1

        print(f"Job resumed: {job['name']}")
        print(f"  Next run: {job['next_run_at']}")
        return 0

    except Exception as e:
        print(f"Error resuming job: {e}", file=sys.stderr)
        return 1


def cmd_remove(args) -> int:
    """删除任务"""
    if not args.job_id:
        print("Error: --job-id is required", file=sys.stderr)
        return 1

    try:
        job = cron_jobs.get_job(args.job_id)
        if not job:
            print(f"Error: Job '{args.job_id}' not found", file=sys.stderr)
            return 1

        removed = cron_jobs.remove_job(args.job_id)
        if removed:
            print(f"Job removed: {job['name']}")
            return 0
        print(f"Error: Failed to remove job", file=sys.stderr)
        return 1

    except Exception as e:
        print(f"Error removing job: {e}", file=sys.stderr)
        return 1


def cmd_trigger(args) -> int:
    """手动触发任务"""
    if not args.job_id:
        print("Error: --job-id is required", file=sys.stderr)
        return 1

    try:
        job = cron_jobs.trigger_job(args.job_id)
        if not job:
            print(f"Error: Job '{args.job_id}' not found", file=sys.stderr)
            return 1

        print(f"Job triggered: {job['name']}")
        return 0

    except Exception as e:
        print(f"Error triggering job: {e}", file=sys.stderr)
        return 1


def cmd_tick(args) -> int:
    """手动触发调度"""
    try:
        executed = tick(verbose=True)
        print(f"Executed {executed} job(s)")
        return 0
    except Exception as e:
        print(f"Error running tick: {e}", file=sys.stderr)
        return 1


def cmd_info(args) -> int:
    """显示任务详情"""
    if not args.job_id:
        print("Error: --job-id is required", file=sys.stderr)
        return 1

    try:
        job = cron_jobs.get_job(args.job_id)
        if not job:
            print(f"Error: Job '{args.job_id}' not found", file=sys.stderr)
            return 1

        print(json.dumps(job, indent=2, default=str))
        return 0

    except Exception as e:
        print(f"Error getting job info: {e}", file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(description="Cron Job Management")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # list
    list_parser = subparsers.add_parser("list", help="List all cron jobs")
    list_parser.add_argument("--include-disabled", action="store_true",
                              help="Include disabled jobs")

    # create
    create_parser = subparsers.add_parser("create", help="Create a new cron job")
    create_parser.add_argument("--prompt", "-p", help="Prompt to execute")
    create_parser.add_argument("--schedule", "-s", required=True, help="Schedule (e.g., '30m', 'every 2h', '0 9 * * *')")
    create_parser.add_argument("--name", "-n", help="Job name")
    create_parser.add_argument("--repeat", "-r", type=int, help="Repeat count")
    create_parser.add_argument("--deliver", "-d", default="local", help="Delivery target")
    create_parser.add_argument("--skills", help="Comma-separated skill names")

    # pause
    pause_parser = subparsers.add_parser("pause", help="Pause a cron job")
    pause_parser.add_argument("--job-id", "-j", required=True, help="Job ID")
    pause_parser.add_argument("--reason", "-r", help="Pause reason")

    # resume
    resume_parser = subparsers.add_parser("resume", help="Resume a paused job")
    resume_parser.add_argument("--job-id", "-j", required=True, help="Job ID")

    # remove
    remove_parser = subparsers.add_parser("remove", help="Remove a cron job")
    remove_parser.add_argument("--job-id", "-j", required=True, help="Job ID")

    # trigger
    trigger_parser = subparsers.add_parser("trigger", help="Trigger a job immediately")
    trigger_parser.add_argument("--job-id", "-j", required=True, help="Job ID")

    # tick
    subparsers.add_parser("tick", help="Manually trigger scheduler tick")

    # info
    info_parser = subparsers.add_parser("info", help="Show job details")
    info_parser.add_argument("--job-id", "-j", required=True, help="Job ID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "list": cmd_list,
        "create": cmd_create,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "remove": cmd_remove,
        "trigger": cmd_trigger,
        "tick": cmd_tick,
        "info": cmd_info,
    }

    if args.command in commands:
        return commands[args.command](args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())