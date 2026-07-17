"""Skill 上传解析工具 (2026-07-12 从 app/api/skills.py 抽出)。

把上传的 zip / md / txt / json / yaml 内容解析成统一 skill dict,
并从自由文本里启发式提取 steps / triggers / keywords / name。

抽出前这些函数约 235 行, 塞在 skills 路由文件底部, 与 HTTP 层职责混杂。
纯函数, 无 FastAPI 依赖, 可独立测试与复用。
"""
import os
import re
import json
import zipfile
import tempfile
from typing import Any, Dict, List, Optional

import yaml

# 上传允许的文件扩展名 (路由与解析共用的单一事实源)
ALLOWED_EXTENSIONS = {
    ".zip", ".md", ".txt", ".json", ".yaml", ".yml",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
    ".sh", ".bash", ".zsh",
    ".html", ".css", ".sql",
}


# ── 解析函数 ──────────────────────────────────

def _parse_uploaded_file(content_bytes: bytes, ext: str, override_name: Optional[str] = None) -> Dict:
    """从上传内容中提取 skill 信息"""
    result = {
        "name": override_name,  # 用户显式提供的 name 优先
        "description": "",
        "steps": [],
        "pitfalls": None,
        "triggers": [],
        "platforms": [],
        "body_text": "",
        "references": {},
        "warnings": [],
    }

    if ext == ".zip":
        result.update(_parse_zip(content_bytes))
    elif ext in (".json",):
        result.update(_parse_json(content_bytes))
    elif ext in (".yaml", ".yml"):
        result.update(_parse_yaml(content_bytes))
    else:
        result.update(_parse_text(content_bytes.decode("utf-8", errors="replace")))
        # _parse_text 返回新 dict，update 会覆盖 name，所以保留用户提供的 override_name
        if override_name:
            result["name"] = override_name
    # 始终保留用户显式提供的 name
    if override_name:
        result["name"] = override_name

    # 自动提取 trigger
    if result["body_text"] and not result["triggers"]:
        result["triggers"] = _extract_triggers(result["body_text"])

    return result


