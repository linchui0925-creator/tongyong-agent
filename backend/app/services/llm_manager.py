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
from app.llm.model_metadata import get_model_info
from app.llm.configurable_openai import ConfigurableOpenAICompatibleLLM

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
        self._custom_providers: List[Dict[str, Any]] = []
        self._active_provider_profile_id: Optional[str] = None
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

    @staticmethod
    def is_real_api_key(key: Optional[str]) -> bool:
        """Return False for UI masks and local placeholders that must not be used."""
        if not key:
            return False
        stripped = str(key).strip()
        if not stripped:
            return False
        invalid_values = {"****", "local-placeholder", "placeholder", "undefined", "null"}
        if stripped in invalid_values:
            return False
        if stripped.startswith("YOUR_") or "****" in stripped:
            return False
        return True

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

        custom_provider = self.get_custom_provider(saved_provider)
        saved_entry = None
        try:
            if self._config_file.exists():
                data = json.loads(self._config_file.read_text(encoding="utf-8"))
                for entry in data.get("saved_models", []):
                    if entry.get("provider") == saved_provider and entry.get("model") == saved_model:
                        saved_entry = entry
                        break
        except Exception:
            saved_entry = None

        entry_key = (saved_entry or {}).get("api_key")
        api_key = (
            entry_key if self.is_real_api_key(entry_key)
            else (custom_provider or {}).get("api_key")
            or self.get_api_key(saved_provider)
        )
        if not api_key:
            logger.warning(f"已保存的 provider {saved_provider} 无 API key")
            return False

        try:
            if custom_provider:
                llm = self._custom_provider_to_llm(custom_provider, api_key, saved_model, saved_endpoint)
            else:
                from app.llm.factory import get_llm
                llm = get_llm(saved_provider, api_key, saved_model)
            if saved_model:
                llm.model = saved_model
            if saved_endpoint and hasattr(llm, 'api_base'):
                llm.api_base = saved_endpoint
            self._current_llm = llm
            self._current_provider = saved_provider
            self._current_model = saved_model
            self._active_provider_profile_id = saved_provider if custom_provider else None
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
            if self._current_llm is not None and hasattr(self._agent_engine_ref, "context_compressor"):
                info = get_model_info(getattr(self._current_llm, "model", "") or "")
                if info and info.context_window:
                    self._agent_engine_ref.context_compressor.context_length = info.context_window
                    self._agent_engine_ref.context_compressor.threshold_tokens = int(
                        info.context_window * self._agent_engine_ref.context_compressor.threshold_percent
                    )
            logger.debug(f"LLMManager[{self.profile_id}] 同步到 AgentEngine")

    # ── 配置持久化 ────────────────────────────────────────

    def _load_config(self) -> None:
        """从文件加载配置"""
        try:
            if self._config_file.exists():
                data = json.loads(self._config_file.read_text(encoding="utf-8"))
                self._api_keys = data.get("api_keys", {})
                self._saved_models = data.get("saved_models", [])
                self._custom_providers = data.get("custom_providers", [])
                self._active_provider_profile_id = data.get("active_provider_profile_id")
                saved_provider = data.get("provider")
                if saved_provider and (saved_provider in get_available_providers() or self.get_custom_provider(saved_provider)):
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
                "custom_providers": self._custom_providers,
                "active_provider_profile_id": self._active_provider_profile_id,
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
            if self.is_real_api_key(key):
                return key
        from app.llm.factory import _get_default_api_key
        key = _get_default_api_key(provider)
        if key:
            self._api_keys[provider] = key
        return key

    def set_api_key(self, provider: str, api_key: str) -> None:
        """设置并持久化指定 provider 的 API 密钥"""
        if self.is_real_api_key(api_key):
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
        custom_provider = self.get_custom_provider(self._current_provider)
        return {
            "provider": self._current_provider,
            "model": self._current_model,
            "api_key_configured": bool((custom_provider or {}).get("api_key") or self.get_api_key(self._current_provider)),
            "provider_profile_id": self._active_provider_profile_id,
        }

    # ── 自定义供应商管理 ──────────────────────────────────

    @staticmethod
    def _mask_key(key: Optional[str]) -> str:
        if not key:
            return ""
        if len(key) <= 8:
            return "****"
        return f"{key[:4]}****{key[-4:]}"

    def _public_custom_provider(self, provider: Dict[str, Any]) -> Dict[str, Any]:
        item = dict(provider)
        key = item.pop("api_key", "")
        item["has_api_key"] = bool(key)
        item["api_key_masked"] = self._mask_key(key)
        return item

    def list_custom_providers(self) -> List[Dict[str, Any]]:
        import os
        import json
        from pathlib import Path
        # 从config目录读取自定义供应商配置
        custom_config_dir = Path('config/providers')
        custom_config_dir.mkdir(parents=True, exist_ok=True)
        # 读取所有json配置文件
        for config_file in custom_config_dir.glob('*.json'):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    provider_config = json.load(f)
                    if all(k in provider_config for k in ['id', 'name', 'endpoint', 'model']):
                        builtin_providers.append({
                            'id': provider_config['id'],
                            'name': provider_config.get('name', provider_config['id']),
                            'protocol': provider_config.get('protocol', 'openai_compatible'),
                            'base_url': provider_config['endpoint'],
                            'default_model': provider_config['model'],
                            'models': provider_config.get('models', [provider_config['model']]),
                            'icon': provider_config.get('icon', '⚙️'),
                            'color': provider_config.get('color', '#7C3AED'),
                            'enabled': provider_config.get('enabled', True),
                            'has_api_key': bool(provider_config.get('api_key') or os.getenv(f'{provider_config[id].upper()}_API_KEY')),
                            'api_key': provider_config.get('api_key') or os.getenv(f'{provider_config[id].upper()}_API_KEY'),
                        })
            except Exception as e:
                logger.warning(f'加载自定义供应商配置{config_file}失败: {e}')
        builtin_providers = []
        # EdgeFn GLM
        if os.getenv('EDGEFN_API_KEY'):
            builtin_providers.append({
                'id': 'edgefn',
                'name': 'EdgeFn GLM-5.2',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.edgefn.net/v1',
                'default_model': 'GLM-5.2',
                'models': ['GLM-5.2', 'GLM-4.5V'],
                'icon': '🌐',
                'color': '#165DFF',
                'enabled': True,
                'has_api_key': True,
            })
        # DeepSeek
        if os.getenv('DEEPSEEK_API_KEY'):
            builtin_providers.append({
                'id': 'deepseek',
                'name': 'DeepSeek V3',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.deepseek.com/v1',
                'default_model': 'deepseek-chat',
                'models': ['deepseek-chat', 'deepseek-coder'],
                'icon': '🔍',
                'color': '#2563EB',
                'enabled': True,
                'has_api_key': True,
            })
        # 豆包Doubao
        if os.getenv('DOUBAO_API_KEY'):
            builtin_providers.append({
                'id': 'doubao',
                'name': '字节豆包',
                'protocol': 'openai_compatible',
                'base_url': 'https://ark.cn-beijing.volces.com/api/plan/v1',
                'default_model': 'doubao-pro-32k',
                'models': ['doubao-pro-32k', 'doubao-lite-128k'],
                'icon': '📦',
                'color': '#22C55E',
                'enabled': True,
                'has_api_key': True,
            })
        # OpenAI
        if os.getenv('OPENAI_API_KEY'):
            builtin_providers.append({
                'id': 'openai',
                'name': 'OpenAI GPT',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.openai.com/v1',
                'default_model': 'gpt-4o',
                'models': ['gpt-4o', 'gpt-4o-mini', 'gpt-3.5-turbo'],
                'icon': '🤖',
                'color': '#10A37F',
                'enabled': True,
                'has_api_key': True,
            })
        # 通义千问
        if os.getenv('DASHSCOPE_API_KEY'):
            builtin_providers.append({
                'id': 'qwen',
                'name': '阿里通义千问',
                'protocol': 'openai_compatible',
                'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                'default_model': 'qwen-max',
                'models': ['qwen-max', 'qwen-plus', 'qwen-long'],
                'icon': '☁️',
                'color': '#FF6A00',
                'enabled': True,
                'has_api_key': True,
            })
        # 把内置供应商和自定义供应商合并返回
        return builtin_providers + [self._public_custom_provider(p) for p in self._custom_providers]


    def get_custom_provider(self, provider_id: str) -> Optional[Dict[str, Any]]:
        for provider in self._custom_providers:
            if provider.get("id") == provider_id:
                return dict(provider)
        return None

    def upsert_custom_provider(self, data: Dict[str, Any]) -> Dict[str, Any]:
        provider = dict(data)
        provider_id = provider.get("id") or f"custom_{uuid.uuid4().hex[:10]}"
        provider["id"] = provider_id
        provider.setdefault("protocol", "openai_compatible")
        provider.setdefault("enabled", True)
        provider.setdefault("models", [])
        provider.setdefault("request_config", {})
        provider.setdefault("icon", "⚙")
        provider.setdefault("color", "#7C3AED")
        if not self.is_real_api_key(provider.get("api_key")):
            provider.pop("api_key", None)
            old = self.get_custom_provider(provider_id)
            if old and old.get("api_key"):
                provider["api_key"] = old["api_key"]

        replaced = False
        for idx, existing in enumerate(self._custom_providers):
            if existing.get("id") == provider_id:
                self._custom_providers[idx] = provider
                replaced = True
                break
        if not replaced:
            self._custom_providers.append(provider)
        self._save_config()
        return self._public_custom_provider(provider)

    def delete_custom_provider(self, provider_id: str) -> bool:
        before = len(self._custom_providers)
        self._custom_providers = [p for p in self._custom_providers if p.get("id") != provider_id]
        if len(self._custom_providers) < before:
            if self._active_provider_profile_id == provider_id:
                self._active_provider_profile_id = None
            if self._current_provider == provider_id:
                self._current_provider = "tongyi"
                self._current_model = None
                self._current_llm = None
            self._save_config()
            return True
        return False

    def _custom_provider_to_llm(
        self,
        provider: Dict[str, Any],
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        api_endpoint: Optional[str] = None,
    ) -> BaseLLM:
        chosen_model = model or provider.get("default_model") or (provider.get("models") or [{}])[0].get("id")
        resolved_key = api_key if self.is_real_api_key(api_key) else provider.get("api_key")
        llm = ConfigurableOpenAICompatibleLLM(
            api_key=resolved_key or "",
            model=chosen_model,
            provider_id=provider["id"],
            base_url=api_endpoint or provider.get("base_url") or "https://api.openai.com/v1",
            request_config=provider.get("request_config") or {},
            model_overrides=provider.get("model_overrides") or {},
        )
        return llm

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
            custom_provider = self.get_custom_provider(provider)
            if provider not in available and not custom_provider:
                logger.error(f"提供商 {provider} 不可用，可用: {available}")
                return False

            resolved_key = (
                api_key if self.is_real_api_key(api_key)
                else (custom_provider or {}).get("api_key")
                or self.get_api_key(provider)
            )
            if not resolved_key:
                logger.warning(f"{provider} 未配置 API 密钥")

            llm = self._custom_provider_to_llm(custom_provider, resolved_key, model, api_endpoint) if custom_provider else get_llm(provider, resolved_key)
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
            self._current_model = model or llm.model
            self._active_provider_profile_id = provider if custom_provider else None

            if self.is_real_api_key(api_key):
                if custom_provider:
                    custom_provider["api_key"] = api_key
                    self.upsert_custom_provider(custom_provider)
                else:
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
            custom_provider = self.get_custom_provider(provider)
            resolved_key = (
                api_key if self.is_real_api_key(api_key)
                else (custom_provider or {}).get("api_key")
                or self.get_api_key(provider)
            )
            llm = self._custom_provider_to_llm(custom_provider, resolved_key, model, api_endpoint) if custom_provider else get_llm(provider, resolved_key)
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
        if not self.is_real_api_key(entry.get("api_key")):
            entry.pop("api_key", None)
        entry["id"] = uuid.uuid4().hex[:12]
        self._saved_models = [
            m for m in self._saved_models
            if not (
                m.get("provider") == entry.get("provider")
                and m.get("model") == entry.get("model")
                and (m.get("api_endpoint") or "") == (entry.get("api_endpoint") or "")
            )
        ]
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
        for provider in self._custom_providers:
            p = provider.get("id")
            is_current = p == self._current_provider
            statuses.append({
                "id": p,
                "name": provider.get("name", p),
                "icon": provider.get("icon", "⚙"),
                "color": provider.get("color", "#7C3AED"),
                "is_current": is_current,
                "has_api_key": bool(provider.get("api_key")),
                "model": self._current_model if is_current else provider.get("default_model"),
                "custom": True,
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
