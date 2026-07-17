"""
REM Backfill Lane - 历史日记回填

OpenClaw 风格的"回填车道":
- 读取历史 data/dreams/diary/YYYY-MM-DD.md 日记文件
- 提取结构化输出，写入 DREAMS.md (人类可审查面)
- 或暂存到短期存储 (机器排名面)
- 两条独立车道，互不干扰
"""

import os
import re
import json
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from app.paths import data_path

logger = logging.getLogger(__name__)


class REMBackfill:
    """REM 回填处理器"""

    def __init__(self, dreams_dir: str = data_path("dreams")):
        self.dreams_dir = dreams_dir
        self.diary_dir = os.path.join(dreams_dir, "diary")
        self.dreams_path = os.path.join(dreams_dir, "DREAMS.md")
        self.short_term_dir = os.path.join(dreams_dir, ".dreams", "short-term")

        os.makedirs(self.diary_dir, exist_ok=True)
        os.makedirs(self.short_term_dir, exist_ok=True)

    # ── Grounded Diary: 预览 ─────────────────

    def preview_diary(self, path: Optional[str] = None, days: int = 7) -> List[Dict]:
        """预览日记文件中的结构化候选"""
        if path:
            files = [path] if os.path.isfile(path) else []
        else:
            files = self._get_recent_diary_files(days)

        candidates = []
        for file_path in files:
            content = self._read_text(file_path)
            entries = self._extract_diary_entries(content)
            for entry in entries:
                entry["source_file"] = file_path
            candidates.extend(entries)

        return candidates

    # ── Grounded Backfill → DREAMS.md ────────

    def backfill_to_dreams(self, path: Optional[str] = None, days: int = 7) -> Tuple[int, str]:
        """将历史日记回填到 DREAMS.md (人类可审查面)"""
        candidates = self.preview_diary(path, days)

        if not candidates:
            return 0, "没有找到可回填的日记条目"

        dreams_content = self._read_text(self.dreams_path)
        header = f"\n## REM Backfill - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        entries_text = []
        for c in candidates:
            entries_text.append(f"- **{c.get('topic', '未命名')}** (来自 {os.path.basename(c['source_file'])})\n")
            if c.get("content"):
                entries_text.append(f"  {c['content']}\n")

        backfill_block = header + "".join(entries_text) + "\n"

        with open(self.dreams_path, "a", encoding="utf-8") as f:
            f.write(backfill_block)

        logger.info(f"REM 回填: {len(candidates)} 条写入 DREAMS.md")
        return len(candidates), ""

    # ── Stage Short-Term: 暂存到机器排名面 ───

    def stage_short_term(self, path: Optional[str] = None, days: int = 7) -> Tuple[int, str]:
        """将候选暂存到短期存储 (机器排名面)"""
        candidates = self.preview_diary(path, days)

        if not candidates:
            return 0, "没有找到可暂存的日记条目"

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(self.short_term_dir, f"backfill_{timestamp}.json")

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(candidates, f, ensure_ascii=False, indent=2)

        logger.info(f"REM 暂存: {len(candidates)} 条 -> {output_file}")
        return len(candidates), output_file

    # ── Rollback ─────────────────────────────

    def rollback_dreams(self, marker: str = "## REM Backfill") -> int:
        """回滚 DREAMS.md 中最近的回填条目"""
        content = self._read_text(self.dreams_path)

        # 找到最后一个回填标记并移除
        parts = content.rsplit(f"\n{marker}", 1)
        if len(parts) < 2:
            return 0

        # 计算被删除部分中的列表项数量
        removed_content = parts[1]
        entry_count = removed_content.count(f"\n- **")

        restored = parts[0].rstrip() + "\n"
        with open(self.dreams_path, "w", encoding="utf-8") as f:
            f.write(restored)

        logger.info(f"REM 回滚: 移除了 {entry_count} 条回填条目")
        return entry_count

    def rollback_short_term(self, filename: Optional[str] = None) -> int:
        """回滚短期存储"""
        if filename:
            path = os.path.join(self.short_term_dir, filename)
            if os.path.exists(path):
                os.remove(path)
                return 1
            return 0

        count = 0
        for f in sorted(os.listdir(self.short_term_dir)):
            if f.startswith("backfill_"):
                os.remove(os.path.join(self.short_term_dir, f))
                count += 1

        logger.info(f"REM 回滚短期存储: {count} 文件")
        return count

    # ── 内部辅助 ─────────────────────────────

    def _get_recent_diary_files(self, days: int) -> List[str]:
        files = []
        for i in range(days):
            date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            path = os.path.join(self.diary_dir, f"{date_str}.md")
            if os.path.exists(path):
                files.append(path)
        return sorted(files)

    def _extract_diary_entries(self, content: str) -> List[Dict]:
        """从日记 Markdown 中提取结构化条目"""
        entries = []

        # 按 h2/h3 分割
        sections = re.split(r"\n(?=#{1,3}\s)", content)

        for section in sections:
            if not section.strip():
                continue

            # 提取标题
            title_match = re.match(r"#{1,3}\s+(.+)", section)
            topic = title_match.group(1).strip() if title_match else "未分类"

            # 提取列表项作为内容
            items = re.findall(r"^- (.+)", section, re.MULTILINE)

            # 提取代码块
            code_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", section, re.DOTALL)

            entries.append({
                "topic": topic,
                "content": "\n".join(items) if items else section.strip()[:200],
                "items": items,
                "code_blocks": code_blocks,
                "raw_length": len(section),
            })

        return entries

    def write_diary_entry(self, session_summary: str, date_str: Optional[str] = None):
        """写入当日日记"""
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        path = os.path.join(self.diary_dir, f"{date_str}.md")

        timestamp = datetime.now().strftime("%H:%M")
        entry = f"\n### {timestamp}\n\n{session_summary}\n"

        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)

    def _read_text(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def get_stats(self) -> Dict:
        diary_files = []
        if os.path.isdir(self.diary_dir):
            diary_files = [f for f in os.listdir(self.diary_dir) if f.endswith(".md")]

        short_term_files = []
        if os.path.isdir(self.short_term_dir):
            short_term_files = [f for f in os.listdir(self.short_term_dir)]

        dreams_exists = os.path.exists(self.dreams_path)

        return {
            "diary_files": len(diary_files),
            "short_term_files": len(short_term_files),
            "dreams_file_exists": dreams_exists,
            "diary_dates": sorted(diary_files)[-7:] if diary_files else [],
        }
