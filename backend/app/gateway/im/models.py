"""
IM Gateway 数据模型 — 平台无关的 IM 事件抽象

为什么单独抽出：
- 飞书 / 微信 事件 payload 完全不同，但都要收敛成统一的 IMMessageEvent 给 adapter.handle_message
- 配置也统一为 IMPlatformConfig，加新平台只需要新增一个 IMPlatform 枚举值
- 业务逻辑（鉴权、profile 路由、session 管理）只在 base.py 处理一次
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class IMPlatform(str, Enum):
    """IM 平台枚举 — 加新平台在此添加"""

    FEISHU = "feishu"           # 飞书 (Lark)
    WECOM = "wecom"             # 企业微信 (WeChat Work)
    WECHAT_OFFICIAL = "wechat"  # 微信公众号 (WeChat Official Account)


@dataclass
class IMMessageEvent:
    """
    平台无关的入站消息事件

    飞书 / 微信 各自解析完原始 payload 后，都构建一个 IMMessageEvent 传给 adapter.handle_message

    字段说明:
        platform:        来源平台 ("feishu" / "wecom" / "wechat")
        chat_id:         平台内的会话 ID（飞书 chat_id, 微信 openid）
        chat_type:       "direct" (私聊) / "group" (群聊)
        user_id:         发送者的平台内唯一 ID（飞书 open_id, 微信 from_user）
        user_name:       发送者显示名（可选）
        text:            提取出的纯文本（@bot 已被剥离）
        mentioned_bot:   是否 @ 了 bot（群聊场景）
        message_id:      平台消息 ID（用于 reply / 撤回）
        timestamp:       平台时间戳（毫秒）
        raw:             原始 payload（adapter 内部使用，不依赖）
        attachments:     附件 URL 列表（图片 / 文件 / 音频）— 暂未实现
    """

    platform: str
    chat_id: str
    chat_type: str = "direct"  # "direct" | "group"
    user_id: str = ""
    user_name: str = ""
    text: str = ""
    mentioned_bot: bool = True
    message_id: str = ""
    timestamp: int = 0
    raw: Optional[Any] = None
    attachments: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class IMPlatformConfig:
    """
    IM 平台配置 — 来自 settings 或 YAML

    不同平台额外的字段放在 `extra` dict 里（避免每个平台字段污染主类）
    """

    platform: IMPlatform
    enabled: bool = False

    # ── 通用鉴权 ──
    allowed_users: List[str] = field(default_factory=list)   # 白名单 open_id 列表
    allow_all_users: bool = False                              # 危险开关，默认 False

    # ── 消息路由 ──
    # IM 用户 → tongyong profile 映射
    # 例: {"ou_xxx": "default", "ou_yyy": "linc"}
    user_profile_map: Dict[str, str] = field(default_factory=dict)
    default_profile: str = "default"  # 兜底 profile

    # ── 平台私有配置 ──
    # 飞书: app_id / app_secret / verification_token / encrypt_key
    # 企业微信: corp_id / corp_secret / agent_id / token / encoding_aes_key
    # 公众号: appid / appsecret / token / encoding_aes_key
    extra: Dict[str, Any] = field(default_factory=dict)

    # ── 行为开关 ──
    show_tool_calls: bool = True   # 是否推送 tool_start / tool_complete 到 IM
    show_thinking: bool = False     # 是否推送 thinking_delta（默认折叠）
    max_message_length: int = 4000  # 单条消息最大字符数（飞书 4KB / 微信 2KB 需各平台覆盖）

    def is_user_allowed(self, user_id: str) -> bool:
        """检查用户是否在白名单"""
        if self.allow_all_users:
            return True
        if not self.allowed_users:
            # 没配白名单 + 没开 allow_all → 拒绝（fail-closed）
            return False
        return user_id in self.allowed_users

    def resolve_profile(self, user_id: str) -> str:
        """根据 user_id 解析出 tongyong profile 名"""
        return self.user_profile_map.get(user_id, self.default_profile)


# ── 辅助类型 ──

@dataclass
class IMResponse:
    """adapter.send 的返回"""

    success: bool
    message_id: str = ""        # 平台回执的消息 ID（用于后续编辑/撤回）
    error: str = ""
    raw: Optional[Dict[str, Any]] = None
