"""交付证据门禁 / 执行声明校验 (2026-07-12 从 agent.py 抽出)。

这些是零依赖的纯函数, 供 self-built (agent.py) 和 LangChain
(langchain_agent.py) 两条推理路径共用, 用来:
  - 检测模型"假完成"(声称执行却无真实工具证据)
  - 判断工具返回是否为错误 + 错误分类
  - 从写文件/截图工具结果里提取可预览产物

抽出前它们散在 agent.py 顶部, 造成该文件臃肿且职责混杂;
抽出后 agent.py 仍 re-export 这些名字, 保持既有 import 兼容。
"""
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from urllib.parse import quote, urlparse
import json
import re


def _has_execution_claim(text: str) -> bool:
    """检测模型是否声称已经执行了外部动作。"""
    if not text:
        return False
    patterns = [
        # 已完成时 - 声称已经做了
        r"已(?:经)?(?:调用|执行|运行|打开|访问|搜索|读取|写入|修改|创建|删除|安装|启动|截图|导航)",
        r"我(?:已|已经)(?:调用|执行|运行|打开|访问|搜索|读取|写入|修改|创建|删除|安装|启动|截图|导航)",
        r"(?:调用|执行|运行|打开|访问|搜索|读取|写入|修改|创建|删除|安装|启动|截图|导航).{0,12}(?:完成|成功|完毕)",
        r"(?:successfully|have|has)\s+(?:called|executed|run|opened|visited|searched|read|wrote|modified|created|deleted|installed|started)",
        # 将来时 - 声称要做什么（但实际还没做）
        r"让我(?:看看|搜索|查找|分析|执行|运行|检查|查看)",
        r"让我来(?:看看|搜索|查找|分析|执行|运行|检查|查看)",
        r"我来(?:看看|搜索|查找|分析|执行|运行|检查|查看)",
        r"我(?:将|要)去?(?:看看|搜索|查找|分析|执行|运行|检查|查看)",
        r"我(?:将|要)(?:调用|执行|运行|打开|访问|搜索|读取|写入|修改|创建|删除|安装|启动)",
        r"(?:let me|i'll|i am going to|i will)\s+(?:search|find|look|check|execute|run|read|write|open|visit|analyze)",
        r"(?:现在|马上|这就去)(?:搜索|查找|分析|执行|运行|检查)",
    ]
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _is_error_result(result: str) -> bool:
    """检测工具返回结果是否为错误。"""
    if result.startswith("工具执行失败"):
        return True
    lower = result.lower()
    if "超时" in result or "timeout" in lower or "timed out" in lower:
        return True
    if "不在允许列表中" in result or "请使用 browser 工具" in result:
        return True
    if "executable doesn't exist" in lower or "please run the following command to download new browsers" in lower:
        return True
    if "error" in lower or "错误" in result or "失败" in result:
        return True
    return False


def _classify_error_type(error_msg: str) -> str:
    """将错误信息分类为语义类型。"""
    msg = error_msg.lower()
    if "permission" in msg or "权限" in error_msg or "denied" in msg or "拒绝" in error_msg:
        return "permission"
    elif "executable doesn't exist" in msg or "playwright install" in msg or "浏览器未安装" in error_msg:
        return "environment_missing"
    elif "timeout" in msg or "超时" in error_msg or "timed out" in msg:
        return "timeout"
    elif "invalid" in msg or "参数" in error_msg or "格式" in error_msg:
        return "invalid_args"
    return "generic"


def _validate_execution_claim(text: str, tools_used: list, commands_executed: list) -> Tuple[bool, Optional[str]]:
    """最终输出硬校验：声明执行必须有本轮工具证据。"""
    if _has_execution_claim(text) and not tools_used and not commands_executed:
        return False, (
            "你刚才的回复声称已经执行了任务，但本轮没有任何真实工具调用记录。"
            "禁止把计划、意图或文字描述当成执行结果。"
            "下一轮必须二选一：实际调用合适的工具；或明确说明尚未执行。"
        )
    return True, None


def _required_tool_evidence(message: str) -> Dict[str, str]:
    """从用户请求推断最低交付证据。

    目标不是做复杂意图识别，而是拦住高风险长任务的常见假完成：
    只读文件/输出方案，却没有实际写文件或运行验证。
    """
    text = (message or "").casefold()
    requirements: Dict[str, str] = {}

    # 写文件要求: 必须同时有"写操作词"和"文件相关词"才触发, 纯计划/文案不触发。
    # 代码/网页/前端 → 触发文件证据; 纯计划/文案/分析不触发。
    write_terms = ("写", "新增", "创建", "修改", "生成", "写入", "写文件", "删除", "实现", "build", "构建", "编译")
    # 代码相关: 网页/组件/程序/API/工具 → 需要文件证据
    # 文案相关: 计划/文案/邮件/文章/方案 → 不需要文件证据
    code_keywords = ("文件", "代码", "项目", "前端", "页面", "网页", "组件", "程序", "html",
                     "app", "目录", "src", "workspace", "计算器", "博客", "爬虫", "api",
                     "接口", "后端", "数据库", "脚本", "函数", "类", "模块", "demo",
                     "css", "js", "tsx", "vue", "readme", "文档", "config", "json",
                     "工具", "功能")
    if any(t in text for t in write_terms) and any(k in text for k in code_keywords):
        requirements["write"] = "缺少真实写文件证据：必须调用 workspace_write、write_file 或 patch。"

    build_terms = ("npm run build", "构建", "build", "验证", "编译")
    if any(term in text for term in build_terms):
        requirements["build"] = "缺少构建/验证证据：必须调用 workspace_terminal 或 terminal 运行 npm run build 或等价命令。"

    return requirements