def _parse_zip(content_bytes: bytes) -> Dict:
    result = {"warnings": []}
    refs = {}
    body_texts = []

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "upload.zip")
            with open(zip_path, "wb") as f:
                f.write(content_bytes)

            with zipfile.ZipFile(zip_path, "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    fname = os.path.basename(info.filename)
                    if fname.startswith(".") or fname.startswith("_"):
                        continue
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in ALLOWED_EXTENSIONS:
                        continue

                    data = zf.read(info.filename).decode("utf-8", errors="replace")

                    # 优先读取 README/SKILL 等说明文件
                    base_lower = os.path.basename(info.filename).lower()
                    if base_lower in ("readme.md", "readme.txt", "skill.md", "skill.txt",
                                      "readme", "skill"):
                        body_texts.append(data)
                        # 用户显式提供的 name 优先，否则从文件名推断
                        if not result.get("name"):
                            result["name"] = _derive_name_from_content(data)

                    # 收集引用文件
                    if ext in (".md", ".txt", ".py", ".js", ".ts", ".sh", ".json", ".yaml"):
                        refs[fname] = data[:2000]  # 限制大小

        result["references"] = refs
        if body_texts:
            result["body_text"] = "\n\n".join(body_texts)
    except Exception as e:
        result["warnings"].append(f"ZIP 解压失败: {e}，将作为普通文本处理")
        result["body_text"] = content_bytes.decode("utf-8", errors="replace")

    # 从 body_text 提取 steps/description
    if result.get("body_text"):
        result.update(_parse_text(result["body_text"]))

    return result


def _parse_json(content_bytes: bytes) -> Dict:
    try:
        data = json.loads(content_bytes.decode("utf-8", errors="replace"))
        desc = data.get("description", "")
        body_text = data.get("content") or data.get("body") or desc or content_bytes.decode("utf-8", errors="replace")
        return {
            "name": data.get("name"),
            "description": desc,
            "steps": data.get("steps", data.get("execution_steps", [])),
            "pitfalls": data.get("pitfalls", data.get("warnings")),
            "triggers": data.get("triggers", data.get("trigger_conditions", [])),
            "platforms": data.get("platforms", []),
            "body_text": body_text,
        }
    except Exception as e:
        return {"warnings": [f"JSON 解析失败: {e}"], "body_text": content_bytes.decode("utf-8", errors="replace")}


def _parse_yaml(content_bytes: bytes) -> Dict:
    try:
        data = yaml.safe_load(content_bytes.decode("utf-8", errors="replace"))
        if isinstance(data, dict):
            desc = data.get("description", "")
            body_text = data.get("content") or data.get("body") or desc or content_bytes.decode("utf-8", errors="replace")
            return {
                "name": data.get("name"),
                "description": desc,
                "steps": data.get("steps", data.get("execution_steps", [])),
                "pitfalls": data.get("pitfalls", data.get("warnings")),
                "triggers": data.get("triggers", data.get("trigger_conditions", [])),
                "platforms": data.get("platforms", []),
                "body_text": body_text,
            }
        return {"body_text": content_bytes.decode("utf-8", errors="replace")}
    except Exception as e:
        return {"warnings": [f"YAML 解析失败: {e}"], "body_text": content_bytes.decode("utf-8", errors="replace")}


def _parse_text(text: str) -> Dict:
    result = {}
    result["body_text"] = text

    # 尝试从 frontmatter 提取
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                # name 以调用方传入的 override_name 为准，不覆盖
                if not result.get("name"):
                    result["name"] = meta.get("name")
                result["description"] = meta.get("description", "")
                result["triggers"] = meta.get("triggers", [])
                result["platforms"] = meta.get("platforms", [])
            except Exception:
                pass

    # 从 body 中提取 steps
    lines = text.split("\n")
    steps = []
    for line in lines:
        stripped = line.strip()
        # 匹配 1. 2. 或 - 或 numbered list
        m = re.match(r"^\d+[.)]\s+(.+)", stripped)
        if m:
            steps.append(m.group(1).strip())
        elif stripped.startswith("- ") and len(steps) > 0:
            steps.append(stripped[2:].strip())

    if steps:
        result["steps"] = steps

    # 尝试提取 description（取第一段非空文字）
    if not result.get("description"):
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and len(stripped) > 10:
                result["description"] = stripped[:200]
                break

    return result


def _extract_steps_from_text(text: str) -> List[str]:
    lines = text.split("\n")
    steps = []
    for line in lines:
        stripped = line.strip()
        m = re.match(r"^\d+[.)]\s+(.+)", stripped)
        if m:
            steps.append(m.group(1).strip())
        elif re.match(r"^[-*]\s+(.+)", stripped) and len(steps) > 0:
            steps.append(re.sub(r"^[-*]\s+", "", stripped).strip())
    return steps[:20]  # 最多 20 步


def _extract_triggers(text: str) -> List[str]:
    """从文本中提取可能的 trigger 关键词"""
    triggers = set()
    # 匹配代码块外的关键词模式
    # 提取带引号的关键词或加粗文本
    patterns = [
        r'\*\*([^*]+)\*\*',
        r'`([^`]+)`',
        r'触发[:：]\s*([^\n]+)',
        r'触发条件[:：]\s*([^\n]+)',
        r'当.*时.*执行',
        r'(?:use|apply|run|execute)\s+([a-zA-Z\s]+)',
    ]
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            word = m.group(1 or 0).strip().lower()
            if word and 2 < len(word) < 50:
                triggers.add(word[:80])
    return sorted(list(triggers))[:10]


def _extract_keywords(text: str) -> List[str]:
    """从描述中提取关键词"""
    # 去除 markdown 符号
    clean = re.sub(r'[#*`>\[\]]', ' ', text.lower())
    words = re.findall(r'[a-zA-Z]{4,}', clean)
    # 统计词频，取 top 10
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    return sorted(freq.keys(), key=lambda x: freq[x], reverse=True)[:10]


def _derive_name_from_content(text: str) -> Optional[str]:
    """从内容中推断 skill 名称"""
    lines = text.split("\n")
    for line in lines:
        stripped = line.strip()
        # # SkillName 格式
        m = re.match(r"^#+\s*(.+)", stripped)
        if m:
            name = m.group(1).strip().split("\n")[0].strip()
            name = re.sub(r"[^a-zA-Z0-9\s\-]", "", name)[:60]
            if name:
                return name
        # "name: xxx" 格式
        m2 = re.match(r"^\s*name:\s*(.+)", stripped, re.IGNORECASE)
        if m2:
            name = m2.group(1).strip()[:60]
            if name:
                return name
    return None
