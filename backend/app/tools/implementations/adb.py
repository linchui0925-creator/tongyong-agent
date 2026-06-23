"""
adb - Android 设备控制工具

通过 ADB（Android Debug Bridge）控制 Android 设备：
- 安装/卸载 App
- 启动 Activity / Service
- 点击/滑动/输入
- 截图
- Shell 命令

前置条件：Android 设备已通过 USB 或网络连接，adb 可用。
"""

import logging
import subprocess
import os
import re
from typing import Optional, Tuple

from app.tools.registry import registry

logger = logging.getLogger(__name__)

# ── ADB 执行 ───────────────────────────────────────────────


def _run_adb(args: list, device_serial: Optional[str] = None, timeout: int = 30) -> Tuple[str, str, int]:
    """执行 adb 命令，返回 (stdout, stderr, returncode)"""
    cmd = ["adb"]
    if device_serial:
        cmd.extend(["-s", device_serial])
    cmd.extend(args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout, result.stderr, result.returncode
    except FileNotFoundError:
        return "", "adb 未找到（请确保 Android SDK platform-tools 在 PATH 中）", 1
    except subprocess.TimeoutExpired:
        return "", f"命令超时（{timeout}s）", 1
    except Exception as e:
        return "", str(e), 1


def _check_adb() -> bool:
    """检查 adb 是否可用"""
    stdout, _, code = _run_adb(["version"])
    return code == 0


def _device_connected(serial: Optional[str] = None) -> bool:
    """检查设备是否连接"""
    stdout, _, code = _run_adb(["devices"] if not serial else ["-s", serial, "get-state"])
    if code != 0:
        return False
    if serial:
        return "device" in stdout or "device:" in stdout
    # 列出所有设备
    lines = stdout.strip().split("\n")
    return any("device" in line and "emulator" not in line for line in lines[1:] if line.strip())


# ── ADB 工具入口 ───────────────────────────────────────────


async def adb_execute(
    action: str,
    package: str = "",
    activity: str = "",
    device_serial: str = "",
    x: int = 0,
    y: int = 0,
    text: str = "",
    key: str = "",
    path: str = "/sdcard/screen.png",
    local_path: str = "/tmp/android_screenshot.png",
    timeout: int = 30,
) -> str:
    """
    ADB 工具入口。

    action:
      devices           列出已连接设备
      install           安装 APK（package 为 APK 路径）
      uninstall         卸载 App（package 为包名）
      start_app         启动 App（package 为包名）
      start_activity    启动 Activity（package/activity）
      tap               点击坐标（x, y）
      swipe             滑动（x1,y1,x2,y2, duration）
      input_text        输入文本（text）
      keypress          按键（key）
      screenshot        截图并拉取到本地（local_path）
      shell             执行 shell 命令（text 为命令）
      current_app       获取当前前台 App

    示例：
      adb(action="devices")
      adb(action="install", package="/tmp/app.apk")
      adb(action="start_app", package="com.android.chrome")
      adb(action="tap", x=500, y=300)
      adb(action="input_text", text="hello")
      adb(action="screenshot", local_path="/tmp/screen.png")
    """
    serial = device_serial if device_serial else None

    try:
        if action == "devices":
            stdout, _, code = _run_adb(["devices"])
            if code != 0:
                return f"ADB 错误: {stdout or 'unknown'}"
            lines = stdout.strip().split("\n")
            devices = [l for l in lines[1:] if l.strip()]
            if not devices:
                return "没有已连接的 Android 设备"
            return f"已连接设备（{len(devices)} 个）:\n" + "\n".join(devices)

        elif action == "install":
            if not package:
                return "install 需要 package 参数（APK 路径）"
            if not os.path.exists(package):
                return f"APK 文件不存在: {package}"
            stdout, stderr, code = _run_adb(["install", "-r", package], serial, timeout=120)
            if code == 0:
                return f"安装成功: {package}"
            return f"安装失败: {stderr or stdout}"

        elif action == "uninstall":
            if not package:
                return "uninstall 需要 package 参数（包名）"
            stdout, stderr, code = _run_adb(["uninstall", package], serial)
            if code == 0:
                return f"已卸载: {package}"
            return f"卸载失败: {stderr or stdout}"

        elif action == "start_app":
            if not package:
                return "start_app 需要 package 参数"
            stdout, stderr, code = _run_adb(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"], serial)
            if code == 0:
                return f"已启动: {package}"
            return f"启动失败: {stderr or stdout}"

        elif action == "start_activity":
            if not package or not activity:
                return "start_activity 需要 package 和 activity 参数"
            component = f"{package}/{activity}"
            stdout, stderr, code = _run_adb(["shell", "am", "start", "-n", component], serial)
            if code == 0 and "started" in stdout.lower():
                return f"已启动 Activity: {component}"
            return f"启动失败: {stderr or stdout}"

        elif action == "tap":
            stdout, stderr, code = _run_adb(["shell", "input", "tap", str(x), str(y)], serial)
            if code == 0:
                return f"已点击: ({x}, {y})"
            return f"点击失败: {stderr or stdout}"

        elif action == "swipe":
            # swipe x1 y1 x2 y2 duration(ms)
            parts = text.split()
            if len(parts) >= 4:
                x1, y1, x2, y2 = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                duration = int(parts[4]) if len(parts) > 4 else 300
            else:
                return "swipe 的 text 格式: x1 y1 x2 y2 [duration]"
            stdout, stderr, code = _run_adb(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)], serial)
            if code == 0:
                return f"已滑动: ({x1},{y1}) → ({x2},{y2})"
            return f"滑动失败: {stderr or stdout}"

        elif action == "input_text":
            if not text:
                return "input_text 需要 text 参数"
            # 转义特殊字符
            escaped = text.replace(" ", "%s").replace("'", "\\'")
            stdout, stderr, code = _run_adb(["shell", "input", "text", escaped], serial)
            if code == 0:
                return f"已输入: {text[:20]}..."
            return f"输入失败: {stderr or stdout}"

        elif action == "keypress":
            if not key:
                return "keypress 需要 key 参数"
            # 按键映射
            key_map = {
                "HOME": "3",
                "BACK": "4",
                "ENTER": "66",
                "TAB": "61",
                "ESCAPE": "82",
                "POWER": "26",
                "VOLUME_UP": "24",
                "VOLUME_DOWN": "25",
                "UP": "19",
                "DOWN": "20",
                "LEFT": "21",
                "RIGHT": "22",
                "MENU": "82",
            }
            keycode = key_map.get(key.upper(), key)
            stdout, stderr, code = _run_adb(["shell", "input", "keyevent", keycode], serial)
            if code == 0:
                return f"已按键: {key}"
            return f"按键失败: {stderr or stdout}"

        elif action == "screenshot":
            # 先截图到设备
            stdout, stderr, code = _run_adb(["shell", "screencap", "-p", path], serial, timeout=10)
            if code != 0:
                return f"截图失败: {stderr or stdout}"
            # 拉取到本地
            dest_dir = os.path.dirname(local_path)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)
            stdout2, stderr2, code2 = _run_adb(["pull", path, local_path], serial, timeout=30)
            if code2 == 0:
                return f"截图已保存: {os.path.abspath(local_path)}"
            return f"拉取截图失败: {stderr2 or stdout2}"

        elif action == "shell":
            if not text:
                return "shell 需要 text 参数（命令）"
            stdout, stderr, code = _run_adb(["shell", text], serial, timeout=timeout)
            if code == 0:
                return stdout[:2000] or "命令执行成功（无输出）"
            return f"Shell 错误: {stderr or stdout}"

        elif action == "current_app":
            # 获取当前前台 App 的包名
            stdout, stderr, code = _run_adb(["shell", "dumpsys", "activity", "activities"], serial, timeout=15)
            if code != 0:
                return f"获取失败: {stderr or stdout}"
            # 找 mResumedActivity
            match = re.search(r'mResumedActivity.*?([a-zA-Z0-9\.]+)/([a-zA-Z0-9\.]+)', stdout)
            if match:
                package, activity = match.groups()
                return f"当前前台: {package}/{activity}"
            # 备选方式
            stdout2, _, _ = _run_adb(["shell", "dumpsys", "window", "windows"], serial)
            match2 = re.search(r'mCurrentFocus.*?([a-zA-Z0-9\.]+)/([a-zA-Z0-9\.]+)', stdout2)
            if match2:
                package, activity = match2.groups()
                return f"当前前台: {package}/{activity}"
            return "无法确定当前前台 App"

        elif action == "get_device_info":
            model, _, _ = _run_adb(["shell", "getprop", "ro.product.model"], serial)
            version, _, _ = _run_adb(["shell", "getprop", "ro.build.version.release"], serial)
            manufacturer, _, _ = _run_adb(["shell", "getprop", "ro.product.manufacturer"], serial)
            return f"设备信息: {manufacturer.strip()} {model.strip()} (Android {version.strip()})"

        else:
            return f"未知操作: {action}，支持的: devices/install/uninstall/start_app/start_activity/tap/swipe/input_text/keypress/screenshot/shell/current_app/get_device_info"

    except Exception as e:
        logger.error(f"ADB 工具失败: {e}", exc_info=True)
        return f"ADB 执行失败: {e}"


