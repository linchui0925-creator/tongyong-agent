"""
GatewayManager - Profile独立网关进程的生命周期管理器

每个Profile有独立的网关进程，监听不同端口，实现真正的隔离。
主进程(8000)作为控制平面，管理这些网关进程的生命周期。
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Profile网关起始端口
_BASE_PORT = 8001
_MAX_PORTS = 99  # 8001-8099


class GatewayProcess:
    """单个Profile网关进程"""

    def __init__(self, profile_id: str, port: int, process: Optional['asyncio.subprocess.Process'] = None):
        self.profile_id = profile_id
        self.port = port
        self.process = process
        self._start_time = None

    @property
    def is_running(self) -> bool:
        if self.process is None:
            return False
        return self.process.returncode is None

    async def stop(self):
        """停止进程"""
        if self.process and self.is_running:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.process = None

    def restart(self, new_process: 'asyncio.subprocess.Process'):
        """重启进程"""
        import time
        self.process = new_process
        self._start_time = time.time()


class GatewayManager:
    """管理所有Profile网关进程的生命周期"""

    _instance: Optional['GatewayManager'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._gateways: Dict[str, GatewayProcess] = {}  # profile_id → GatewayProcess
        self._used_ports: set[int] = set()
        self._base_port = _BASE_PORT
        self._initialized = True
        self._lock = asyncio.Lock()
        logger.info("GatewayManager 初始化完成")

    # ── 端口管理 ────────────────────────────────────────────

    def _allocate_port(self, profile_id: str) -> int:
        """为Profile分配独立端口"""
        # 优先使用profile已占用的端口
        if profile_id in self._gateways:
            return self._gateways[profile_id].port

        # 查找可用端口
        used = set(gw.port for gw in self._gateways.values())
        for port in range(self._base_port, self._base_port + _MAX_PORTS):
            if port not in used:
                self._used_ports.add(port)
                return port
        raise RuntimeError(f"无可用端口（范围 {self._base_port}-{self._base_port + _MAX_PORTS}）")

    def _release_port(self, port: int):
        """释放端口"""
        self._used_ports.discard(port)

    # ── 进程管理 ────────────────────────────────────────────

    def _get_gateway_command(self, profile_id: str, port: int) -> list:
        """获取启动网关的命令"""
        backend_dir = Path(__file__).parent.parent.parent
        return [
            sys.executable, "-m", "uvicorn",
            "app.gateway.profile_gateway:app",
            "--host", "127.0.0.1",
            "--port", str(port),
        ]

    def _get_gateway_env(self, profile_id: str) -> dict:
        """获取网关进程的环境变量"""
        env = dict(os.environ)
        env["PROFILE_ID"] = profile_id
        env["PYTHONPATH"] = str(Path(__file__).parent.parent.parent)
        return env

    async def start_gateway(self, profile_id: str, port: Optional[int] = None) -> Dict[str, any]:
        """启动指定Profile的独立网关进程"""
        async with self._lock:
            # 如果网关已存在，先停止
            if profile_id in self._gateways:
                await self.stop_gateway(profile_id)

            # 分配端口
            if port is None:
                port = self._allocate_port(profile_id)

            # 启动进程
            backend_dir = Path(__file__).parent.parent.parent
            cmd = self._get_gateway_command(profile_id, port)
            env = self._get_gateway_env(profile_id)

            logger.info(f"启动Profile网关: {profile_id}, 端口: {port}")
            logger.info(f"命令: {' '.join(cmd)}")

            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    cwd=str(backend_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                # 等待进程启动
                await asyncio.sleep(1)

                # 检查进程是否正常启动
                if process.returncode is not None:
                    stdout, stderr = await process.communicate()
                    logger.error(f"网关进程启动失败: {stderr.decode() if stderr else 'unknown'}")
                    return {"success": False, "error": "进程启动失败"}

                gw_process = GatewayProcess(profile_id, port, process)
                self._gateways[profile_id] = gw_process

                logger.info(f"Profile网关启动成功: {profile_id}, PID: {process.pid}, 端口: {port}")
                return {
                    "success": True,
                    "profile_id": profile_id,
                    "port": port,
                    "pid": process.pid,
                    "url": f"http://127.0.0.1:{port}/v1",
                }

            except Exception as e:
                logger.error(f"启动网关失败: {e}")
                return {"success": False, "error": str(e)}

    async def stop_gateway(self, profile_id: str) -> Dict[str, any]:
        """停止指定Profile的网关进程"""
        async with self._lock:
            if profile_id not in self._gateways:
                return {"success": True, "message": "网关不存在"}

            gw = self._gateways[profile_id]
            port = gw.port

            logger.info(f"停止Profile网关: {profile_id}, 端口: {port}")

            try:
                await gw.stop()
                self._release_port(port)
                del self._gateways[profile_id]
                logger.info(f"Profile网关已停止: {profile_id}")
                return {"success": True, "profile_id": profile_id, "port": port}
            except Exception as e:
                logger.error(f"停止网关失败: {e}")
                return {"success": False, "error": str(e)}

    async def restart_gateway(self, profile_id: str) -> Dict[str, any]:
        """重启指定Profile的网关进程"""
        port = None
        if profile_id in self._gateways:
            port = self._gateways[profile_id].port

        await self.stop_gateway(profile_id)
        return await self.start_gateway(profile_id, port)

    def get_gateway_url(self, profile_id: str) -> Optional[str]:
        """获取Profile网关URL"""
        if profile_id in self._gateways:
            port = self._gateways[profile_id].port
            return f"http://127.0.0.1:{port}/v1"
        return None

    def get_gateway_port(self, profile_id: str) -> Optional[int]:
        """获取Profile网关端口"""
        if profile_id in self._gateways:
            return self._gateways[profile_id].port
        return None

    # ── 状态查询 ────────────────────────────────────────────

    def list_gateways(self) -> list:
        """列出所有Profile网关状态"""
        return [
            {
                "profile_id": profile_id,
                "port": gw.port,
                "is_running": gw.is_running,
                "url": f"http://127.0.0.1:{gw.port}/v1",
            }
            for profile_id, gw in self._gateways.items()
        ]

    def get_gateway_status(self, profile_id: str) -> Optional[Dict]:
        """获取指定Profile的网关状态"""
        if profile_id not in self._gateways:
            return None
        gw = self._gateways[profile_id]
        return {
            "profile_id": profile_id,
            "port": gw.port,
            "is_running": gw.is_running,
            "url": f"http://127.0.0.1:{gw.port}/v1",
        }

    async def stop_all(self):
        """停止所有网关"""
        for profile_id in list(self._gateways.keys()):
            await self.stop_gateway(profile_id)
        logger.info("所有Profile网关已停止")

    def __del__(self):
        """析构时确保所有进程已停止"""
        for profile_id in list(self._gateways.keys()):
            gw = self._gateways[profile_id]
            if gw.is_running:
                gw.stop()


# ── 全局单例 ──────────────────────────────────────────────

_gateway_manager: Optional[GatewayManager] = None


def get_gateway_manager() -> GatewayManager:
    """获取GatewayManager单例"""
    global _gateway_manager
    if _gateway_manager is None:
        _gateway_manager = GatewayManager()
    return _gateway_manager
