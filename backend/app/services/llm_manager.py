"""
LLMManager - 全局 LLM 管理器

职责：
1. 统一管理所有 LLM 提供商的 API 密钥和配置
2. 支持动态切换模型并同步到 AgentEngine
3. 配置持久化（保存/加载到 JSON 文件）
4. 管理多组已保存的模型配置
5. 支持per-profile独立实例
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Dict, Optional, Any, List

from app.llm.base import BaseLLM
from app.llm.factory import get_llm, get_available_providers, get_provider_info

logger = logging.getLogger(__name__)


def _get_default_config_path(profile_id: str = "default") -> Path:
    """获取指定profile的配置文件路径"""
    if profile_id == "default":
        return Path("data/llm_config.json")
    return Path(f"data/hermes/profiles/{profile_id}/llm_config.json")


class LLMManager:
    """全局 LLM 管理器，支持动态切换模型，可per-profile独立实例"""

    _instance = None

    def __new__(cls, profile_id: str = "default"):
        # 如果是默认profile且已有全局单例，返回单例
        if profile_id == "default" and cls._instance is not None:
            return cls._instance
        # 否则创建新实例
        instance = super().__new__(cls)
        instance._initialized = False
        return instance

    def __init__(self, profile_id: str = "default"):
        # 避免重复初始化（Python可能多次调用__new__）
        if hasattr(self, '_initialized') and self._initialized and profile_id == "default":
            return
        self.profile_id = profile_id
        self._config_file = _get_default_config_path(profile_id)
        self._current_llm: Optional[BaseLLM] = None
        self._current_provider: str = "tongyi"
        self._current_model: Optional[str] = None
        self._current_config: Dict[str, Any] = {}
        self._agent_engine_ref = None
        self._api_keys: Dict[str, str] = {}
        self._saved_models: List[Dict[str, Any]] = []
        self._initialized = True
        self._load_config()

    # ── AgentEngine 绑定 ──────────────────────────────────

    def bind_agent_engine(self, engine) -> None:
        """绑定 AgentEngine 实例，切换模型时自动同步"""
        self._agent_engine_ref = engine
        if self._current_llm is not None:
            self._sync_to_agent()
        logger.info(f"LLMManager[{self.profile_id}] 已绑定 AgentEngine")

    def _seed_initial_llm(self, llm: BaseLLM, provider: str) -> None:
        """在启动时注入已有的 LLM 实例（避免重复创建）"""
        self._current_llm = llm
        self._current_provider = provider
        logger.info(f"LLMManager[{self.profile_id}] 已接收初始 LLM: {provider}")

    def try_restore_saved_provider(self) -> bool:
        """尝试从已保存的配置中恢复上次使用的 provider"""
        saved_provider = None
        saved_model = None
        saved_endpoint = None
        try:
            if self._config_file.exists():
                data = json.loads(self._config_file.read_text(encoding="utf-8"))
                saved_provider = data.get("provider")
                saved_model = data.get("model")
                saved_provider_cfg = data.get("saved_models", [])
                if saved_provider and saved_model:
                    for entry in saved_provider_cfg:
                        if entry.get("provider") == saved_provider and entry.get("model") == saved_model:
                            saved_endpoint = entry.get("api_endpoint")
                            break
        except Exception as e:
            logger.warning(f"读取保存的配置失败: {e}")
            return False

        if not saved_provider:
            logger.info(f"LLMManager[{self.profile_id}] 没有保存的 provider")
            return False
        if saved_provider == self._current_provider and self._current_llm is not None:
            logger.info(f"保存的 provider 与当前相同且 LLM 已存在")
            return True

        api_key = self.get_api_key(saved_provider)
        if not api_key:
            logger.warning(f"已保存的 provider {saved_provider} 无 API key")
            return False

        try:
            from app.llm.factory import get_llm
            llm = get_llm(saved_provider, api_key)
            if saved_model:
                llm.model = saved_model
            if saved_endpoint and hasattr(llm, 'api_base'):
                llm.api_base = saved_endpoint
            self._current_llm = llm
            self._current_provider = saved_provider
            self._current_model = saved_model
            self._sync_to_agent()
            logger.info(f"已从保存的配置恢复 LLM: {saved_provider} / {saved_model}")
            return True
        except Exception as e:
            logger.warning(f"恢复保存的 LLM 失败: {e}")
            return False

    def _sync_to_agent(self) -> None:
        """将当前 LLM 同步到 AgentEngine"""
        if self._agent_engine_ref is not None:
            self._agent_engine_ref.llm = self._current_llm
            logger.debug(f"LLMManager[{self.profile_id}] 同步到 AgentEngine")

    # ── 配置持久化 ────────────────────────────────────────

    def _load_config(self) -> None:
        """从文件加载配置"""
        try:
            if self._config_file.exists():
                data = json.loads(self._config_file.read_text(encoding="utf-8"))
                self._api_keys = data.get("api_keys", {})
                self._saved_models = data.get("saved_models", [])
                saved_provider = data.get("provider")
                if saved_provider and saved_provider in get_available_providers():
                    self._current_provider = saved_provider
                    self._current_model = data.get("model") or self._current_model
                logger.info(f"LLMManager[{self.profile_id}] 已加载配置")
        except Exception as e:
            logger.warning(f"加载 LLM 配置失败: {e}")

    def _save_config(self) -> None:
        """保存配置到文件"""
        try:
            self._config_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "provider": self._current_provider,
                "model": self._current_model,
                "api_keys": self._api_keys,
                "saved_models": self._saved_models,
            }
            self._config_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"保存 LLM 配置失败: {e}")

    # ── API 密钥管理 ──────────────────────────────────────

    def get_api_key(self, provider: str) -> Optional[str]:
        """获取指定 provider 的 API 密钥"""
        if provider in self._api_keys:
            key = self._api_keys[provider]
            # 占位符视为无效，回退到环境变量
            if key and not key.startswith("YOUR_"):
                return key
        from app.llm.factory import _get_default_api_key
        key = _get_default_api_key(provider)
        if key:
            self._api_keys[provider] = key
        return key

    def set_api_key(self, provider: str, api_key: str) -> None:
        """设置并持久化指定 provider 的 API 密钥"""
        if api_key:
            self._api_keys[provider] = api_key
            self._save_config()

    def get_all_api_keys(self) -> Dict[str, str]:
        """获取所有已配置的 API 密钥"""
        result = dict(self._api_keys)
        for p in get_available_providers():
            if p not in result:
                from app.llm.factory import _get_default_api_key
                key = _get_default_api_key(p)
                if key:
                    result[p] = key
        return result

    # ── 当前状态 ──────────────────────────────────────────

    def get_current_llm(self) -> Optional[BaseLLM]:
        return self._current_llm

    def get_current_provider(self) -> str:
        return self._current_provider

    def get_current_model(self) -> Optional[str]:
        return self._current_model

    def get_current_config(self) -> Dict[str, Any]:
        return {
            "provider": self._current_provider,
            "model": self._current_model,
            "api_key_configured": bool(self.get_api_key(self._current_provider)),
        }

    # ── 模型切换 ──────────────────────────────────────────

    def switch_model(
        self,
        provider: str,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        api_endpoint: Optional[str] = None,
        **kwargs,
    ) -> bool:
        """切换模型"""
        try:
            available = get_available_providers()
            if provider not in available:
                logger.error(f"提供商 {provider} 不可用，可用: {available}")
                return False

            resolved_key = api_key or self.get_api_key(provider)
            if not resolved_key:
                logger.warning(f"{provider} 未配置 API 密钥")

            llm = get_llm(provider, resolved_key)
            if not llm:
                logger.error(f"无法创建 LLM 实例: {provider}")
                return False

            if api_endpoint and hasattr(llm, 'api_base'):
                llm.api_base = api_endpoint
            if model:
                llm.model = model

            for key, value in kwargs.items():
                if hasattr(llm, key):
                    setattr(llm, key, value)

            self._current_llm = llm
            self._current_provider = provider
            self._current_model = model

            if api_key:
                self._api_keys[provider] = api_key

            self._sync_to_agent()
            self._save_config()

            logger.info(f"LLMManager[{self.profile_id}] 模型切换: {provider} / {model or llm.model}")
            return True

        except Exception as e:
            logger.error(f"模型切换失败: {e}", exc_info=True)
            return False

    async def test_connection(
        self,
        provider: str,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        api_endpoint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """测试模型连接"""
        result = {"success": False, "message": "", "model": ""}
        try:
            resolved_key = api_key or self.get_api_key(provider)
            llm = get_llm(provider, resolved_key)
            if api_endpoint and hasattr(llm, 'api_base'):
                llm.api_base = api_endpoint
            if model:
                llm.model = model

            ok = await llm.initialize()
            result["success"] = ok
            result["model"] = llm.model
            result["message"] = f"{provider} 连接{'成功' if ok else '失败'}"
        except Exception as e:
            result["message"] = f"连接测试失败: {e}"
        return result

    def switch_to_profile(self, profile) -> bool:
        """切换到指定Profile配置"""
        return self.switch_model(
            provider=profile.provider,
            api_key=profile.api_key,
            model=profile.model,
            api_endpoint=profile.api_endpoint,
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
            top_p=profile.top_p,
        )

    # ── 已保存模型管理 ────────────────────────────────────

    def get_saved_models(self) -> List[Dict[str, Any]]:
        """获取所有已保存的模型配置（API 密钥脱敏）"""
        result = []
        for m in self._saved_models:
            entry = dict(m)
            key = entry.get("api_key", "")
            if key and len(key) > 8:
                entry["api_key"] = key[:4] + "****" + key[-4:]
            elif key:
                entry["api_key"] = "****"
            result.append(entry)
        return result

    def add_saved_model(self, entry: Dict[str, Any]) -> str:
        """添加一个已保存的模型配置，返回 id"""
        entry["id"] = uuid.uuid4().hex[:12]
        self._saved_models.append(entry)
        self._save_config()
        logger.info(f"已保存模型配置: {entry.get('provider')} / {entry.get('model')}")
        return entry["id"]

    def delete_saved_model(self, model_id: str) -> bool:
        """删除已保存的模型配置"""
        before = len(self._saved_models)
        self._saved_models = [m for m in self._saved_models if m.get("id") != model_id]
        if len(self._saved_models) < before:
            self._save_config()
            logger.info(f"已删除模型配置: {model_id}")
            return True
        return False

    def get_saved_model_by_id(self, model_id: str) -> Optional[Dict[str, Any]]:
        """根据 id 查找已保存的模型"""
        for m in self._saved_models:
            if m.get("id") == model_id:
                return dict(m)
        return None

    # ── 状态查询 ──────────────────────────────────────────

    def get_all_providers_status(self) -> list:
        """获取所有提供商的当前状态"""
        statuses = []
        for p in get_available_providers():
            info = get_provider_info(p) or {}
            is_current = p == self._current_provider
            has_key = bool(self.get_api_key(p))
            statuses.append({
                "id": p,
                "name": info.get("name", p),
                "icon": info.get("icon", ""),
                "color": info.get("color", ""),
                "is_current": is_current,
                "has_api_key": has_key,
                "model": self._current_model if is_current else None,
            })
        return statuses


# ── 全局单例 ──────────────────────────────────────────────

_llm_manager_instance: Optional[LLMManager] = None


def get_llm_manager(profile_id: str = "default") -> LLMManager:
    """获取LLMManager实例，per-profile独立实例"""
    global _llm_manager_instance
    if profile_id == "default":
        if _llm_manager_instance is None:
            _llm_manager_instance = LLMManager(profile_id)
        return _llm_manager_instance
    # per-profile独立实例
    return LLMManager(profile_id)


def initialize_llm_with_config(provider: Optional[str] = None, api_key: Optional[str] = None):
    """使用配置初始化 LLM"""
    provider = provider or "tongyi"
    mgr = get_llm_manager()
    if mgr.switch_model(provider, api_key):
        return mgr.get_current_llm()
    return None