# ── Schema ────────────────────────────────────────────────


ADB_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "description": "操作类型",
            "enum": ["devices", "install", "uninstall", "start_app", "start_activity", "tap", "swipe", "input_text", "keypress", "screenshot", "shell", "current_app", "get_device_info"],
        },
        "package": {
            "type": "string",
            "description": "包名或 APK 路径（install/uninstall/start_app/start_activity 用）",
        },
        "activity": {
            "type": "string",
            "description": "Activity 名称（start_activity 用，如 .MainActivity）",
        },
        "device_serial": {
            "type": "string",
            "description": "设备序列号（多设备时必填）",
        },
        "x": {
            "type": "integer",
            "description": "tap 时的 X 坐标",
        },
        "y": {
            "type": "integer",
            "description": "tap 时的 Y 坐标",
        },
        "text": {
            "type": "string",
            "description": "input_text/swipe/shell 时的文本",
        },
        "key": {
            "type": "string",
            "description": "keypress 时的按键（HOME/BACK/ENTER/POWER/VOLUME_UP/...）",
        },
        "path": {
            "type": "string",
            "description": "screenshot 时设备端路径，默认 /sdcard/screen.png",
        },
        "local_path": {
            "type": "string",
            "description": "screenshot 时拉取到本地的路径",
        },
    },
    "required": ["action"],
}


def _check_adb_tool() -> bool:
    """检查 adb 是否可用"""
    return _check_adb()




def _register_tools():
    registry.register(
        name="adb",
        toolset="android",
        description=(
            "【Android 设备控制】\n\n"
            "通过 ADB 控制 Android 设备，支持：\n"
            "- 设备管理（devices / get_device_info）\n"
            "- App 安装卸载（install / uninstall）\n"
            "- 启动 App/Activity（start_app / start_activity）\n"
            "- 操作界面（tap / swipe / input_text / keypress）\n"
            "- 截图（screenshot）\n"
            "- 执行 Shell 命令（shell）\n"
            "- 查看当前前台 App（current_app）\n\n"
            "前置条件：Android 设备通过 USB 或网络连接，adb 在 PATH 中。\n"
            "网络连接：adb connect <ip>:5555"
        ),
        schema=ADB_SCHEMA,
        handler=adb_execute,
        check_fn=_check_adb_tool,
        is_async=True,
        emoji="📱",
        parallel_mode="never",
    )


# 启动时注册 (W4-21 P2-2: 显式 _register_tools, 便于测试 mock)
_register_tools()
