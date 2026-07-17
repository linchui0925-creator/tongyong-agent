"""
SkillFileManager - 技能平文件管理器 (Hermes 风格)

管理 data/hermes/skills/ 下的 SKILL.md 技能目录
格式兼容 agentskills.io 标准:
- YAML frontmatter (name, description, version, platforms)
- Markdown body (Steps, Pitfalls, References)
- 渐进披露: list → view → references
"""

import os
import re
import yaml
import logging
import shutil
from typing import List, Dict, Optional, Tuple
from app.paths import data_path

logger = logging.getLogger(__name__)

# 安全扫描模式
_SKILL_THREAT_PATTERNS = [
    r"rm\s+-rf\s+/",
    r":(){ :\|:& };:",  # fork bomb
    r"sudo\s+",
    r"chmod\s+-R\s+777",
    r"curl\s+.*\|\s*(bash|sh)\b",
    r"wget\s+.*-O-\s+.*\|\s*(bash|sh)\b",
    r"base64\s+.*decode.*\|.*(bash|sh)\b",
    r"eval\s*\(",
    r"exec\s*\(",
    r"system\s*\(",
    r"DROP\s+(TABLE|DATABASE)",
    r"git\s+push\s+--force",
    r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
    r"you\s+are\s+(not|no\s+longer)",
]


