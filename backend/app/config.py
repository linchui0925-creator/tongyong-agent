from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Any, Dict, Optional


class Settings(BaseSettings):
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

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
