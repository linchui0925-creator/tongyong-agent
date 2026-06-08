"""
TaskWorkspace — Per-Task 工作区

每个任务有独立的文件系统工作区，用于：
- 存放任务的输入/输出文件（代码、数据等），不再塞进消息 content
- 工具调用在此目录内读写，LLM 不直接接收文件内容
- 各 Agent 共享同一任务的工作区，实现真正的协作

目录结构:
  workspace/
    t_{task_id}/           # 每个任务独立的根目录
      input/               # 任务输入（需求文档、上游产出等）
      output/              # 任务产出（代码、测试、报告等）
      context/             # 中间上下文（LLM 提示词草稿等）
      artifacts/           # 最终交付物（可直接下载）
      logs/                # 执行日志
      meta.json            # 工作区元数据
"""

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 路径约定
# ══════════════════════════════════════════════════════════

SUBDIRS = ("input", "output", "context", "artifacts", "logs")


# ══════════════════════════════════════════════════════════
# WorkspaceMeta — 工作区元数据
# ══════════════════════════════════════════════════════════

@dataclass
class WorkspaceMeta:
    """工作区元数据"""
    task_id:      str
    created_at:   str = field(default_factory=lambda: datetime.now().isoformat())
    created_by:   str = ""
    updated_at:   str = field(default_factory=lambda: datetime.now().isoformat())
    parent_id:    str = ""                    # 父任务 ID（用于嵌套分解）
    root_task_id: str = ""                    # 根任务 ID（整条流水线的根）
    tags:         List[str] = field(default_factory=list)
    extra:        Dict[str, Any] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "WorkspaceMeta":
        return cls(**json.loads(path.read_text(encoding="utf-8")))

    def to_dict(self) -> dict:
        return {
            "task_id":      self.task_id,
            "created_at":   self.created_at,
            "created_by":   self.created_by,
            "updated_at":   self.updated_at,
            "parent_id":    self.parent_id,
            "root_task_id": self.root_task_id,
            "tags":         self.tags,
            "extra":        self.extra,
        }


# ══════════════════════════════════════════════════════════
# TaskWorkspace — per-task 工作区
# ══════════════════════════════════════════════════════════

