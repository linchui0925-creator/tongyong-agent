from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Profile(BaseModel):
    """网关Profile配置"""
    id: str = Field(..., description="唯一标识")
    name: str = Field(..., description="显示名称")

    # LLM 配置
    provider: str = Field(..., description="LLM provider (e.g., tongyi, openai)")
    model: Optional[str] = Field(None, description="模型名覆盖")
    api_key: Optional[str] = Field(None, description="API key")
    api_endpoint: Optional[str] = Field(None, description="自定义API endpoint")

    # 生成参数
    temperature: Optional[float] = Field(None, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, ge=1)
    top_p: Optional[float] = Field(None, ge=0, le=1)

    # 网关设置
    max_tool_rounds: int = Field(default=10)

    # 独立网关端口 (0表示未启动独立网关)
    gateway_port: int = Field(default=0, description="独立网关端口，0表示未分配")

    # 元数据
    is_default: bool = Field(default=False)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class GatewaySettings(BaseSettings):
    """OpenAI-compatible 网关配置"""

    # API 认证
    api_key: str = Field(default="", alias="GATEWAY_API_KEY")
    """API密钥。为空时所有请求放行（仅限本地使用）。"""

    # 服务配置
    model_name: str = Field(default="tongyong-agent", alias="GATEWAY_MODEL_NAME")
    """对外暴露的模型名称"""

    # 会话
    max_tool_rounds: int = Field(default=10, alias="GATEWAY_MAX_TOOL_ROUNDS")
    """工具调用最大轮数"""

    # Profile管理
    profile_config_path: str = Field(default="data/gateway_profiles.json")
    """Profile配置文件路径"""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        protected_namespaces=(),
    )
