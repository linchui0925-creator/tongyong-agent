"""
DomainIntegrator - 领域认知整合与执行调度中枢

认知层: 读取 domains/ 下所有 .md 文件，编译为提示词上下文
执行层: 管理各领域 executor，提供统一调用入口

遵循 Hermes 平文件模式：内容即指令。
"""

import os
import re
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path

from app.domains.base import BaseDomainExecutor

logger = logging.getLogger(__name__)

# 当前文件所在目录（domains/ 包目录）
_PACKAGE_DIR = Path(__file__).parent


class DomainIntegrator:
    """领域认知整合器 + 执行调度中枢"""

    def __init__(self, base_dir: Optional[Path] = None, profile_id: str = "default"):
        self.base_dir = base_dir or _PACKAGE_DIR
        self.profile_id = profile_id  # 当前profile_id，用于身份检测
        # domain_key → { file_key → content }（认知层）
        self._entries: Dict[str, Dict[str, str]] = {}
        # domain_key → [trigger_keywords]
        self._domain_keywords: Dict[str, List[str]] = {}
        # domain_key → BaseDomainExecutor（执行层）
        self._executors: Dict[str, BaseDomainExecutor] = {}
        self._load_all()

    # ── 加载认知层（.md 文件） ───────────────────

    def _load_all(self):
        """遍历所有子目录，读取 .md 文件"""
        self._entries = {}
        self._domain_keywords = {}

        for domain_dir in sorted(self.base_dir.iterdir()):
            if not domain_dir.is_dir() or domain_dir.name.startswith("_"):
                continue
            if domain_dir.name == "__pycache__":
                continue

            domain_key = domain_dir.name
            files = sorted(domain_dir.glob("*.md"))
            if not files:
                continue

            self._entries[domain_key] = {}
            for md_file in files:
                file_key = md_file.stem
                content = self._read_file(md_file)
                if content:
                    self._entries[domain_key][file_key] = content

            self._domain_keywords[domain_key] = self._extract_keywords(domain_key, files)

        logger.info(
            f"DomainIntegrator 加载完成: {len(self._entries)} 个领域, "
            f"{sum(len(v) for v in self._entries.values())} 个文件, "
            f"{len(self._executors)} 个执行器"
        )

    def _read_file(self, path: Path) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            logger.warning(f"读取领域文件失败: {path}, {e}")
            return ""

    def _extract_keywords(self, domain_key: str, files: List[Path]) -> List[str]:
        builtin_keywords = {
            "identity": ["你是谁", "你叫什么", "你的名字", "who are you", "什么身份", "tongyong", "tong yong"],
            "cli": ["运行", "执行", "命令", "shell", "terminal", "终端", "cli"],
            "personality": ["人格", "性格", "设定", "画像", "偏好", "风格", "语气", "记住我", "你是谁"],
            "memory": ["记忆", "梦境", "反思", "忘记", "还记得", "长期", "nudge", "回忆"],
            "cron": ["定时", "调度", "计划", "周期", "每天", "cron", "scheduler", "定期"],
            "tools": ["工具", "执行", "创建", "删除", "修改", "分析", "查看",
                      "浏览器", "网页", "截图", "screenshot", "页面", "网址",
                      "skill", "技能", "工作流", "流程", "上传 skill"],
        }
        keywords = builtin_keywords.get(domain_key, [domain_key])
        for f in files:
            stem = f.stem.lower()
            if stem == "commands":
                keywords.extend(["命令", "command"])
            elif stem == "git":
                keywords.extend(["git", "提交", "commit", "push", "分支"])
            elif stem == "python":
                keywords.extend(["python", "pytest", "pip", "测试"])
            elif stem == "node":
                keywords.extend(["node", "npm", "前端"])
            elif stem == "docker":
                keywords.extend(["docker", "容器", "container"])
            elif stem == "system":
                keywords.extend(["文件", "目录", "进程", "系统"])
        return list(set(keywords))

    # ── 执行层管理 ─────────────────────────────

    def register_executor(self, executor: BaseDomainExecutor):
        """注册领域执行器"""
        self._executors[executor.name] = executor
        logger.info(f"注册执行器: {executor.name}")

    def get_executor(self, domain: str) -> Optional[BaseDomainExecutor]:
        """获取指定领域的执行器"""
        return self._executors.get(domain)

    def get_all_executors(self) -> Dict[str, BaseDomainExecutor]:
        """获取所有已注册的执行器"""
        return dict(self._executors)

    async def execute_domain(self, domain: str, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """通过执行器执行领域动作"""
        executor = self._executors.get(domain)
        if not executor:
            return {"success": False, "error": f"领域 '{domain}' 没有注册执行器"}
        return await executor.execute(action, params)

    # ── 认知层 API ──────────────────────────────

    def set_profile_id(self, profile_id: str):
        """切换当前profile_id（影响身份检测）"""
        self.profile_id = profile_id

    def get_all(self) -> str:
        """返回所有领域编译后的完整提示词"""
        sections = []
        for domain_key in sorted(self._entries.keys()):
            domain_section = self._format_domain(domain_key)
            if domain_section:
                sections.append(domain_section)
        return "\n\n".join(sections)

    def get_filtered(self, message: str) -> str:
        """根据用户消息返回相关领域的提示词"""
        message_lower = message.lower()
        matched_domains = set()
        matched_domains.add("identity")
        for domain_key, keywords in self._domain_keywords.items():
            if any(kw in message_lower for kw in keywords):
                matched_domains.add(domain_key)
        return self.get_by_domains(list(matched_domains))

    def get_by_domains(self, domain_keys: List[str]) -> str:
        """返回指定领域的提示词"""
        sections = []
        for key in domain_keys:
            domain_section = self._format_domain(key)
            if domain_section:
                sections.append(domain_section)
        return "\n\n".join(sections)

    def get_domain_keys(self) -> List[str]:
        return sorted(self._entries.keys())

    def get_file_keys(self, domain_key: str) -> List[str]:
        return sorted(self._entries.get(domain_key, {}).keys())

    def refresh(self):
        self._load_all()

    def _user_has_custom_identity(self) -> bool:
        """检测用户是否配置了自定义身份（MEMORY.md有实质内容）"""
        try:
            from app.hermes.memory_file import MemoryFileManager
            memory_mgr = MemoryFileManager(profile_id=self.profile_id)
            memory_content = memory_mgr.read_memory()
            user_content = memory_mgr.read_user()
            # 有实质内容（超过默认提示长度）则认为用户有自定义设定
            return len(memory_content.strip()) > 100 or len(user_content.strip()) > 50
        except Exception:
            return False

    def _format_domain(self, domain_key: str) -> str:
        """格式化领域内容，identity域有条件跳过"""
        # identity域：如果用户已配置自定义身份，则跳过默认identity.md
        if domain_key == "identity" and self._user_has_custom_identity():
            logger.debug("用户已配置自定义身份，跳过默认identity.md")
            return ""
        files = self._entries.get(domain_key)
        if not files:
            return ""
        parts = []
        for file_key in sorted(files.keys()):
            content = files[file_key]
            if content:
                parts.append(content)
        return "\n\n".join(parts)


# ── 全局单例 ─────────────────────────────────

_integrator_instance: Optional[DomainIntegrator] = None


def get_integrator() -> DomainIntegrator:
    """获取 DomainIntegrator 单例（注册默认执行器）"""
    global _integrator_instance
    if _integrator_instance is None:
        _integrator_instance = DomainIntegrator()
        # 注册默认执行器
        _register_default_executors(_integrator_instance)
    return _integrator_instance


def _register_default_executors(integrator: DomainIntegrator):
    """注册所有领域执行器"""
    try:
        from app.domains.cli import CLIExecutor
        integrator.register_executor(CLIExecutor(working_dir="."))
    except Exception as e:
        logger.warning(f"注册 CLI 执行器失败: {e}")

    try:
        from app.domains.tools import ToolsExecutor
        integrator.register_executor(ToolsExecutor())
    except Exception as e:
        logger.warning(f"注册 Tools 执行器失败: {e}")

    try:
        from app.domains.memory import MemoryExecutor
        integrator.register_executor(MemoryExecutor())
    except Exception as e:
        logger.warning(f"注册 Memory 执行器失败: {e}")

    try:
        from app.domains.cron import CronExecutor
        integrator.register_executor(CronExecutor())
    except Exception as e:
        logger.warning(f"注册 Cron 执行器失败: {e}")

    try:
        from app.domains.identity import IdentityManager
        integrator.register_executor(IdentityManager())
    except Exception as e:
        logger.warning(f"注册 Identity 执行器失败: {e}")

    logger.info(f"已注册 {len(integrator.get_all_executors())} 个领域执行器")
