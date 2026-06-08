"""
IMGatewayManager — IM 平台生命周期管理

职责:
- 启动时从 settings 读取所有启用的平台
- 启停各平台的 adapter
- 提供统一的 start / stop / status 接口给 main.py
- 集中错误处理：单个平台失败不影响其他

设计参考 hermes-agent `gateway/run.py::start_gateway()`
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.gateway.im.base import IMPlatformAdapter, set_agent_engine
from app.gateway.im.models import IMPlatform, IMPlatformConfig

logger = logging.getLogger(__name__)


class IMGatewayManager:
    """
    IM 网关管理器 — 单例

    用法:
        manager = IMGatewayManager()
        manager.set_platform_config(IMPlatform.FEISHU, feishu_config)
        await manager.start_all()

    或在 main.py lifespan 里:
        await im_gateway_manager.start_all()
    """

    def __init__(self):
        self._configs: Dict[IMPlatform, IMPlatformConfig] = {}
        self._adapters: Dict[str, IMPlatformAdapter] = {}  # platform_name → adapter
        self._started: bool = False

    # ── 配置注册 ──

    def set_platform_config(self, platform: IMPlatform, config: IMPlatformConfig) -> None:
        """注册某个平台的配置（在 start 之前调用）"""
        if self._started:
            logger.warning(f"[IMGateway] 启动后注册 {platform.value} 不会立即生效")
        self._configs[platform] = config

    def remove_platform_config(self, platform: IMPlatform) -> None:
        self._configs.pop(platform, None)

    # ── 生命周期 ──

    async def start_all(self) -> Dict[str, bool]:
        """
        启动所有 enabled 平台

        Returns: {platform_name: success_bool}
        """
        if self._started:
            logger.warning("[IMGateway] 已启动，重复 start_all 忽略")
            return {p.value: True for p in self._adapters}

        results: Dict[str, bool] = {}
        for platform, config in self._configs.items():
            if not config.enabled:
                logger.info(f"[IMGateway] 跳过未启用平台: {platform.value}")
                continue
            ok = await self._start_one(platform, config)
            results[platform.value] = ok

        self._started = True
        if results:
            logger.info(f"[IMGateway] 启动完成: {results}")
        else:
            logger.info("[IMGateway] 没有启用的 IM 平台")
        return results

    async def stop_all(self) -> None:
        """停止所有平台"""
        if not self._started:
            return
        logger.info("[IMGateway] 停止所有平台...")
        for name, adapter in self._adapters.items():
            try:
                await adapter.disconnect()
            except Exception as e:
                logger.error(f"[IMGateway] 停止 {name} 失败: {e}", exc_info=True)
        self._adapters.clear()
        self._started = False
        logger.info("[IMGateway] 全部停止")

    async def _start_one(self, platform: IMPlatform, config: IMPlatformConfig) -> bool:
        """启动单个平台"""
        try:
            adapter = self._create_adapter(platform, config)
            if adapter is None:
                logger.warning(f"[IMGateway] {platform.value} adapter 未实现或依赖缺失")
                return False
            ok = await adapter.connect()
            if ok:
                self._adapters[platform.value] = adapter
                logger.info(f"[IMGateway] {platform.value} 启动成功")
            else:
                logger.error(f"[IMGateway] {platform.value} connect 返回 False")
            return ok
        except Exception as e:
            logger.error(f"[IMGateway] 启动 {platform.value} 异常: {e}", exc_info=True)
            return False

    def _create_adapter(self, platform: IMPlatform, config: IMPlatformConfig) -> Optional[IMPlatformAdapter]:
        """
        工厂方法 — 根据平台枚举创建对应 adapter

        延迟 import：避免没装 SDK 时整个包加载失败
        """
        try:
            if platform == IMPlatform.FEISHU:
                from app.gateway.im.feishu import FeishuAdapter, check_feishu_requirements
                if not check_feishu_requirements():
                    logger.warning("[IMGateway] 飞书依赖缺失: pip install lark-oapi")
                    return None
                return FeishuAdapter(config)

            elif platform == IMPlatform.WECOM:
                from app.gateway.im.wecom import WeComAdapter, check_wecom_requirements
                if not check_wecom_requirements():
                    logger.warning("[IMGateway] 企业微信依赖缺失: pip install wechatpy[cryptography]")
                    return None
                return WeComAdapter(config)

            elif platform == IMPlatform.WECHAT_OFFICIAL:
                from app.gateway.im.wechat import WeChatAdapter, check_wechat_requirements
                if not check_wechat_requirements():
                    logger.warning("[IMGateway] 微信依赖缺失: pip install wechatpy")
                    return None
                return WeChatAdapter(config)

            else:
                logger.error(f"[IMGateway] 未知平台: {platform}")
                return None
        except ImportError as e:
            logger.error(f"[IMGateway] {platform.value} adapter 加载失败: {e}")
            return None

    # ── 状态查询 ──

    def get_status(self) -> Dict[str, Any]:
        """返回所有平台连接状态 — 给 /api/gateway/status 用"""
        return {
            "started": self._started,
            "platforms": {
                name: {
                    "connected": adapter._connected,
                    "platform": adapter.platform_name,
                    "active_sessions": len(adapter._session_map),
                }
                for name, adapter in self._adapters.items()
            },
        }

    def get_adapter(self, platform_name: str) -> Optional[IMPlatformAdapter]:
        return self._adapters.get(platform_name)


# ── 全局单例 ──
# main.py 启停时用这个
im_gateway_manager = IMGatewayManager()


def inject_agent_engine(engine: Any) -> None:
    """main.py lifespan 里调用一次"""
    set_agent_engine(engine)
