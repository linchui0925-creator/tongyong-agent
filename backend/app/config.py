"""
全局配置 - 应用启动时从 .env / 环境变量加载。

通过 pydantic_settings.BaseSettings 自动从环境变量读值，支持：
  - 11 个 LLM provider 的 API key（tongyi / openai / deepseek / anthropic ...）
  - 数据持久化路径（SQLite / ChromaDB）
  - 记忆与压缩阈值
  - 各 IM Gateway 的 app_id / app_secret

单例通过 get_settings() 访问；不要直接 Settings() 多次实例化。
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Any, Dict, List, Optional


class Settings(BaseSettings):
    """应用配置单例。字段缺失时使用默认值，env 变量优先级最高。"""
    app_name: str = "TongYong Agent"
    debug: bool = True

    database_url: str = "sqlite:///./data/tongyong.db"

    chroma_persist_directory: str = "./data/chroma"

    default_llm_provider: str = "tongyi"
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
    edgefn_api_key: Optional[str] = None  # W4-41: edgefn.net 聚合代理 (GLM/DeepSeek)

    memory_top_k: int = 10
    compress_threshold: int = 5000

    # Hermes 平文件系统
    hermes_enabled: bool = False
    hermes_memory_dir: str = "./data/hermes"
    hermes_skills_dir: str = "./data/hermes/skills"

    # Dreaming 梦境系统
    dreaming_enabled: bool = False
    dreaming_frequency: str = "0 3 * * *"
    dreaming_lookback_days: int = 7
    dreaming_min_score: float = 0.8
    dreaming_min_recall: int = 3
    dreaming_min_queries: int = 3

    # Nudge 后台反思
    nudge_memory_interval: int = 10
    nudge_skill_interval: int = 10

    # MCP 服务器配置
    # mcp_servers:
    #   filesystem:
    #     command: "npx"
    #     args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    #     env: {}
    mcp_servers: Dict[str, Dict[str, Any]] = {}

    # Skill 市场（外部 GitHub 仓库源）
    # 用户在"市场"Tab 添加的 owner/repo 列表，默认空
    marketplace_sources: List[str] = []
    marketplace_cache_ttl_hours: int = 24
    marketplace_github_token: Optional[str] = None  # 提高 rate limit

    # ── IM Gateway (Phase 0+) ──
    # 飞书
    feishu_enabled: bool = False
    feishu_app_id: Optional[str] = None
    feishu_app_secret: Optional[str] = None
    feishu_verification_token: Optional[str] = None
    feishu_encrypt_key: Optional[str] = None
    feishu_domain: str = "feishu"  # feishu / lark / larksuite
    feishu_allowed_users: List[str] = []
    feishu_allow_all_users: bool = False
    feishu_default_profile: str = "default"
    feishu_user_profile_map: Dict[str, str] = {}  # {"ou_alice": "linc", ...}
    # 企业微信
    wecom_enabled: bool = False
    wecom_corp_id: Optional[str] = None
    wecom_agent_id: Optional[str] = None
    wecom_corp_secret: Optional[str] = None
    wecom_token: Optional[str] = None
    wecom_aes_key: Optional[str] = None
    wecom_allowed_users: List[str] = []
    wecom_default_profile: str = "default"
    # 微信服务号
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