def _missing_tool_evidence(requirements: Dict[str, str], tools_used: list, commands_executed: list) -> List[str]:
    """根据本轮工具记录判断还缺哪些交付证据。"""
    missing: List[str] = []
    if "write" in requirements and not any(t in ("workspace_write", "write_file", "patch") for t in tools_used):
        missing.append(requirements["write"])
    if "build" in requirements:
        has_build = any(
            "npm run build" in (cmd or "").casefold()
            or "npm build" in (cmd or "").casefold()
            or "pnpm build" in (cmd or "").casefold()
            or "yarn build" in (cmd or "").casefold()
            for cmd in commands_executed
        )
        if not has_build:
            missing.append(requirements["build"])
    return missing


def _artifact_preview_from_write_result(result: str) -> Optional[Dict[str, str]]:
    """从工具返回文本或 JSON 里提取可预览产物。"""
    if not result:
        return None

    # 优先支持结构化 payload：{"artifact_previews": [...]} / {"preview_url": ...}
    try:
        parsed = json.loads(result)
        if isinstance(parsed, dict):
            previews = parsed.get("artifact_previews") or []
            if isinstance(previews, list) and previews:
                first = previews[0]
                if isinstance(first, dict) and first.get("path"):
                    return {
                        "path": str(first.get("path")),
                        "name": str(first.get("name") or Path(str(first.get("path"))).name),
                        "kind": str(first.get("kind") or "web"),
                        "preview_url": str(first.get("preview_url") or first.get("open_url") or ""),
                        "open_url": str(first.get("open_url") or first.get("preview_url") or ""),
                    }
            if parsed.get("path") and parsed.get("kind") in {"web", "image"}:
                path = str(parsed["path"])
                kind = str(parsed["kind"])
                encoded = quote(path, safe="")
                return {
                    "path": path,
                    "name": str(parsed.get("name") or Path(path).name),
                    "kind": kind,
                    "preview_url": str(parsed.get("preview_url") or (f"/api/files/serve?path={encoded}" if kind == "image" else f"/api/files/preview?path={encoded}")),
                    "open_url": str(parsed.get("open_url") or f"/api/files/serve?path={encoded}"),
                }

            remote_url = str(parsed.get("url") or "").strip()
            if remote_url.startswith(("http://", "https://")):
                parsed_url = urlparse(remote_url)
                suffix = Path(parsed_url.path).suffix.lower()
                if suffix in {".html", ".htm", ".xhtml"}:
                    return {
                        "path": remote_url,
                        "name": Path(parsed_url.path).name or "网页",
                        "kind": "web",
                        "preview_url": remote_url,
                        "open_url": remote_url,
                    }
            return None
    except Exception:
        pass

    match = re.search(r"已写入\s+(.+?)（", result)
    if match:
        path = match.group(1).strip()
    else:
        label_match = re.search(
            r"(?:截图|文件)?已保存(?:到)?[：:]\s*(.+)$|saved(?:\s+to)?[：:]\s*(.+)$",
            result,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if label_match:
            path = (label_match.group(1) or label_match.group(2) or "").strip()
        else:
            fallback = re.search(
                r"(/[^ \t\r\n)）\]]+\.(?:html?|svg|png|jpe?g|gif|webp))",
                result,
                flags=re.IGNORECASE,
            )
            if not fallback:
                return None
            path = fallback.group(1).strip()
    path = path.strip().strip("'\"`")
    absolute_match = re.search(r"^absolute_path=(.+)$", result, flags=re.MULTILINE)
    serve_path = absolute_match.group(1).strip() if absolute_match else path
    suffix = Path(path).suffix.lower()
    if suffix in {".html", ".htm"}:
        kind = "web"
    elif suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        kind = "image"
    else:
        return None
    encoded = quote(serve_path, safe="")
    return {
        "path": serve_path,
        "name": Path(path).name,
        "kind": kind,
        "preview_url": f"/api/files/serve?path={encoded}" if kind == "image" else f"/api/files/preview?path={encoded}",
        "open_url": f"/api/files/serve?path={encoded}",
    }
