"""
IM Gateway — 飞书 / 企业微信 / 微信 平台 adapter 集合

设计参考 hermes-agent `gateway/platforms/`，但简化：
- 不引入 plugin 机制（tongyong 是单仓）
- 直接用 dataclass 配置
- 适配器只关心：connect / send / handle_message

模块结构:
    base.py       - IMPlatformAdapter 抽象基类
    models.py     - IMMessageEvent / IMPlatformConfig 数据类
    manager.py    - IMGatewayManager 多平台生命周期
    feishu.py     - 飞书 adapter
    wecom.py      - 企业微信 adapter
    wechat.py     - 微信服务号 adapter
"""

from app.gateway.im.models import IMMessageEvent, IMPlatformConfig, IMPlatform, IMResponse
from app.gateway.im.base import IMPlatformAdapter, set_agent_engine
from app.gateway.im.manager import IMGatewayManager, im_gateway_manager, inject_agent_engine

__all__ = [
    "IMMessageEvent",
    "IMPlatformConfig",
    "IMPlatform",
    "IMResponse",
    "IMPlatformAdapter",
    "IMGatewayManager",
    "im_gateway_manager",
    "set_agent_engine",
    "inject_agent_engine",
]
