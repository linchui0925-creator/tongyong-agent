"""
MemoryFileManager - 平文件记忆管理器 (Hermes 风格)

管理 MEMORY.md (环境事实/项目约定) 和 USER.md (用户偏好/风格)
核心设计:
- 严格字符限制迫使 Agent 主动压缩信息
- 冻结快照机制保护 prefix caching
- 安全扫描防注入
"""

import os
import re
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from app.paths import data_path

logger = logging.getLogger(__name__)

# 安全扫描：防 prompt injection 和敏感信息泄露
_MEMORY_THREAT_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"do\s+not\s+(tell|reveal|share|disclose)",
    r"forget\s+(all\s+)?(previous|prior)\s+instructions",
    r"you\s+are\s+(not|no\s+longer)",
    r"your\s+(new|real)\s+(instruction|prompt|goal)",
    r"system\s+prompt",
    r"(curl|wget)\s+.*(\$TOKEN|\$KEY|\$SECRET|env\b)",
    r"base64\s+.*decode",
    r"export\s+[A-Z_]+=",
]


class MemoryFileManager:
    """平文件记忆管理器"""

    MEMORY_LIMIT = 2200    # MEMORY.md 字符上限
    USER_LIMIT = 1375      # USER.md 字符上限

    def __init__(self, base_dir: str = data_path("hermes"), profile_id: str = "default"):
        # 支持per-profile目录
        if profile_id and profile_id != "default":
            self.base_dir = f"{base_dir}/profiles/{profile_id}"
        else:
            self.base_dir = base_dir
        self.profile_id = profile_id
        self.memory_path = os.path.join(self.base_dir, "MEMORY.md")
        self.user_path = os.path.join(self.base_dir, "USER.md")
        self._snapshot_memory: Optional[str] = None
        self._snapshot_user: Optional[str] = None
        self._frozen = False

        os.makedirs(self.base_dir, exist_ok=True)
        self._ensure_files()
        logger.info(f"MemoryFileManager 初始化: {self.base_dir}")

    def load_memory(self) -> str:
        """加载记忆内容（供网关使用）"""
        return self._read_file(self.memory_path)

    def _ensure_files(self):
        """确保记忆文件存在"""
        for path in [self.memory_path, self.user_path]:
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("")

    # ── 快照管理 ──────────────────────────────────

    def freeze_snapshot(self):
        """创建冻结快照，会话期间不变"""
        self._snapshot_memory = self._read_file(self.memory_path)
        self._snapshot_user = self._read_file(self.user_path)
        self._frozen = True
        logger.debug("记忆冻结快照已创建")

    def get_snapshot_memory(self) -> str:
        """获取 MEMORY.md 内容（优先返回冻结快照）"""
        if self._frozen and self._snapshot_memory is not None:
            return self._snapshot_memory
        return self._read_file(self.memory_path)

    def get_snapshot_user(self) -> str:
        """获取 USER.md 内容（优先返回冻结快照）"""
        if self._frozen and self._snapshot_user is not None:
            return self._snapshot_user
        return self._read_file(self.user_path)

    def unfreeze(self):
        """解冻，下次读取将走磁盘"""
        self._frozen = False
        self._snapshot_memory = None
        self._snapshot_user = None

    # ── 读 ──────────────────────────────────────

    def read_memory(self) -> str:
        return self._read_file(self.memory_path)

    def read_user(self) -> str:
        return self._read_file(self.user_path)

    def _read_file(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    # ── 写（只写磁盘，不更新快照） ─────────────

    def write_memory(self, content: str) -> Tuple[bool, str]:
        """写入 MEMORY.md，返回 (成功, 消息)"""
        return self._write_file(self.memory_path, content, self.MEMORY_LIMIT, "MEMORY.md")

    def write_user(self, content: str) -> Tuple[bool, str]:
        """写入 USER.md，返回 (成功, 消息)"""
        return self._write_file(self.user_path, content, self.USER_LIMIT, "USER.md")

    def _write_file(self, path: str, content: str, limit: int, label: str) -> Tuple[bool, str]:
        # 安全扫描
        threat = self._security_scan(content)
        if threat:
            logger.warning(f"{label} 安全扫描未通过: {threat}")
            return False, f"内容包含安全风险: {threat}"

        # 字符限制检查
        if len(content) > limit:
            current = self._read_file(path)
            # 返回错误并附上现有内容，迫使 Agent 压缩
            return False, (
                f"内容超限 ({len(content)} > {limit})。"
                f"请使用 replace 或 remove 精简后再试。\n"
                f"当前内容:\n{current}"
            )

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"{label} 已写入 ({len(content)} chars)")
            return True, ""
        except OSError as e:
            logger.error(f"{label} 写入失败: {e}")
            return False, f"写入失败: {e}"

    # ── 条目级操作 ─────────────────────────────

    def add_entry(self, target: str, entry: str) -> Tuple[bool, str]:
        """添加一条记忆条目 (以 - 开头的列表项)"""
        content = self._read_file(self.memory_path) if target == "memory" else self._read_file(self.user_path)
        path = self.memory_path if target == "memory" else self.user_path
        limit = self.MEMORY_LIMIT if target == "memory" else self.USER_LIMIT
        label = "MEMORY.md" if target == "memory" else "USER.md"

        formatted = f"- {entry.strip()}\n"
        new_content = content + formatted if content else formatted

        # 安全扫描
        threat = self._security_scan(new_content)
        if threat:
            return False, f"内容包含安全风险: {threat}"

        if len(new_content) > limit:
            return False, (
                f"添加后将超限 ({len(new_content)} > {limit})。"
                f"请先使用 replace 或 remove 腾出空间。"
            )

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        logger.info(f"{label} 添加条目: {entry[:50]}")
        return True, ""

    def replace_entry(self, target: str, old_pattern: str, new_entry: str) -> Tuple[bool, str]:
        """替换匹配的条目（整行替换）"""
        path = self.memory_path if target == "memory" else self.user_path
        limit = self.MEMORY_LIMIT if target == "memory" else self.USER_LIMIT
        label = "MEMORY.md" if target == "memory" else "USER.md"
        content = self._read_file(path)

        if old_pattern not in content:
            return False, f"未找到匹配的内容: {old_pattern}"

        lines = content.split("\n")
        new_lines = []
        found = False
        for line in lines:
            if old_pattern in line and not found:
                new_lines.append(f"- {new_entry.strip()}")
                found = True
            else:
                new_lines.append(line)

        if not found:
            return False, f"未找到匹配的行: {old_pattern}"
        new_content = "\n".join(new_lines)

        threat = self._security_scan(new_content)
        if threat:
            return False, f"替换后内容包含安全风险: {threat}"

        if len(new_content) > limit:
            return False, f"替换后超限 ({len(new_content)} > {limit})"

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        logger.info(f"{label} 替换条目: {old_pattern[:30]} -> {new_entry[:30]}")
        return True, ""

    def remove_entry(self, target: str, pattern: str) -> Tuple[bool, str]:
        """删除匹配的条目（整行删除）"""
        path = self.memory_path if target == "memory" else self.user_path
        label = "MEMORY.md" if target == "memory" else "USER.md"
        content = self._read_file(path)

        if pattern not in content:
            return False, f"未找到匹配的内容: {pattern}"

        lines = content.split("\n")
        new_lines = [line for line in lines if pattern not in line]
        if len(new_lines) == len(lines):
            return False, f"未找到匹配的行: {pattern}"
        new_content = "\n".join(new_lines)

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        logger.info(f"{label} 删除条目: {pattern[:30]}")
        return True, ""

    def list_entries(self, target: str) -> List[str]:
        """列出所有条目（自动过滤空条目）"""
        content = self._read_file(self.memory_path if target == "memory" else self.user_path)
        return [
            line.lstrip("- ")
            for line in content.split("\n")
            if line.strip().startswith("- ") and line.lstrip("- ").strip()
        ]

    # ── 安全扫描 ──────────────────────────────

    def _security_scan(self, content: str) -> Optional[str]:
        """检查内容是否包含安全威胁（大小写不敏感）"""
        for pattern in _MEMORY_THREAT_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return f"匹配危险模式: {pattern}"
        return None

    # ── 统计 ──────────────────────────────────

    def get_stats(self) -> Dict:
        return {
            "memory_chars": len(self._read_file(self.memory_path)),
            "memory_limit": self.MEMORY_LIMIT,
            "user_chars": len(self._read_file(self.user_path)),
            "user_limit": self.USER_LIMIT,
            "frozen": self._frozen,
            "memory_entries": len(self.list_entries("memory")),
            "user_entries": len(self.list_entries("user")),
        }
