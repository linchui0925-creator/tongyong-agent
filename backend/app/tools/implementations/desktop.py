"""
desktop - 桌面控制工具（macOS）

通过 AppleScript 和系统命令控制 macOS 桌面：
- 打开/切换 App
- 鼠标点击/移动
- 键盘输入
- 截图

CDP/WebSocket 远程模式：browser 工具已有 CDP 支持，desktop 工具通过相同通道代理。
"""

import logging
import subprocess
import os
import shutil
from typing import Optional

from app.tools.registry import registry

logger = logging.getLogger(__name__)

# ── macOS AppleScript 执行 ─────────────────────────────────


def _run_osascript(script: str) -> str:
    """执行 AppleScript，返回 stdout 或报错"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return f"AppleScript 错误: {result.stderr.strip()}"
        return result.stdout.strip()
    except FileNotFoundError:
        return "osascript 不可用（非 macOS）"
    except Exception as e:
        return f"执行失败: {e}"


def _check_darwin() -> bool:
    return subprocess.run(["sw_vers"], capture_output=True).returncode == 0


# ── Desktop 工具入口 ──────────────────────────────────────


async def desktop_execute(
    action: str,
    app: str = "",
    x: int = 0,
    y: int = 0,
    text: str = "",
    key: str = "",
    path: str = "/tmp/desktop_screenshot.png",
    duration: float = 0.5,
) -> str:
    """
    desktop 工具入口。

    action:
      launch      打开 App（app 参数传入 App 名称）
      click       点击坐标（x, y）
      move        移动鼠标（x, y）
      type        输入文本（text）
      keypress    按键（key，如 Enter/Tab/Escape/ArrowUp/ArrowDown）
      screenshot  截图保存（path）
      right_click 右键点击（x, y）
      scroll      滚动（x, y, duration 滚动时长）

    示例：
      desktop(action="launch", app="Safari")
      desktop(action="click", x=500, y=300)
      desktop(action="type", text="hello")
      desktop(action="keypress", key="Enter")
      desktop(action="screenshot", path="/tmp/screen.png")
    """
    if not _check_darwin():
        return "desktop 工具仅支持 macOS"

    try:
        if action == "launch":
            if not app:
                return "launch 需要 app 参数"
            script = f'tell application "{app}" to activate'
            result = _run_osascript(script)
            if "错误" in result:
                # 尝试用 open 命令
                result2 = subprocess.run(["open", "-a", app], capture_output=True, text=True)
                if result2.returncode == 0:
                    return f"已打开: {app}"
                return f"无法打开 {app}: {result2.stderr or result}"
            return f"已激活: {app}"

        elif action == "focus":
            if not app:
                return "focus 需要 app 参数"
            # First check if app is running
            check_script = f'''
tell application "System Events"
    if exists (process "{app}") then
        return "running"
    else
        return "not_running"
    end if
end tell
'''
            check_result = _run_osascript(check_script)
            if check_result == "not_running":
                return f"{app} 未运行，请先使用 launch 打开"
            # Bring to front using AppleScript with retry for minimized windows
            script = f'''
tell application "{app}"
    activate
    set wasMinimized to false
    tell process "{app}"
        if miniified of window 1 then
            set wasMinimized to true
        end if
    end tell
    if wasMinimized then
        set miniaturized of window 1 to false
    end if
end tell
'''
            result = _run_osascript(script)
            if "错误" in result:
                # Fallback: simple activate
                script2 = f'tell application "{app}" to activate'
                result = _run_osascript(script2)
            return f"已聚焦: {app}"

        elif action == "click":
            script = f'''
tell application "System Events"
    set mousePos to {{0, 0}}
    set cursorPos to current application's (do shell script "echo $CG_MIN_CURSOR_COORD_DEPRECATED") as list
end tell
'''
            # 使用 cliclick 工具（Homebrew install cliclick）
            cliclick_path = shutil.which("cliclick")
            if cliclick_path:
                result = subprocess.run(
                    ["cliclick", f"c:{x},{y}"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    return f"已点击: ({x}, {y})"
                return f"点击失败: {result.stderr}"
            else:
                # 不用 cliclick，用 Python + PyAutoGUI
                try:
                    import pyautogui
                    pyautogui.click(x, y)
                    return f"已点击: ({x}, {y})"
                except Exception as e:
                    return f"点击需要安装 cliclick 或 pyautogui: {e}"

        elif action == "right_click":
            cliclick_path = shutil.which("cliclick")
            if cliclick_path:
                result = subprocess.run(
                    ["cliclick", f"c:{x},{y}", "rc"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    return f"已右键点击: ({x}, {y})"
                return f"右键点击失败: {result.stderr}"
            return "右键点击需要 cliclick（brew install cliclick）"

        elif action == "move":
            cliclick_path = shutil.which("cliclick")
            if cliclick_path:
                result = subprocess.run(
                    ["cliclick", f"m:{x},{y}"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    return f"已移动到: ({x}, {y})"
                return f"移动失败: {result.stderr}"
            return "移动鼠标需要 cliclick（brew install cliclick）"

        elif action == "type":
            if not text:
                return "type 需要 text 参数"
            # 用 AppleScript 输入文本
            escaped = text.replace('"', '\\"')
            script = f'''
tell application "System Events"
    keystroke "{escaped}"
end tell
'''
            result = _run_osascript(script)
            if "错误" in result:
                return f"输入失败: {result}"
            return f"已输入: {text[:20]}..."

        elif action == "keypress":
            if not key:
                return "keypress 需要 key 参数"
            # 按键映射
            key_map = {
                "Enter": "return",
                "Tab": "tab",
                "Escape": "escape",
                "ArrowUp": "up arrow",
                "ArrowDown": "down arrow",
                "ArrowLeft": "left arrow",
                "ArrowRight": "right arrow",
                "Home": "home",
                "End": "end",
                "PageUp": "page up",
                "PageDown": "page down",
                "Backspace": "delete",
                "Delete": "forward delete",
            }
            key_code = key_map.get(key, key.lower())
            script = f'''
tell application "System Events"
    keystroke "{key_code}"
end tell
'''
            result = _run_osascript(script)
            if "错误" in result:
                return f"按键失败: {result}"
            return f"已按键: {key}"

        elif action == "screenshot":
            result = subprocess.run(
                ["screencapture", "-x", path],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return f"截图已保存: {os.path.abspath(path)}"
            return f"截图失败: {result.stderr}"

        elif action == "scroll":
            # 向下滚动 duration 秒
            cliclick_path = shutil.which("cliclick")
            if cliclick_path:
                clicks = int(duration * 20)  # 约 20 次/秒
                for _ in range(clicks):
                    subprocess.Popen(["cliclick", "wd:-100"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"已滚动: {clicks} 次"
            return "滚动需要 cliclick"

        elif action == "get_front_app":
            script = '''
tell application "System Events"
    set frontApp to first process whose frontmost is true
    return name of frontApp
end tell
'''
            result = _run_osascript(script)
            return f"当前前台 App: {result}"

        elif action == "list_open_apps":
            script = '''
tell application "System Events"
    set appList to name of every process
    return appList
end tell
'''
            result = _run_osascript(script)
            apps = [a.strip() for a in result.split(", ")]
            return f"运行的 App（{len(apps)} 个）: {', '.join(apps[:20])}..."

        else:
            return f"未知操作: {action}，支持的: launch/focus/click/move/type/keypress/screenshot/right_click/scroll/get_front_app/list_open_apps"

    except Exception as e:
        logger.error(f"desktop 工具失败: {e}", exc_info=True)
        return f"desktop 执行失败: {e}"


# ── Schema ────────────────────────────────────────────────


DESKTOP_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "description": "操作类型",
            "enum": ["launch", "focus", "click", "move", "right_click", "type", "keypress", "screenshot", "scroll", "get_front_app", "list_open_apps"],
        },
        "app": {
            "type": "string",
            "description": "launch 时要打开的 App 名称（如 Safari、Chrome、WeChat）",
        },
        "x": {
            "type": "integer",
            "description": "click/move/right_click/scroll 时的 X 坐标",
        },
        "y": {
            "type": "integer",
            "description": "click/move/right_click/scroll 时的 Y 坐标",
        },
        "text": {
            "type": "string",
            "description": "type 时要输入的文本",
        },
        "key": {
            "type": "string",
            "description": "keypress 时的按键（Enter/Tab/Escape/ArrowUp/ArrowDown/...）",
        },
        "path": {
            "type": "string",
            "description": "screenshot 时截图保存路径，默认 /tmp/desktop_screenshot.png",
        },
        "duration": {
            "type": "number",
            "description": "scroll 时滚动时长（秒），默认 0.5",
        },
    },
    "required": ["action"],
}


def _check_desktop() -> bool:
    """检查是否 macOS"""
    return _check_darwin()


registry.register(
    name="desktop",
    toolset="desktop",
    description=(
        "【macOS 桌面控制】\n\n"
        "通过 AppleScript + 系统命令控制 macOS 桌面，支持：\n"
        "- 打开任意 App（launch/focus，focus 用于恢复已运行但最小化的窗口）\n"
        "- 鼠标点击/移动（click/move）\n"
        "- 键盘输入（type/keypress）\n"
        "- 截图（screenshot）\n"
        "- 当前前台 App（get_front_app）\n"
        "- 运行的 App 列表（list_open_apps）\n\n"
        "依赖：\n"
        "- cliclick（鼠标控制）: brew install cliclick\n"
        "- pyautogui（备选）: pip install pyautogui\n\n"
        "注意：仅支持 macOS，用于 Agent 在用户本机执行桌面操作。"
    ),
    schema=DESKTOP_SCHEMA,
    handler=desktop_execute,
    check_fn=_check_desktop,
    is_async=True,
    emoji="🖥️",
    parallel_mode="never",
)