class SkillFileManager:
    """技能平文件管理器"""

    def __init__(self, base_dir: str = data_path("hermes")):
        self.skills_dir = os.path.join(base_dir, "skills")
        os.makedirs(self.skills_dir, exist_ok=True)
        logger.info(f"SkillFileManager 初始化: {self.skills_dir}")

    # ── 渐进披露 Level 0: 列表 ─────────────────

    def list_skills(self) -> List[Dict]:
        """返回所有技能摘要 (名称 + 一行描述)"""
        skills = []
        for category_dir in self._get_category_dirs():
            category = os.path.basename(category_dir)
            for skill_dir in self._get_skill_dirs(category_dir):
                name = os.path.basename(skill_dir)
                meta = self._read_frontmatter(os.path.join(skill_dir, "SKILL.md"))
                skills.append({
                    "name": name,
                    "category": category,
                    "description": meta.get("description", ""),
                    "version": meta.get("version", "1.0.0"),
                })
        return skills

    # ── 渐进披露 Level 1: 技能详情 ─────────────

    def view_skill(self, name: str) -> Optional[Dict]:
        """返回完整 SKILL.md 内容"""
        path = self._find_skill_path(name)
        if not path:
            return None
        skill_path = os.path.join(path, "SKILL.md")
        if not os.path.exists(skill_path):
            return None

        content = self._read_text(skill_path)
        meta, body = self._parse_frontmatter(content)
        return {
            "name": name,
            "category": os.path.basename(os.path.dirname(path)),
            "metadata": meta,
            "body": body,
            "has_references": os.path.isdir(os.path.join(path, "references")),
            "has_templates": os.path.isdir(os.path.join(path, "templates")),
        }

    # ── 渐进披露 Level 2: 引用文件 ─────────────

    def view_file(self, skill_name: str, file_path: str) -> Optional[str]:
        """返回技能目录下的指定文件内容"""
        skill_dir = self._find_skill_path(skill_name)
        if not skill_dir:
            return None
        full_path = os.path.join(skill_dir, file_path)
        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            return None
        return self._read_text(full_path)

    # ── CRUD ──────────────────────────────────

    def create_skill(
        self,
        name: str,
        description: str,
        steps: List[str],
        pitfalls: Optional[List[str]] = None,
        category: str = "general",
        platforms: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """创建新技能"""
        safe_name = self._sanitize_name(name)
        category_dir = os.path.join(self.skills_dir, category)
        skill_dir = os.path.join(category_dir, safe_name)

        if os.path.exists(skill_dir):
            return False, f"技能 '{name}' 已存在"

        os.makedirs(skill_dir, exist_ok=True)

        frontmatter = {
            "name": name,
            "description": description,
            "version": "1.0.0",
            "platforms": platforms or [],
        }

        body_parts = ["## Steps"]
        for i, step in enumerate(steps, 1):
            body_parts.append(f"{i}. {step}")

        if pitfalls:
            body_parts.append("\n## Pitfalls")
            for p in pitfalls:
                body_parts.append(f"- {p}")

        skill_content = self._build_skill_file(frontmatter, "\n".join(body_parts))

        # 安全扫描
        threat = self._security_scan(skill_content)
        if threat:
            shutil.rmtree(skill_dir)
            return False, f"技能内容包含安全风险: {threat}"

        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(skill_content)

        logger.info(f"技能已创建: {category}/{safe_name}")
        return True, ""

    def patch_skill(self, name: str, old: str, new: str) -> Tuple[bool, str]:
        """局部替换技能内容 (模糊匹配，Token 高效)"""
        path = self._find_skill_path(name)
        if not path:
            return False, f"技能 '{name}' 未找到"

        skill_path = os.path.join(path, "SKILL.md")
        content = self._read_text(skill_path)

        # 备份用于回滚
        backup = content

        if old not in content:
            # 尝试模糊匹配 (行级)
            matched = False
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if old.strip() in line:
                    lines[i] = line.replace(old.strip(), new.strip())
                    matched = True
                    break
            if not matched:
                return False, f"未找到匹配内容: {old[:50]}"
            new_content = "\n".join(lines)
        else:
            new_content = content.replace(old, new, 1)

        threat = self._security_scan(new_content)
        if threat:
            return False, f"修改后内容包含安全风险: {threat}"

        # 原子写入
        try:
            with open(skill_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            logger.info(f"技能已修补: {name}")
            return True, ""
        except OSError as e:
            # 回滚
            with open(skill_path, "w", encoding="utf-8") as f:
                f.write(backup)
            logger.error(f"技能修补失败，已回滚: {e}")
            return False, f"写入失败，已回滚: {e}"

    def edit_skill(self, name: str, content: str) -> Tuple[bool, str]:
        """整体重写技能"""
        path = self._find_skill_path(name)
        if not path:
            return False, f"技能 '{name}' 未找到"

        skill_path = os.path.join(path, "SKILL.md")
        backup = self._read_text(skill_path)

        threat = self._security_scan(content)
        if threat:
            return False, f"内容包含安全风险: {threat}"

        try:
            with open(skill_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"技能已重写: {name}")
            return True, ""
        except OSError as e:
            with open(skill_path, "w", encoding="utf-8") as f:
                f.write(backup)
            return False, f"写入失败，已回滚: {e}"

    def delete_skill(self, name: str) -> Tuple[bool, str]:
        """删除技能"""
        path = self._find_skill_path(name)
        if not path:
            return False, f"技能 '{name}' 未找到"
        shutil.rmtree(path)
        logger.info(f"技能已删除: {name}")
        return True, ""

    def add_reference(self, skill_name: str, filename: str, content: str) -> Tuple[bool, str]:
        """添加引用文件"""
        path = self._find_skill_path(skill_name)
        if not path:
            return False, f"技能 '{skill_name}' 未找到"
        ref_dir = os.path.join(path, "references")
        os.makedirs(ref_dir, exist_ok=True)
        try:
            with open(os.path.join(ref_dir, filename), "w", encoding="utf-8") as f:
                f.write(content)
            return True, ""
        except OSError as e:
            return False, f"写入失败: {e}"

    # ── 内部辅助 ──────────────────────────────

    def _get_category_dirs(self) -> List[str]:
        if not os.path.isdir(self.skills_dir):
            return []
        return [
            os.path.join(self.skills_dir, d)
            for d in sorted(os.listdir(self.skills_dir))
            if os.path.isdir(os.path.join(self.skills_dir, d))
        ]

    def _get_skill_dirs(self, category_dir: str) -> List[str]:
        return [
            os.path.join(category_dir, d)
            for d in sorted(os.listdir(category_dir))
            if os.path.isdir(os.path.join(category_dir, d))
        ]

    def _find_skill_path(self, name: str) -> Optional[str]:
        """跨目录查找技能"""
        for category_dir in self._get_category_dirs():
            skill_dir = os.path.join(category_dir, name)
            if os.path.isdir(skill_dir):
                return skill_dir
            # 同名搜索
            for candidate_dir in self._get_skill_dirs(category_dir):
                if os.path.basename(candidate_dir) == self._sanitize_name(name):
                    return candidate_dir
        return None

    def _read_frontmatter(self, path: str) -> Dict:
        if not os.path.exists(path):
            return {}
        content = self._read_text(path)
        meta, _ = self._parse_frontmatter(content)
        return meta

    def _parse_frontmatter(self, content: str) -> Tuple[Dict, str]:
        """解析 YAML frontmatter，返回 (metadata, body)"""
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    meta = {}
                return meta, parts[2].strip()
        return {}, content.strip()

    def _build_skill_file(self, frontmatter: Dict, body: str) -> str:
        frontmatter_str = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False)
        return f"---\n{frontmatter_str}---\n\n{body}\n"

    def _security_scan(self, content: str) -> Optional[str]:
        content_lower = content.lower()
        for pattern in _SKILL_THREAT_PATTERNS:
            if re.search(pattern, content_lower):
                return f"匹配危险模式: {pattern}"
        return None

    def _sanitize_name(self, name: str) -> str:
        # 保留 Unicode 字符（中文、日文等），只替换危险字符
        return re.sub(r"[^a-zA-Z0-9_\-一-鿿]", "-", name.lower()).strip("-") or "unnamed"

    def _read_text(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def get_stats(self) -> Dict:
        skills = self.list_skills()
        return {
            "total_skills": len(skills),
            "categories": len(set(s["category"] for s in skills)),
            "skills": skills,
        }