class TaskWorkspace:
    """
    Per-Task 工作区。
    
    每个任务对应一个独立的 TaskWorkspace 实例。
    
    使用示例:
    
        ws = TaskWorkspace("t_001", root="/tmp/workspace")
        ws.init()  # 创建目录结构
        
        # 写文件（不再塞消息 content）
        ws.write("input", "requirement.md", "# 用户需求...")
        ws.write("output", "solution.py", "print('hello')")
        
        # 工具可直接读写文件
        result = await tool_mgr.execute("terminal", {"command": f"python {ws.path('output/solution.py')}"})
        
        # 读文件用于 LLM 上下文
        code = ws.read("output/solution.py")
        
        # 写日志
        ws.log("Coder", "已完成函数 foo 的编写")
        
        # 清理
        ws.destroy()
    """

    def __init__(
        self,
        task_id: str,
        root: Optional[str] = None,
        created_by: str = "",
        parent_id: str = "",
        root_task_id: str = "",
    ):
        """
        Args:
            task_id:   任务 ID（全局唯一）
            root:      工作区根目录（默认 ~/.tongyong/workspaces/）
            created_by: 创建者 Agent 名称
            parent_id: 父任务 ID（用于嵌套分解）
            root_task_id: 根任务 ID
        """
        self.task_id = task_id
        self._root = Path(root or os.path.expanduser("~/.tongyong/workspaces"))
        self._created_by = created_by
        self._parent_id = parent_id
        self._root_task_id = root_task_id or task_id
        self._meta: Optional[WorkspaceMeta] = None

    # ── 目录管理 ─────────────────────────────────────────

    @property
    def base(self) -> Path:
        """任务根目录，如 /tmp/workspace/t_001"""
        return self._root / f"t_{self.task_id}"

    def path(self, sub: str, filename: str = "") -> Path:
        """
        构造子目录下的文件路径。
        
        Args:
            sub:      子目录名（input/output/context/artifacts/logs）
            filename: 文件名
        
        Returns:
            完整路径
        """
        p = self.base / sub
        if filename:
            p = p / filename
        return p

    def init(self) -> "TaskWorkspace":
        """创建工作区目录结构"""
        if self.base.exists():
            logger.debug(f"[Workspace] 工作区已存在: {self.base}")
            return self

        for sub in SUBDIRS:
            (self.base / sub).mkdir(parents=True, exist_ok=True)

        # 写 meta.json
        self._meta = WorkspaceMeta(
            task_id=self.task_id,
            created_by=self._created_by,
            parent_id=self._parent_id,
            root_task_id=self._root_task_id,
        )
        self._meta.save(self.base / "meta.json")

        logger.info(f"[Workspace] 工作区已创建: {self.base}")
        return self

    def destroy(self, keep_logs: bool = False) -> None:
        """
        删除工作区。
        
        Args:
            keep_logs: 是否保留 logs 目录
        """
        if not self.base.exists():
            return

        if keep_logs:
            shutil.move(str(self.base), str(self.base.parent / f".archived_{self.task_id}"))
        else:
            shutil.rmtree(self.base)
        logger.info(f"[Workspace] 工作区已销毁: {self.base}")

    # ── 文件读写 ─────────────────────────────────────────

    def write(self, sub: str, filename: str, content: str, encoding: str = "utf-8") -> Path:
        """
        写入文件。
        
        Args:
            sub:      子目录
            filename: 文件名
            content: 文件内容
        
        Returns:
            写入的完整路径
        """
        p = self.path(sub, filename)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        self._touch_updated()
        return p

    def read(self, sub: str, filename: str, encoding: str = "utf-8") -> str:
        """读取文件内容"""
        p = self.path(sub, filename)
        return p.read_text(encoding=encoding)

    def exists(self, sub: str, filename: str = "") -> bool:
        """检查文件是否存在"""
        p = self.path(sub, filename) if filename else self.base / sub
        return p.exists()

    def list_files(self, sub: str, pattern: str = "*") -> List[Path]:
        """列出子目录下匹配 pattern 的文件"""
        p = self.base / sub
        if not p.exists():
            return []
        return sorted(p.glob(pattern))

    def append(self, sub: str, filename: str, content: str, encoding: str = "utf-8") -> None:
        """追加内容到文件末尾"""
        p = self.path(sub, filename)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding=encoding) as f:
            f.write(content)
        self._touch_updated()

    # ── 日志 ─────────────────────────────────────────

    def log(self, actor: str, message: str, level: str = "INFO") -> None:
        """
        写入执行日志。
        
        Args:
            actor:   执行者名称
            message: 日志内容
            level:   日志级别（INFO/WARN/ERROR）
        """
        ts = datetime.now().isoformat()
        entry = f"[{ts}] [{level}] [{actor}] {message}\n"
        self.append("logs", "execution.log", entry)

    def get_log(self) -> str:
        """读取完整执行日志"""
        try:
            return self.read("logs", "execution.log")
        except FileNotFoundError:
            return ""

    # ── 元数据 ─────────────────────────────────────────

    @property
    def meta(self) -> WorkspaceMeta:
        """获取元数据（懒加载）"""
        if self._meta is None:
            p = self.base / "meta.json"
            if p.exists():
                self._meta = WorkspaceMeta.load(p)
            else:
                self._meta = WorkspaceMeta(task_id=self.task_id)
        return self._meta

    def _touch_updated(self) -> None:
        """更新 updated_at 时间戳"""
        self.meta.updated_at = datetime.now().isoformat()
        self.meta.save(self.base / "meta.json")

    # ── 摘要信息 ─────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """返回工作区摘要（用于调试和展示）"""
        summary = {
            "task_id":      self.task_id,
            "base":         str(self.base),
            "subdirs":      {sub: len(list((self.base / sub).glob("*"))) for sub in SUBDIRS if (self.base / sub).exists()},
            "meta":         self.meta.to_dict(),
        }
        return summary

    def __repr__(self) -> str:
        return f"<TaskWorkspace task={self.task_id} base={self.base}>"


# ══════════════════════════════════════════════════════════
# WorkspaceManager — 全局工作区管理器
# ══════════════════════════════════════════════════════════

class WorkspaceManager:
    """
    全局工作区管理器。
    
    管理所有任务的工作区实例，提供统一的获取和生命周期管理。
    """

    def __init__(self, root: Optional[str] = None):
        self._root = Path(root or os.path.expanduser("~/.tongyong/workspaces"))
        self._workspaces: Dict[str, TaskWorkspace] = {}
        self._root.mkdir(parents=True, exist_ok=True)

    def get(self, task_id: str, create: bool = True) -> Optional[TaskWorkspace]:
        """
        获取某任务的工作区。
        
        Args:
            task_id: 任务 ID
            create:  不存在时是否创建
        
        Returns:
            TaskWorkspace 或 None
        """
        if task_id in self._workspaces:
            return self._workspaces[task_id]

        ws = TaskWorkspace(task_id, root=str(self._root))
        if not ws.base.exists():
            if not create:
                return None
            ws.init()

        self._workspaces[task_id] = ws
        return ws

    def destroy(self, task_id: str, **kwargs) -> None:
        """销毁某任务的工作区"""
        ws = self._workspaces.pop(task_id, None)
        if ws:
            ws.destroy(**kwargs)

    def list_tasks(self) -> List[str]:
        """列出所有已创建工作区的任务 ID"""
        return list(self._workspaces.keys())


# ── 全局快捷函数 ─────────────────────────────────────────

_manager: Optional[WorkspaceManager] = None

def get_workspace_manager() -> WorkspaceManager:
    global _manager
    if _manager is None:
        _manager = WorkspaceManager()
    return _manager


def get_workspace(task_id: str, create: bool = True) -> Optional[TaskWorkspace]:
    return get_workspace_manager().get(task_id, create=create)