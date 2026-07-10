"""
全局配置 - 应用启动时从 .env / 环境变量加载。
"""
import os
import json
import re
from typing import Any, Dict, List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


def load_mcp_servers_from_env() -> Dict[str, Dict[str, Any]]:
    """从环境变量加载MCP服务器配置"""
    mcp_servers = {}
    pattern = re.compile(r'^MCP_SERVERS_([A-Z0-9_]+)_(COMMAND|ARGS|ENV)$', re.IGNORECASE)
    
    for key, value in os.environ.items():
        match = pattern.match(key)
        if not match:
            continue
        server_id = match.group(1).lower()
        field = match.group(2).lower()
        if server_id not in mcp_servers:
            mcp_servers[server_id] = {}
        try:
            if field == "args":
                mcp_servers[server_id][field] = json.loads(value)
            elif field == "env":
                mcp_servers[server_id][field] = json.loads(value)
            else:
                mcp_servers[server_id][field] = value
        except json.JSONDecodeError:
            pass
    
    valid_servers = {}
    for sid, config in mcp_servers.items():
        if "command" in config:
            valid_servers[sid] = config
    return valid_servers


class Settings(BaseSettings):
    app_name: str = "TongYong Agent"
    debug: bool = True
    database_url: str = "sqlite:///./data/tongyong.db"
    chroma_persist_directory: str = "./data/chroma"
    default_llm_provider: str = "edgefn"  # W5-2: 默认 edgefn
    default_llm_model: str = "GLM-4.5V"   # W5-2: 默认 GLM-4.5V
    
    tongyi_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    zhipu_api_key: Optional[str] = None
    baichuan_api_key: Optional[str] = None
    wenxin_api_key: Optional[str] = None
    xfyun_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    yi_api_key: Optional[str] = None
    minimax_api_key: Optional[str] = None
    moonshot_api_key: Optional[str] = None
    stepfun_api_key: Optional[str] = None
    siliconflow_api_key: Optional[str] = None
    # W5-2 (2026-07-09): 默认硬编码 edgefn API Key。
    # 部署不配 EDGEFN_API_KEY 环境变量 / .env 时使用该值。
    # ⚠️  该 key 已经写在 git 历史里, 公开仓库前请先在 edgefn 控制台 rotate。
    edgefn_api_key: str = "sk-HJVebvMXb0dEQc2RAe92EeAc2fAc4aF89910D38871016217"
    
    memory_top_k: int = 10
    compress_threshold: int = 5000
    
    hermes_enabled: bool = False
    hermes_memory_dir: str = "./data/hermes"
    hermes_skills_dir: str = "./data/hermes/skills"
    
    dreaming_enabled: bool = False
    dreaming_frequency: str = "0 3 * * *"
    dreaming_lookback_days: int = 7
    dreaming_min_score: float = 0.8
    dreaming_min_recall: int = 3
    dreaming_min_queries: int = 3
    
    nudge_memory_interval: int = 10
    nudge_skill_interval: int = 10
    
    @property
    def mcp_servers(self) -> Dict[str, Dict[str, Any]]:
        return load_mcp_servers_from_env()
    
    marketplace_sources: List[str] = []
    marketplace_cache_ttl_hours: int = 24
    marketplace_github_token: Optional[str] = None

    # W5-1: Community Hub (Skill marketplace union) — config
    community_hub_sync_interval_hours: int = 6
    community_hub_sync_on_startup: bool = True
    community_hub_browse_lol_enabled: bool = False
    community_hub_browse_cn_enabled: bool = False
    community_hub_scrape_rate_per_sec: float = 1.0
    community_hub_max_repos: int = 50
    community_hub_frontend_install_confirm: bool = True
    
    feishu_webhook_url: Optional[str] = None
    feishu_enabled: bool = False
    feishu_app_id: Optional[str] = None
    feishu_app_secret: Optional[str] = None
    feishu_verification_token: Optional[str] = None
    feishu_encrypt_key: Optional[str] = None
    feishu_domain: str = "feishu"
    feishu_allowed_users: List[str] = []
    feishu_allow_all_users: bool = False
    feishu_default_profile: str = "default"
    feishu_user_profile_map: Dict[str, str] = {}
    
    wecom_enabled: bool = False
    wecom_corp_id: Optional[str] = None
    wecom_agent_id: Optional[str] = None
    wecom_corp_secret: Optional[str] = None
    wecom_token: Optional[str] = None
    wecom_aes_key: Optional[str] = None
    wecom_allowed_users: List[str] = []
    wecom_default_profile: str = "default"
    
    wechat_enabled: bool = False
    wechat_app_id: Optional[str] = None
    wechat_app_secret: Optional[str] = None
    wechat_token: Optional[str] = None
    wechat_aes_key: Optional[str] = None
    wechat_allowed_users: List[str] = []
    wechat_default_profile: str = "default"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
