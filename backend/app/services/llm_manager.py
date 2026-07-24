"""
LLM 管理器，统一管理所有供应商、模型、配置
完全对齐前端预设供应商格式
"""
import os
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from app.llm.base import BaseLLM
from app.llm.openai_compatible import OpenAICompatibleLLM
from app.llm.request_contract import ModelRequestOptions, GenerationControls
from app.services.provider_catalog import ENV_PREFIX_MAP, BUILTIN_CONFIGS
from app.paths import data_path
import logging
logger = logging.getLogger(__name__)

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None

try:
    import toml
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    toml = None

class LLMManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        # 加载配置文件
        self.config = self._load_config()
        # 内置预设供应商，和前端完全对齐
        self.builtin_providers = self._load_builtin_providers()
        # 用户自定义供应商
        self._custom_providers = self._load_custom_providers()
        # 已初始化的LLM实例缓存
        self._llm_cache: Dict[str, BaseLLM] = {}


    def bind_agent_engine(self, engine):
        """绑定AgentEngine实例"""
        self._agent_engine = engine

    def try_restore_saved_provider(self):
        """Restore a complete runtime config from llm_config.json.

        Backward compatible with old files that only stored provider/model.
        """
        try:
            cfg_path = Path(data_path("llm_config.json"))
            if not cfg_path.exists():
                return None
            saved = json.loads(cfg_path.read_text(encoding="utf-8") or "{}")
            provider = saved.get("provider")
            if not provider:
                return None
            runtime = self.build_runtime_config(
                provider=provider,
                model=saved.get("model"),
                api_key=(saved.get("api_key") or None),
                api_endpoint=saved.get("api_endpoint") or saved.get("api_base"),
                request_config=saved.get("request_config") or {},
            )
            profile_id = saved.get("active_provider_profile_id")
            if profile_id:
                runtime["provider_profile_id"] = profile_id
            return runtime
        except Exception as e:
            logger.warning(f"try_restore_saved_provider failed: {e}")
            return None

    def _seed_initial_llm(self, llm_instance, provider_name):
        """记录启动时注入的 LLM，作为 get_current_llm() 的兜底。"""
        if llm_instance is not None:
            self._current_llm = llm_instance
            if not getattr(self, "_current_model", None):
                self._current_model = getattr(llm_instance, "model", None)
        if provider_name:
            self._current_provider = provider_name

    def _sync_to_agent(self):
        """把当前 LLM 同步到 agent engine。"""
        engine = getattr(self, "_agent_engine", None)
        if engine is not None and getattr(self, "_current_llm", None) is not None:
            engine.llm = self._current_llm

    # ── 当前状态查询（替换硬编码 stub）───────────────────────
    def _default_provider(self) -> str:
        return getattr(self, "config", {}).get("default_provider", "edgefn")

    def _default_model(self) -> str:
        # W5-2 (2026-07-09): 兜底默认模型从 glm-5.2 → GLM-4.5V,
        # 配合 edgefn.py 的 HARDCODED_API_KEY, 部署不配 llm_config.json 也能跑
        return getattr(self, "config", {}).get("default_model", "GLM-4.5V")

    def _default_model_for(self, provider_id: str) -> str:
        for p in getattr(self, "builtin_providers", []):
            if p.get("id") == provider_id:
                return p.get("default_model") or "gpt-4o-mini"
        for p in getattr(self, "_custom_providers", []):
            if p.get("id") == provider_id:
                return p.get("default_model") or "gpt-4o-mini"
        return "gpt-4o-mini"

    def get_current_provider(self) -> str:
        return getattr(self, "_current_provider", None) or self._default_provider()

    def get_current_model(self) -> str:
        return getattr(self, "_current_model", None) or self._default_model()

    def get_current_llm(self):
        return getattr(self, "_current_llm", None)

    def _infer_api_format(self, llm: Optional[BaseLLM]) -> str:
        if llm is None:
            return "chat_completions"
        request_config = getattr(llm, "request_config", {}) or {}
        explicit = request_config.get("api_format")
        if explicit:
            return str(explicit)
        api_base = str(getattr(llm, "api_base", "")).lower()
        if "anthropic" in api_base:
            return "anthropic"
        if "/responses" in api_base:
            return "openai_responses"
        return "chat_completions"

    def _infer_stream_mode(self, llm: Optional[BaseLLM]) -> str:
        if llm is None:
            return "unknown"
        request_config = getattr(llm, "request_config", {}) or {}
        explicit = str(request_config.get("stream_mode") or "").strip().lower()
        if explicit in {"native", "fallback", "proxy", "mock", "disabled"}:
            return explicit
        api_format = self._infer_api_format(llm)
        api_base = str(getattr(llm, "api_base", "")).lower()
        model = str(getattr(llm, "model", "")).lower()
        if api_format == "anthropic":
            return "native"
        if api_format == "openai_responses":
            return "native"
        if "ollama" in api_base or "localhost:11434" in api_base:
            return "native"
        if any(token in api_base for token in ["edgefn", "openrouter", "siliconflow", "therouter", "apikey.fun", "api.apikey.fun", "api.apinebula", "api.ccsub", "api.patewayai"]):
            return "proxy"
        if any(token in model for token in ["deepseek-v4", "glm-5", "reasoning"]):
            return "native"
        return "native"

    def get_current_runtime_config(self) -> Dict[str, Any]:
        provider = self.get_current_provider()
        model = self.get_current_model()
        llm = self.get_current_llm()
        request_config = getattr(llm, "request_config", {}) if llm is not None else {}
        return {
            "provider": provider,
            "model": model,
            "api_key_configured": bool(self.get_api_key(provider)),
            "provider_profile_id": getattr(self, "_current_provider_profile_id", None),
            "api_format": self._infer_api_format(llm),
            "stream_mode": self._infer_stream_mode(llm),
            "api_base": getattr(llm, "api_base", None) if llm is not None else None,
            "request_config": request_config,
        }

    def build_request_options(self) -> ModelRequestOptions:
        runtime = self.get_current_runtime_config()
        request_cfg = runtime.get("request_config", {}) or {}
        controls = GenerationControls(
            temperature=request_cfg.get("temperature"),
            top_p=request_cfg.get("top_p"),
            max_tokens=request_cfg.get("max_tokens"),
            stop=request_cfg.get("stop"),
        )
        return ModelRequestOptions(
            model=runtime["model"],
            provider=runtime["provider"],
            api_format=runtime.get("api_format", "chat_completions"),
            stream_mode=runtime.get("stream_mode", "native"),
            controls=controls,
            provider_fields={
                "api_base": runtime.get("api_base"),
                "provider_profile_id": runtime.get("provider_profile_id"),
                **request_cfg,
            },
        )

    def build_request_options_for(self, provider: str, model: Optional[str] = None, api_endpoint: Optional[str] = None) -> ModelRequestOptions:
        llm = self.get_llm(provider, model=model, api_endpoint=api_endpoint)
        runtime = {
            "provider": provider,
            "model": model or getattr(llm, "model", self.get_current_model()),
            "api_format": self._infer_api_format(llm),
            "stream_mode": self._infer_stream_mode(llm),
            "api_base": getattr(llm, "api_base", None),
            "provider_profile_id": getattr(self, "_current_provider_profile_id", None),
            "request_config": getattr(llm, "request_config", {}) or {},
        }
        request_cfg = runtime.get("request_config", {}) or {}
        controls = GenerationControls(
            temperature=request_cfg.get("temperature"),
            top_p=request_cfg.get("top_p"),
            max_tokens=request_cfg.get("max_tokens"),
            stop=request_cfg.get("stop"),
        )
        return ModelRequestOptions(
            model=runtime["model"],
            provider=runtime["provider"],
            api_format=runtime.get("api_format", "chat_completions"),
            stream_mode=runtime.get("stream_mode", "native"),
            controls=controls,
            provider_fields={
                "api_base": runtime.get("api_base"),
                "provider_profile_id": runtime.get("provider_profile_id"),
                **request_cfg,
            },
        )

    def get_current_config(self) -> Dict[str, Any]:
        runtime = self.get_current_runtime_config()
        return {
            "provider": runtime["provider"],
            "model": runtime["model"],
            "api_key_configured": runtime["api_key_configured"],
            "provider_profile_id": runtime["provider_profile_id"],
        }

    @staticmethod
    def _is_usable_api_key(key: Optional[str]) -> bool:
        if not key or not isinstance(key, str):
            return False
        k = key.strip()
        if not k:
            return False
        upper = k.upper()
        if upper in {"YOUR_API_KEY", "YOUR..._KEY", "NONE", "NULL", "TODO"}:
            return False
        if "YOUR_API_KEY" in upper or upper.startswith("YOUR"):
            return False
        return True

    def get_api_key(self, provider: str) -> Optional[str]:
        """Resolve API key from a single ordered chain.

        Order:
        1. true custom provider profile
        2. llm_config.json api_keys
        3. builtin provider dict / config.toml / env loaded into builtin_providers
        4. environment variable PROVIDER_API_KEY
        5. app.config settings (includes edgefn default)
        """
        if not provider:
            return None

        for p in getattr(self, "_custom_providers", []):
            if p.get("id") == provider and self._is_usable_api_key(p.get("api_key")):
                return p["api_key"]

        try:
            cfg_path = Path(data_path("llm_config.json"))
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8") or "{}")
                k = (cfg.get("api_keys") or {}).get(provider)
                if self._is_usable_api_key(k):
                    return k
        except Exception:
            pass

        for p in getattr(self, "builtin_providers", []):
            if p.get("id") == provider and self._is_usable_api_key(p.get("api_key")):
                return p["api_key"]

        env_key = os.environ.get(f"{provider.upper()}_API_KEY")
        if self._is_usable_api_key(env_key):
            return env_key

        try:
            from app.config import settings
            from app.llm.factory import _get_default_api_key
            settings_key = _get_default_api_key(provider)
            if self._is_usable_api_key(settings_key):
                return settings_key
            # edgefn hardcoded fallback only when settings is empty
            if provider == "edgefn":
                from app.llm.edgefn import EdgeFnLLM
                if self._is_usable_api_key(getattr(EdgeFnLLM, "HARDCODED_API_KEY", None)):
                    return EdgeFnLLM.HARDCODED_API_KEY
            _ = settings  # keep import used for future extension
        except Exception:
            pass
        return None

    def get_saved_models(self) -> List[Dict[str, Any]]:
        """读取 data/llm_config.json 里的 saved_models 列表。"""
        try:
            cfg_path = Path(data_path("llm_config.json"))
            if not cfg_path.exists():
                return []
            cfg = json.loads(cfg_path.read_text(encoding="utf-8") or "{}")
            return cfg.get("saved_models") or []
        except Exception as e:
            logger.warning(f"get_saved_models failed: {e}")
            return []

    def add_saved_model(self, entry: Dict[str, Any]) -> str:
        """往 data/llm_config.json 加一条 saved_model，返回 entry.id。"""
        cfg_path = Path(data_path("llm_config.json"))
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        except Exception:
            cfg = {}
        cfg.setdefault("saved_models", [])
        entry_id = entry.get("id") or os.urandom(6).hex()
        entry["id"] = entry_id
        cfg["saved_models"].append(entry)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return entry_id

    def delete_saved_model(self, model_id: str) -> bool:
        cfg_path = Path(data_path("llm_config.json"))
        if not cfg_path.exists():
            return False
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        before = len(cfg.get("saved_models", []))
        cfg["saved_models"] = [m for m in cfg.get("saved_models", []) if m.get("id") != model_id]
        if len(cfg["saved_models"]) == before:
            return False
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def get_saved_model_by_id(self, model_id: str) -> Optional[Dict[str, Any]]:
        for m in self.get_saved_models():
            if m.get("id") == model_id:
                return m
        return None

    def is_real_api_key(self, key: Optional[str]) -> bool:
        """判断 api_key 是否是用户实际填的（排除 YOUR_API_KEY / sk-placeholder / sk-test）。"""
        if not key:
            return False
        bad = {"YOUR_API_KEY", "sk-placeholder", "sk-xxx", "sk-test", "sk-x", "sk-openai-test-123"}
        return key not in bad

    # ── provider 状态枚举 + 切换 ──────────────────────────────
    def get_all_providers_status(self) -> List[Dict[str, Any]]:
        """返回所有 builtin + custom provider 的 UI 展示信息（带 is_current / has_api_key 标记）。"""
        current = self.get_current_provider()
        result: List[Dict[str, Any]] = []
        for p in getattr(self, "builtin_providers", []):
            result.append({
                "id": p["id"],
                "name": p.get("name", p["id"]),
                "icon": p.get("icon", ""),
                "color": p.get("color", "#7C3AED"),
                "is_current": p["id"] == current,
                "has_api_key": bool(self.get_api_key(p["id"])),
                "model": p.get("default_model"),
                "type": "builtin",
            })
        for p in getattr(self, "_custom_providers", []):
            result.append({
                "id": p["id"],
                "name": p.get("name", p["id"]),
                "icon": p.get("icon", "⚙️"),
                "color": p.get("color", "#7C3AED"),
                "is_current": p["id"] == current,
                "has_api_key": bool(p.get("api_key")),
                "model": p.get("default_model"),
                "type": "custom",
            })
        return result

    def _is_true_custom_provider(self, provider_id: str) -> bool:
        return any(p.get("id") == provider_id for p in getattr(self, "_custom_providers", []))

    def _is_builtin_provider(self, provider_id: str) -> bool:
        return any(p.get("id") == provider_id for p in getattr(self, "builtin_providers", []))

    def _default_api_base_for(self, provider_id: str) -> Optional[str]:
        for p in getattr(self, "builtin_providers", []):
            if p.get("id") == provider_id and p.get("base_url"):
                return p.get("base_url")
        for p in getattr(self, "_custom_providers", []):
            if p.get("id") == provider_id and p.get("base_url"):
                return p.get("base_url")
        if provider_id == "edgefn":
            return "https://api.edgefn.net/v1"
        if provider_id == "openai":
            return "https://api.openai.com/v1"
        if provider_id == "deepseek":
            return "https://api.deepseek.com/v1"
        if provider_id == "minimax":
            return "https://api.minimaxi.com/v1"
        return None

    def build_runtime_config(
        self,
        provider: str,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        api_endpoint: Optional[str] = None,
        request_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build one complete runtime config blob used to rebuild the LLM."""
        is_custom = self._is_true_custom_provider(provider)
        profile = None
        if is_custom:
            profile = next((p for p in self._custom_providers if p.get("id") == provider), None)
        else:
            profile = next((p for p in self.builtin_providers if p.get("id") == provider), None)

        resolved_model = (
            model
            or (profile or {}).get("default_model")
            or self._default_model_for(provider)
            or self._default_model()
        )
        resolved_key = api_key if self._is_usable_api_key(api_key) else self.get_api_key(provider)
        resolved_base = (
            api_endpoint
            or (profile or {}).get("base_url")
            or self._default_api_base_for(provider)
        )
        resolved_request = request_config if request_config is not None else dict((profile or {}).get("request_config") or {})

        return {
            "provider": provider,
            "model": resolved_model,
            "api_key": resolved_key or "",
            "api_base": resolved_base,
            "request_config": resolved_request,
            "provider_profile_id": provider if is_custom else None,
            "is_custom": is_custom,
            "is_builtin": self._is_builtin_provider(provider) or (not is_custom),
        }

    def _llm_from_runtime_config(self, runtime: Dict[str, Any]) -> BaseLLM:
        """Create a fresh LLM instance only from a complete runtime config."""
        provider = runtime["provider"]
        model = runtime.get("model")
        api_key = runtime.get("api_key") or None
        api_base = runtime.get("api_base")
        request_config = runtime.get("request_config") or {}

        # True custom profiles stay on OpenAI-compatible adapter.
        if runtime.get("is_custom"):
            llm = OpenAICompatibleLLM(api_key=api_key or "", model=model)
            if api_base:
                llm.api_base = api_base
            llm.request_config = request_config
            return llm

        # Builtin / factory-registered providers must use their own class
        # (EdgeFnLLM hardcode fallback, protocol specifics, etc.).
        from app.llm.factory import get_llm as _factory_get_llm
        llm = _factory_get_llm(provider, api_key=api_key if self._is_usable_api_key(api_key) else None, model=model)
        # Factory implementations may normalize/replace the constructor key. Re-apply
        # the resolved runtime key so test/chat/voice use the exact same credential.
        if self._is_usable_api_key(api_key):
            llm.api_key = api_key
        if model:
            llm.model = model
        if api_base and hasattr(llm, "api_base"):
            llm.api_base = api_base
        if request_config is not None:
            llm.request_config = request_config
        # Final key safety net for edgefn if factory still got empty key
        if provider == "edgefn" and not self._is_usable_api_key(getattr(llm, "api_key", None)):
            from app.llm.edgefn import EdgeFnLLM
            llm.api_key = EdgeFnLLM.HARDCODED_API_KEY
        return llm

    def apply_runtime_config(self, runtime: Dict[str, Any], persist: bool = True) -> BaseLLM:
        """Replace current LLM runtime from one complete config and optionally persist."""
        llm = self._llm_from_runtime_config(runtime)
        self._current_provider = runtime["provider"]
        self._current_model = runtime.get("model")
        self._current_llm = llm
        self._current_provider_profile_id = runtime.get("provider_profile_id")
        self._current_runtime_config = dict(runtime)
        # Never keep raw key in memory dump fields returned to clients
        if isinstance(self._current_runtime_config, dict):
            self._current_runtime_config = {
                **self._current_runtime_config,
                "api_key_configured": self._is_usable_api_key(runtime.get("api_key")),
            }
            self._current_runtime_config.pop("api_key", None)

        engine = getattr(self, "_agent_engine", None)
        if engine is not None:
            engine.llm = llm

        # Drop stale cache entries for this provider so later get_llm rebuilds cleanly
        stale = [k for k in list(self._llm_cache.keys()) if k.startswith(f"{runtime['provider']}:")]
        for k in stale:
            self._llm_cache.pop(k, None)

        if persist:
            try:
                cfg_path = Path(data_path("llm_config.json"))
                saved = json.loads(cfg_path.read_text(encoding="utf-8") or "{}") if cfg_path.exists() else {}
                saved["provider"] = runtime["provider"]
                saved["model"] = runtime.get("model")
                if runtime.get("provider_profile_id"):
                    saved["active_provider_profile_id"] = runtime["provider_profile_id"]
                else:
                    saved.pop("active_provider_profile_id", None)
                # Keep endpoint hint for non-default bases (no secrets)
                if runtime.get("api_base"):
                    saved["api_endpoint"] = runtime.get("api_base")
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                cfg_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning("apply_runtime_config 持久化失败: %s", e)
        return llm

    def switch_model(self, provider: str, api_key: Optional[str] = None, model: Optional[str] = None, **kwargs) -> bool:
        """切换当前 LLM：先组装完整 runtime config，再重建 LLM 实例。"""
        try:
            endpoint = kwargs.get("api_endpoint")
            request_config = kwargs.get("request_config")
            runtime = self.build_runtime_config(
                provider=provider,
                model=model,
                api_key=api_key,
                api_endpoint=endpoint,
                request_config=request_config,
            )
            # Builtin without any usable key: still allow edgefn hardcode path via factory
            if not self._is_usable_api_key(runtime.get("api_key")) and provider != "edgefn" and not runtime.get("is_custom"):
                # custom can still rely on empty and fail later; builtin needs key except edgefn
                if not runtime.get("is_custom"):
                    logger.warning("switch_model: provider %s 无可用 API key", provider)
            self.apply_runtime_config(runtime, persist=True)
            logger.info(
                "switch_model rebuilt runtime | provider=%s model=%s api_base=%s key=%s",
                runtime.get("provider"),
                runtime.get("model"),
                runtime.get("api_base"),
                "yes" if self._is_usable_api_key(runtime.get("api_key")) else "no",
            )
            return True
        except Exception as e:
            logger.error("switch_model 失败: %s", e, exc_info=True)
            return False

    def _load_config(self) -> Dict[str, Any]:
        """加载config.toml配置文件"""
        config_path = Path("config.toml")
        if not config_path.exists():
            config_path = Path("config.example.toml")
        try:
            if config_path.exists():
                logger.info(f"加载配置文件: {config_path.absolute()}")
                if tomllib is not None:
                    with config_path.open("rb") as f:
                        return tomllib.load(f)
                if toml is not None:
                    return toml.load(config_path)
                logger.warning("未安装 toml 且当前 Python 无 tomllib，使用默认配置")
            return {}
        except Exception as e:
            logger.warning(f"加载配置文件失败: {e}，使用默认配置")
            return {}

    def _load_builtin_providers(self) -> List[Dict[str, Any]]:
        """加载内置预设供应商，和前端TEMPLATE_OPTIONS完全对齐"""
        builtin: List[Dict[str, Any]] = []
        # 从环境变量加载
        # 静态目录数据已抽到 app/services/provider_catalog.py。
        # 这里只做 env / config.toml 的 API Key 与 base_url override。
        import copy
        env_prefix_map = ENV_PREFIX_MAP
        builtin_configs = copy.deepcopy(BUILTIN_CONFIGS)
        # 合并环境变量中的API Key
        for provider in builtin_configs:
            # 优先从环境变量加载
            env_key = env_prefix_map.get(provider['id'])
            if env_key and os.getenv(env_key):
                provider['api_key'] = os.getenv(env_key)
                provider['has_api_key'] = True
            # 其次从config.toml加载
            config_providers = self.config.get('model_providers', {})
            if provider['id'] in config_providers:
                config = config_providers[provider['id']]
                if config.get('api_key'):
                    provider['api_key'] = config['api_key']
                    provider['has_api_key'] = True
                if config.get('base_url'):
                    provider['base_url'] = config['base_url']
                if config.get('default_model'):
                    provider['default_model'] = config['default_model']
            builtin.append(provider)
        return builtin

    def _load_custom_providers(self) -> List[Dict[str, Any]]:
        """加载用户自定义供应商"""
        custom_path = Path(data_path("custom_providers.json"))
        if not custom_path.exists():
            return []
        try:
            with open(custom_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载自定义供应商失败: {e}")
            return []

    def _save_custom_providers(self):
        """保存自定义供应商到文件"""
        custom_path = Path(data_path("custom_providers.json"))
        custom_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(custom_path, "w", encoding="utf-8") as f:
                json.dump(self._custom_providers, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存自定义供应商失败: {e}")

    @staticmethod
    def _mask_key(key: Optional[str]) -> Optional[str]:
        """把 API Key 脱敏成 sk-XX...YY 这种形式，方便 UI 展示"已配置"。
        真实 key 永远不返回给前端；用户不输入新值就保存时后端会沿用旧 key。
        """
        if not key:
            return None
        if len(key) <= 10:
            return '***'
        return f"{key[:4]}...{key[-4:]}"

    def _public_custom_provider(self, provider: Dict[str, Any]) -> Dict[str, Any]:
        """返回脱敏的公共供应商信息。
        - 不返回原始 api_key（避免泄露）
        - 返回 api_key_masked 给前端显示"已配置 sk-XX...YY"
        - 返回 has_api_key 布尔供 UI 决策
        - 保存时如果前端没传 api_key，调用方应用旧 key 兜底（见 upsert_custom_provider）
        """
        public = {k: v for k, v in provider.items() if k != 'api_key'}
        raw_key = provider.get('api_key')
        public['has_api_key'] = bool(raw_key)
        public['api_key_masked'] = self._mask_key(raw_key)
        return public

    def list_custom_providers(self) -> List[Dict[str, Any]]:
        """获取所有可用供应商列表（内置+自定义），自动过滤未配置API Key的内置供应商"""
        # 自定义供应商全部返回
        custom = [self._public_custom_provider(p) for p in self._custom_providers]
        # 内置供应商只返回配置了API Key的
        builtin = [
            self._public_custom_provider(p)
            for p in self.builtin_providers
            if p.get('has_api_key', False)
        ]
        return builtin + custom

    def get_custom_provider(self, provider_id: str) -> Optional[Dict[str, Any]]:
        """获取指定供应商配置"""
        for p in self.builtin_providers:
            if p['id'] == provider_id:
                return p.copy()
        for p in self._custom_providers:
            if p['id'] == provider_id:
                return p.copy()
        return None

    def upsert_custom_provider(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """创建或更新自定义供应商。
        关键约定: 如果 data 里没传 api_key 但旧记录里有，则沿用旧 key。
        这让前端在编辑已有 provider 时可以选择不重输 key(避免误清空)。
        """
        provider_id = data.get('id') or f"custom_{os.urandom(4).hex()}"
        # 检查是否是内置供应商，不允许修改
        for p in self.builtin_providers:
            if p['id'] == provider_id:
                raise ValueError("内置供应商不允许修改")
        provider = dict(data)
        provider['id'] = provider_id
        provider.setdefault('protocol', 'openai_compatible')
        provider.setdefault('enabled', True)
        provider.setdefault('models', [])
        provider.setdefault('request_config', {})
        provider.setdefault('icon', '⚙️')
        provider.setdefault('color', '#7C3AED')
        # 如果新数据没传 api_key 但已有旧记录，沿用旧 key（避免编辑时丢失）
        existing = next((p for p in self._custom_providers if p.get('id') == provider_id), None)
        if not provider.get('api_key') and existing and existing.get('api_key'):
            provider['api_key'] = existing['api_key']
        # 替换旧的
        for i, p in enumerate(self._custom_providers):
            if p['id'] == provider_id:
                self._custom_providers[i] = provider
                self._save_custom_providers()
                return self._public_custom_provider(provider)
        # 新增
        self._custom_providers.append(provider)
        self._save_custom_providers()
        return self._public_custom_provider(provider)

    def delete_custom_provider(self, provider_id: str) -> bool:
        """删除自定义供应商"""
        for i, p in enumerate(self._custom_providers):
            if p['id'] == provider_id:
                del self._custom_providers[i]
                self._save_custom_providers()
                # 清除缓存
                self._llm_cache.pop(provider_id, None)
                return True
        return False

    def _custom_provider_to_llm(self, provider: Dict[str, Any], api_key: Optional[str] = None, model: Optional[str] = None, api_endpoint: Optional[str] = None) -> BaseLLM:
        """将真正的自定义供应商配置转换为LLM实例。"""
        runtime = self.build_runtime_config(
            provider=provider.get("id") or "custom",
            model=model or provider.get("default_model"),
            api_key=api_key or provider.get("api_key"),
            api_endpoint=api_endpoint or provider.get("base_url"),
            request_config=provider.get("request_config") or {},
        )
        # Force custom path even if id collides
        runtime["is_custom"] = True
        runtime["is_builtin"] = False
        return self._llm_from_runtime_config(runtime)

    def _build_llm_for(self, provider_id: str, api_key: Optional[str] = None, model: Optional[str] = None, api_endpoint: Optional[str] = None):
        """根据 provider_id 构造 LLM 实例。

        重要：builtin 不能再误走 custom OpenAICompatible 路径，
        否则 edgefn 等会丢掉类级兜底 key / 协议细节。
        """
        runtime = self.build_runtime_config(
            provider=provider_id,
            model=model,
            api_key=api_key,
            api_endpoint=api_endpoint,
        )
        try:
            return self._llm_from_runtime_config(runtime)
        except Exception as e:
            raise ValueError(f"供应商 {provider_id} 不存在或 factory 未注册: {e}")

    def get_llm(self, provider: str, api_key: Optional[str] = None, model: Optional[str] = None, api_endpoint: Optional[str] = None) -> BaseLLM:
        """获取LLM实例，优先从缓存读取"""
        resolved_key = api_key if self._is_usable_api_key(api_key) else self.get_api_key(provider)
        cache_key = f"{provider}:{model or 'default'}:{resolved_key or 'default'}:{api_endpoint or 'default'}"
        if cache_key in self._llm_cache:
            return self._llm_cache[cache_key]
        llm = self._build_llm_for(provider, resolved_key, model, api_endpoint)
        self._llm_cache[cache_key] = llm
        return llm

    async def test_connection(self, provider: str, api_key: Optional[str] = None, model: Optional[str] = None, api_endpoint: Optional[str] = None) -> Dict[str, Any]:
        """测试供应商连接 — 与 switch 同一条 runtime 重建路径。"""
        try:
            runtime = self.build_runtime_config(
                provider=provider,
                model=model,
                api_key=api_key,
                api_endpoint=api_endpoint,
            )
            llm = self._llm_from_runtime_config(runtime)
            # Validate the effective runtime credential, not a stale adapter field.
            effective_key = getattr(llm, "api_key", None) or runtime.get("api_key")
            if not self._is_usable_api_key(effective_key):
                return {
                    "success": False,
                    "message": f"连接测试失败: API密钥未设置 (provider={provider})",
                }
            resp = await llm.chat([{"role": "user", "content": "hi，只用回复ok"}])
            return {
                "success": True,
                "message": "连接测试成功",
                "response": resp.content,
            }
        except Exception as e:
            logger.warning(f"测试连接失败: {e}")
            return {
                "success": False,
                "message": f"连接测试失败: {str(e)}",
            }

    async def fetch_models(self, provider: str, api_key: Optional[str] = None, api_endpoint: Optional[str] = None) -> Dict[str, Any]:
        """获取供应商的模型列表"""
        try:
            llm = self.get_llm(provider, api_key, "test", api_endpoint)
            models = await llm.fetch_models()
            return {
                "success": True,
                "message": f"获取到 {len(models)} 个模型",
                "models": models,
            }
        except Exception as e:
            logger.warning(f"获取模型列表失败: {e}")
            return {
                "success": False,
                "message": f"获取模型列表失败: {str(e)}",
                "models": [],
            }

    async def test_tools(self, provider: str, api_key: Optional[str] = None, model: Optional[str] = None, api_endpoint: Optional[str] = None) -> Dict[str, Any]:
        """测试工具调用支持"""
        try:
            llm = self.get_llm(provider, api_key, model, api_endpoint)
            # 简单的工具调用测试
            tools = [{
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "返回输入的内容",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
            }]
            resp = await llm.chat(
                [{"role": "user", "content": "调用echo工具，输入text: hello"}],
                tools=tools,
                tool_choice="auto",
            )
            tool_calls = resp.tool_calls or []
            return {
                "success": True,
                "message": f"工具调用测试完成，支持工具调用: {len(tool_calls) > 0}",
                "tool_call_supported": len(tool_calls) > 0,
                "tool_calls": [t.model_dump() for t in tool_calls],
            }
        except Exception as e:
            logger.warning(f"测试工具调用失败: {e}")
            return {
                "success": False,
                "message": f"测试工具调用失败: {str(e)}",
                "tool_call_supported": False,
            }

# 单例实例
_llm_manager_instance = None

def get_llm_manager():
    global _llm_manager_instance
    if _llm_manager_instance is None:
        _llm_manager_instance = LLMManager()
    return _llm_manager_instance
