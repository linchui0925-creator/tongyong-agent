"""
LLM 管理器，统一管理所有供应商、模型、配置
完全对齐前端预设供应商格式
"""
import os
import toml
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from app.llm.base import BaseLLM
from app.llm.openai_compatible import OpenAICompatibleLLM
import logging
logger = logging.getLogger(__name__)

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
        """尝试从 data/llm_config.json 恢复上次保存的 provider/model；返回 (provider, model) 或 None。"""
        try:
            cfg_path = Path("data") / "llm_config.json"
            if not cfg_path.exists():
                return None
            saved = json.loads(cfg_path.read_text(encoding="utf-8") or "{}")
            provider = saved.get("provider")
            if not provider:
                return None
            self._current_provider = provider
            self._current_model = saved.get("model") or self._default_model_for(provider)
            profile_id = saved.get("active_provider_profile_id")
            if profile_id:
                self._current_provider_profile_id = profile_id
            return (provider, self._current_model)
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
        return getattr(self, "config", {}).get("default_model", "glm-5.2")

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

    def get_current_config(self) -> Dict[str, Any]:
        provider = self.get_current_provider()
        model = self.get_current_model()
        return {
            "provider": provider,
            "model": model,
            "api_key_configured": bool(self.get_api_key(provider)),
            "provider_profile_id": getattr(self, "_current_provider_profile_id", None),
        }

    def get_api_key(self, provider: str) -> Optional[str]:
        if not provider:
            return None
        # 自定义供应商里保存的 key
        for p in getattr(self, "_custom_providers", []):
            if p.get("id") == provider and p.get("api_key"):
                return p["api_key"]
        # builtin: 优先 data/llm_config.json api_keys，否则读环境变量
        try:
            cfg_path = Path("data") / "llm_config.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8") or "{}")
                k = (cfg.get("api_keys") or {}).get(provider)
                if k:
                    return k
        except Exception:
            pass
        return os.environ.get(f"{provider.upper()}_API_KEY")

    def get_saved_models(self) -> List[Dict[str, Any]]:
        """读取 data/llm_config.json 里的 saved_models 列表。"""
        try:
            cfg_path = Path("data") / "llm_config.json"
            if not cfg_path.exists():
                return []
            cfg = json.loads(cfg_path.read_text(encoding="utf-8") or "{}")
            return cfg.get("saved_models") or []
        except Exception as e:
            logger.warning(f"get_saved_models failed: {e}")
            return []

    def add_saved_model(self, entry: Dict[str, Any]) -> str:
        """往 data/llm_config.json 加一条 saved_model，返回 entry.id。"""
        cfg_path = Path("data") / "llm_config.json"
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
        cfg_path = Path("data") / "llm_config.json"
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

    def switch_model(self, provider: str, api_key: Optional[str] = None, model: Optional[str] = None, **kwargs) -> bool:
        """切换当前 LLM；同步 agent engine.llm；写入 data/llm_config.json。"""
        try:
            endpoint = kwargs.get("api_endpoint")
            try:
                llm = self._build_llm_for(provider, api_key, model, endpoint)
            except ValueError:
                logger.warning(f"switch_model: provider {provider} 不存在")
                return False
            # 选 model 时优先用显式 model，否则 custom provider 的 default_model，否则 llm 默认
            cfg = self.get_custom_provider(provider) or {}
            self._current_provider = provider
            self._current_model = model or cfg.get("default_model") or llm.model
            self._current_llm = llm
            self._current_provider_profile_id = (
                provider if any(p.get("id") == provider for p in self._custom_providers) else None
            )
            engine = getattr(self, "_agent_engine", None)
            if engine is not None:
                engine.llm = llm
            try:
                cfg_path = Path("data") / "llm_config.json"
                if cfg_path.exists():
                    saved = json.loads(cfg_path.read_text(encoding="utf-8") or "{}")
                else:
                    saved = {}
                saved["provider"] = provider
                saved["model"] = self._current_model
                if any(p.get("id") == provider for p in self._custom_providers):
                    saved["active_provider_profile_id"] = provider
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                cfg_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning(f"switch_model 持久化失败: {e}")
            self._llm_cache.pop(provider, None)
            return True
        except Exception as e:
            logger.error(f"switch_model 失败: {e}", exc_info=True)
            return False

    def _load_config(self) -> Dict[str, Any]:
        """加载config.toml配置文件"""
        config_path = Path("config.toml")
        if not config_path.exists():
            config_path = Path("config.example.toml")
        try:
            if config_path.exists():
                logger.info(f"加载配置文件: {config_path.absolute()}")
                return toml.load(config_path)
            return {}
        except Exception as e:
            logger.warning(f"加载配置文件失败: {e}，使用默认配置")
            return {}

    def _load_builtin_providers(self) -> List[Dict[str, Any]]:
        """加载内置预设供应商，和前端TEMPLATE_OPTIONS完全对齐"""
        builtin = [
        {
            'id': 'edgefn',
            'name': '⚡ EdgeFn聚合',
            'protocol': 'openai_compatible',
            'base_url': 'https://api.edgefn.net/v1',
            'default_model': 'GLM-5.2',
            'models': ['GLM-5.2', 'GLM-4.5V', 'GLM-4-flash', 'deepseek-v4-flash', 'deepseek-v4-pro', 'deepseek-chat'],
            'icon': '⚡',
            'color': '#F59E0B',
            'notes': 'EdgeFn聚合代理，一个Key支持智谱/DeepSeek等多模型，国内访问稳定',
            'star': True,
        },
]
        # 从环境变量加载
        env_prefix_map = {
            'openai': 'OPENAI_API_KEY',
            'sheng_suan_yun': 'SHENG_SUAN_YUN_API_KEY',
            'patewayai': 'PATEWAYAI_API_KEY',
            'volcengine_agentplan': 'VOLCENGINE_AGENTPLAN_API_KEY',
            'byteplus': 'BYTEPLUS_API_KEY',
            'doubaoseed': 'DOUBAOSEED_API_KEY',
            'ccsub': 'CCSUB_API_KEY',
            'unity2ai': 'UNITY2AI_API_KEY',
            'siliconflow': 'SILICONFLOW_API_KEY',
            'siliconflow_en': 'SILICONFLOW_EN_API_KEY',
            'dmxapi': 'DMXAPI_API_KEY',
            'packycode': 'PACKYCODE_API_KEY',
            'apikey_fun': 'APIKEY_FUN_API_KEY',
            'apinebula': 'APINEBULA_API_KEY',
            'atlascloud': 'ATLASCLOUD_API_KEY',
            'sudocode': 'SUDOCODE_API_KEY',
            'claude_cn': 'CLAUDE_CN_API_KEY',
            'runapi': 'RUNAPI_API_KEY',
            'relaxycode': 'RELAXYCODE_API_KEY',
            'cubence': 'CUBENCE_API_KEY',
            'aigocode': 'AIGOCODE_API_KEY',
            'rightcode': 'RIGHTCODE_API_KEY',
            'aicodemirror': 'AICODEMIRROR_API_KEY',
            'crazyrouter': 'CRAZYROUTER_API_KEY',
            'sssaicode': 'SSSAICODE_API_KEY',
            'youyun': 'YOUYUN_API_KEY',
            'youyun_coding': 'YOUYUN_CODING_API_KEY',
            'micu': 'MICU_API_KEY',
            'ctok': 'CTOK_API_KEY',
            'azure_openai': 'AZURE_OPENAI_API_KEY',
            'deepseek': 'DEEPSEEK_API_KEY',
            'zhipu': 'ZHIPU_API_KEY',
            'zhipu_en': 'ZHIPU_EN_API_KEY',
            'qianfan': 'QIANFAN_API_KEY',
            'bailian': 'BAILIAN_API_KEY',
            'kimi': 'KIMI_API_KEY',
            'kimi_coding': 'KIMI_CODING_API_KEY',
            'stepfun': 'STEPFUN_API_KEY',
            'stepfun_en': 'STEPFUN_EN_API_KEY',
            'modelscope': 'MODELSCOPE_API_KEY',
            'longcat': 'LONGCAT_API_KEY',
            'minimax': 'MINIMAX_API_KEY',
            'minimax_en': 'MINIMAX_EN_API_KEY',
            'bailing': 'BAILING_API_KEY',
            'xiaomi_mimo': 'XIAOMI_MIMO_API_KEY',
            'xiaomi_mimo_turbo': 'XIAOMI_MIMO_TURBO_API_KEY',
            'novita_ai': 'NOVITA_AI_API_KEY',
            'nvidia': 'NVIDIA_API_KEY',
            'aihubmix': 'AIHUBMIX_API_KEY',
            'cherryin': 'CHERRYIN_API_KEY',
            'eflowcode': 'EFLOWCODE_API_KEY',
            'pipellm': 'PIPELLM_API_KEY',
            'openrouter': 'OPENROUTER_API_KEY',
            'therouter': 'THEROUTER_API_KEY',
        }
        # 内置供应商配置，和前端完全一致
        builtin_configs = [
            # 星标推荐
            {
                'id': 'openai',
                'name': '🟢 OpenAI Official',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.openai.com/v1',
                'default_model': '请输入模型ID',
                'models': [],
                'icon': '🟢',
                'color': '#10A37F',
                'notes': '官方接口地址正确，请填写你已开通权限的模型ID',
                'star': True,
            },
            {
                'id': 'sheng_suan_yun',
                'name': '🟣 胜算云',
                'protocol': 'openai_compatible',
                'base_url': 'https://router.shengsuanyun.com/api',
                'default_model': 'claude-sonnet-4-6',
                'models': ['sheng-suan-7b'],
                'icon': '🟣',
                'color': '#a855f7',
                'notes': '胜算云模型接口。',
                'star': True,
            },
            {
                'id': 'patewayai',
                'name': '⚫ PatewayAI',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.patewayai.com/v1',
                'default_model': 'pateway-v1',
                'models': ['pateway-v1'],
                'icon': '⚫',
                'color': '#1f2937',
                'notes': 'PatewayAI官方接口。',
                'star': True,
            },
            {
                'id': 'volcengine_agentplan',
                'name': '🔵 火山Agentplan',
                'protocol': 'openai_compatible',
                'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
                'default_model': 'doubao-seed-2-0-code-preview-latest',
                'models': ['doubao-pro-32k'],
                'icon': '🔵',
                'color': '#3b82f6',
                'notes': '火山引擎AgentPlan/豆包兼容接口。',
                'star': True,
            },
            {
                'id': 'byteplus',
                'name': '🔵 BytePlus',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.byteplus.com/v1',
                'default_model': 'byteplus-v1',
                'models': ['byteplus-v1'],
                'icon': '🔵',
                'color': '#3b82f6',
                'notes': 'BytePlus官方接口。',
                'star': True,
            },
            {
                'id': 'doubaoseed',
                'name': '🟣 DouBaoSeed',
                'protocol': 'openai_compatible',
                'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
                'default_model': 'doubao-seed-2-0-code-preview-latest',
                'models': ['doubao-seed-128k'],
                'icon': '🟣',
                'color': '#a855f7',
                'notes': '字节跳动豆包Seed系列模型。',
                'star': True,
            },
            {
                'id': 'ccsub',
                'name': '🟢 CCSub',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.ccsub.com/v1',
                'default_model': 'ccsub-7b',
                'models': ['ccsub-7b'],
                'icon': '🟢',
                'color': '#22c55e',
                'notes': 'CCSub模型接口。',
                'star': True,
            },
            {
                'id': 'unity2ai',
                'name': '⚫ Unity2.ai',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.unity2.ai/v1',
                'default_model': 'unity-v1',
                'models': ['unity-v1'],
                'icon': '⚫',
                'color': '#1f2937',
                'notes': 'Unity2.ai官方接口。',
                'star': True,
            },
            {
                'id': 'siliconflow',
                'name': '💜 SiliconFlow',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.siliconflow.cn/v1',
                'default_model': '请输入模型ID',
                'models': [],
                'icon': '💜',
                'color': '#8b5cf6',
                'notes': '官方接口地址正确，请填写你已开通权限的模型ID',
                'star': True,
            },
            {
                'id': 'siliconflow_en',
                'name': '💜 SiliconFlow en',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.siliconflow.com/v1',
                'default_model': 'deepseek-v3',
                'models': ['deepseek-v3'],
                'icon': '💜',
                'color': '#8b5cf6',
                'notes': '硅基流动国际版接口。',
                'star': True,
            },
            {
                'id': 'dmxapi',
                'name': '⚪ DMXAPI',
                'protocol': 'openai_compatible',
                'base_url': 'https://www.dmxapi.cn',
                'default_model': 'dmx-v1',
                'models': ['dmx-v1'],
                'icon': '⚪',
                'color': '#9ca3af',
                'notes': 'DMXAPI模型接口。',
                'star': True,
            },
            {
                'id': 'packycode',
                'name': '⚫ PackyCode',
                'protocol': 'openai_compatible',
                'base_url': 'https://www.packyapi.com',
                'default_model': 'packy-coder-v1',
                'models': ['packy-coder-v1'],
                'icon': '⚫',
                'color': '#1f2937',
                'notes': 'PackyCode代码大模型接口。',
                'star': True,
            },
            {
                'id': 'apikey_fun',
                'name': '🟠 APIKEY.FUN',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.apikey.fun/v1',
                'default_model': 'apikeyfun-v1',
                'models': ['apikeyfun-v1'],
                'icon': '🟠',
                'color': '#f59e0b',
                'notes': 'APIKEY.FUN聚合模型接口。',
                'star': True,
            },
            {
                'id': 'apinebula',
                'name': '⚪ APINebula',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.apinebula.com/v1',
                'default_model': 'apinebula-v1',
                'models': ['apinebula-v1'],
                'icon': '⚪',
                'color': '#9ca3af',
                'notes': 'APINebula星云模型接口。',
                'star': True,
            },
            {
                'id': 'atlascloud',
                'name': '▲ AtlasCloud',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.atlascloud.ai/v1',
                'default_model': 'atlas-v1',
                'models': ['atlas-v1'],
                'icon': '▲',
                'color': '#6366f1',
                'notes': 'AtlasCloud大模型接口。',
                'star': True,
            },
            {
                'id': 'sudocode',
                'name': '🟣 SudoCode',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.sudocode.com/v1',
                'default_model': 'sudo-coder-v1',
                'models': ['sudo-coder-v1'],
                'icon': '🟣',
                'color': '#a855f7',
                'notes': 'SudoCode代码大模型接口。',
                'star': True,
            },
            {
                'id': 'claude_cn',
                'name': '🍀 ClaudeCN',
                'protocol': 'openai_compatible',
                'base_url': 'https://claude.volcengineapi.com/v1',
                'default_model': 'claude-3-5-sonnet',
                'models': ['claude-3-5-sonnet'],
                'icon': '🍀',
                'color': '#4ade80',
                'notes': '火山方舟Claude国内节点接口。',
                'star': True,
            },
            {
                'id': 'runapi',
                'name': '⬛ RunAPI',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.runapi.com/v1',
                'default_model': 'runapi-v1',
                'models': ['runapi-v1'],
                'icon': '⬛',
                'color': '#18181b',
                'notes': 'RunAPI聚合模型接口。',
                'star': True,
            },
            {
                'id': 'relaxycode',
                'name': '⚪ RelaxyCode',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.relaxycode.com/v1',
                'default_model': 'relaxy-coder-v1',
                'models': ['relaxy-coder-v1'],
                'icon': '⚪',
                'color': '#9ca3af',
                'notes': 'RelaxyCode代码模型接口。',
                'star': True,
            },
            {
                'id': 'cubence',
                'name': '⬛ Cubence',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.cubence.com',
                'default_model': 'cubence-v1',
                'models': ['cubence-v1'],
                'icon': '⬛',
                'color': '#18181b',
                'notes': 'Cubence模型接口。',
                'star': True,
            },
            {
                'id': 'aigocode',
                'name': '🟣 AIGoCode',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.aigocode.com',
                'default_model': 'aigo-coder-v1',
                'models': ['aigo-coder-v1'],
                'icon': '🟣',
                'color': '#a855f7',
                'notes': 'AIGoCode代码大模型接口。',
                'star': True,
            },
            {
                'id': 'rightcode',
                'name': '🟠 RightCode',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.rightcode.com/v1',
                'default_model': 'right-coder-v1',
                'models': ['right-coder-v1'],
                'icon': '🟠',
                'color': '#f59e0b',
                'notes': 'RightCode代码模型接口。',
                'star': True,
            },
            {
                'id': 'aicodemirror',
                'name': '✖️ AICodeMirror',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.aicodemirror.com/v1',
                'default_model': 'aicm-v1',
                'models': ['aicm-v1'],
                'icon': '✖️',
                'color': '#ef4444',
                'notes': 'AICodeMirror镜像模型接口。',
                'star': True,
            },
            {
                'id': 'crazyrouter',
                'name': '⚪ CrazyRouter',
                'protocol': 'openai_compatible',
                'base_url': 'https://crazyrouter.com/v1',
                'default_model': 'crazy-v1',
                'models': ['crazy-v1'],
                'icon': '⚪',
                'color': '#9ca3af',
                'notes': 'CrazyRouter大模型路由接口。',
                'star': True,
            },
            {
                'id': 'sssaicode',
                'name': '⬛ SSSAiCode',
                'protocol': 'openai_compatible',
                'base_url': 'https://node-hk.sssaicode.com/api',
                'default_model': 'sssaicode-v1',
                'models': ['sssaicode-v1'],
                'icon': '⬛',
                'color': '#18181b',
                'notes': 'SSSAiCode代码模型接口。',
                'star': True,
            },
            {
                'id': 'youyun',
                'name': '🟣 优云智算',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.youyunzhisuan.com/v1',
                'default_model': 'youyun-v1',
                'models': ['youyun-v1'],
                'icon': '🟣',
                'color': '#a855f7',
                'notes': '优云智算大模型接口。',
                'star': True,
            },
            {
                'id': 'youyun_coding',
                'name': '🟣 优云智算Coding',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.youyunzhisuan.com/v1',
                'default_model': 'youyun-coder-v1',
                'models': ['youyun-coder-v1'],
                'icon': '🟣',
                'color': '#a855f7',
                'notes': '优云智算代码模型接口。',
                'star': True,
            },
            {
                'id': 'micu',
                'name': '🔵 Micu',
                'protocol': 'openai_compatible',
                'base_url': 'https://www.openclaudecode.cn',
                'default_model': 'micu-v1',
                'models': ['micu-v1'],
                'icon': '🔵',
                'color': '#3b82f6',
                'notes': 'Micu大模型接口。',
                'star': True,
            },
            {
                'id': 'ctok',
                'name': '🔵 CTok.ai',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.ctok.ai',
                'default_model': 'ctok-v1',
                'models': ['ctok-v1'],
                'icon': '🔵',
                'color': '#3b82f6',
                'notes': 'CTok.ai模型接口。',
                'star': True,
            },
            # 普通源
            {
                'id': 'azure_openai',
                'name': '🔵 Azure OpenAI',
                'protocol': 'openai_compatible',
                'base_url': 'https://{resource}.openai.azure.com/openai/deployments/{deployment}/v1',
                'default_model': 'gpt-4o',
                'models': ['gpt-4o'],
                'icon': '🔵',
                'color': '#3b82f6',
                'notes': '微软Azure OpenAI服务，需替换资源和部署名称。',
                'star': False,
            },
            {
                'id': 'deepseek',
                'name': '🔍 DeepSeek',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.deepseek.com/v1',
                'default_model': 'deepseek-v4-flash',
                'models': ['deepseek-chat', 'deepseek-coder'],
                'icon': '🔍',
                'color': '#2563eb',
                'notes': '深度求索官方接口，支持deepseek-v4-flash/deepseek-v4-pro，原生支持推理和工具调用。',
                'star': False,
            },
            {
                'id': 'zhipu',
                'name': '🔷 Zhipu GLM',
                'protocol': 'openai_compatible',
                'base_url': 'https://open.bigmodel.cn/api/paas/v4',
                'default_model': 'glm-5.2',
                'models': ['glm-5.4', 'glm-5.2', 'glm-5-flash'],
                'icon': '🔷',
                'color': '#6366f1',
                'notes': '智谱AI官方接口，GLM-5系列最新模型，用户确认5.2/5.4可用',
                'star': False,
            },
            {
                'id': 'zhipu_en',
                'name': '🔷 Zhipu GLM en',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.z.ai/v1',
                'default_model': 'glm-5',
                'models': ['glm-4-air'],
                'icon': '🔷',
                'color': '#6366f1',
                'notes': '智谱GLM英文模型系列。',
                'star': False,
            },
            {
                'id': 'qianfan',
                'name': '🐾 百度千帆',
                'protocol': 'openai_compatible',
                'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
                'default_model': 'qwen3.5-plus',
                'models': ['ernie-3.5-8k'],
                'icon': '🐾',
                'color': '#165dff',
                'notes': '百度智能云千帆大模型平台兼容接口。',
                'star': False,
            },
            {
                'id': 'bailian',
                'name': '🟣 Bailian',
                'protocol': 'openai_compatible',
                'base_url': 'https://bailian.aliyuncs.com/v1',
                'default_model': 'qwen-max',
                'models': ['qwen-max'],
                'icon': '🟣',
                'color': '#a855f7',
                'notes': '阿里云百炼平台兼容接口。',
                'star': False,
            },
            {
                'id': 'kimi',
                'name': '🟣 Kimi Moonshot',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.moonshot.cn/v1',
                'default_model': 'kimi-k2.6',
                'models': ['moonshot-v1-8k', 'moonshot-v1-128k'],
                'icon': '🟣',
                'color': '#a855f7',
                'notes': 'Moonshot AI官方接口，支持超长上下文。',
                'star': False,
            },
            {
                'id': 'kimi_coding',
                'name': '🟣 Kimi For Coding',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.kimi.com/v1',
                'default_model': 'kimi-for-coding',
                'models': ['moonshot-coder-v1'],
                'icon': '🟣',
                'color': '#a855f7',
                'notes': 'Kimi代码专用模型。',
                'star': False,
            },
            {
                'id': 'stepfun',
                'name': '🔹 StepFun',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.stepfun.com/step_plan/v1',
                'default_model': '请输入模型ID',
                'models': [],
                'icon': '🔹',
                'color': '#3b82f6',
                'notes': '官方接口地址正确，请填写你已开通权限的模型ID',
                'star': False,
            },
            {
                'id': 'stepfun_en',
                'name': '🔹 StepFun en',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.stepfun.ai/step_plan/v1',
                'default_model': 'step-3.5-flash',
                'models': ['step-1-32k'],
                'icon': '🔹',
                'color': '#3b82f6',
                'notes': '阶跃星辰英文模型系列。',
                'star': False,
            },
            {
                'id': 'modelscope',
                'name': '🔵 ModelScope',
                'protocol': 'openai_compatible',
                'base_url': 'https://api-inference.modelscope.cn/v1',
                'default_model': 'modelscope-v1',
                'models': ['modelscope-v1'],
                'icon': '🔵',
                'color': '#3b82f6',
                'notes': '阿里达摩院ModelScope平台接口。',
                'star': False,
            },
            {
                'id': 'longcat',
                'name': '🟢 Longcat',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.longcat.chat/v1',
                'default_model': 'longcat-7b',
                'models': ['longcat-7b'],
                'icon': '🟢',
                'color': '#22c55e',
                'notes': 'Longcat长上下文模型。',
                'star': False,
            },
            {
                'id': 'minimax',
                'name': '🎙️ MiniMax',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.minimaxi.com/v1',
                'default_model': '请输入模型ID',
                'models': [],
                'icon': '🎙️',
                'color': '#ec4899',
                'notes': '官方接口地址正确，请填写你已开通权限的模型ID',
                'star': False,
            },
            {
                'id': 'minimax_en',
                'name': '🎙️ MiniMax en',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.minimax.io/v1',
                'default_model': 'minimax-m2.7',
                'models': ['minimax-abab6.5'],
                'icon': '🎙️',
                'color': '#ec4899',
                'notes': 'MiniMax英文模型系列。',
                'star': False,
            },
            {
                'id': 'bailing',
                'name': '⚪ BaiLing',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.tbox.cn/v1',
                'default_model': 'bailing-v1',
                'models': ['bailing-v1'],
                'icon': '⚪',
                'color': '#9ca3af',
                'notes': '百聆大模型接口。',
                'star': False,
            },
            {
                'id': 'xiaomi_mimo',
                'name': '➖ Xiaomi MiMo',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.xiaomimimo.com/v1',
                'default_model': 'mimo-v1',
                'models': ['mimo-v1'],
                'icon': '➖',
                'color': '#6b7280',
                'notes': '小米MiMo大模型系列。',
                'star': False,
            },
            {
                'id': 'xiaomi_mimo_turbo',
                'name': '➖ Xiaomi MiMo Turbo',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.mi.ai/v1',
                'default_model': 'mimo-turbo-v1',
                'models': ['mimo-turbo-v1'],
                'icon': '➖',
                'color': '#6b7280',
                'notes': '小米MiMo Turbo系列。',
                'star': False,
            },
            {
                'id': 'novita_ai',
                'name': '▲ Novita AI',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.novita.ai/openai',
                'default_model': 'novita-v1',
                'models': ['novita-v1'],
                'icon': '▲',
                'color': '#6366f1',
                'notes': 'Novita AI大模型接口。',
                'star': False,
            },
            {
                'id': 'nvidia',
                'name': '🟢 Nvidia',
                'protocol': 'openai_compatible',
                'base_url': 'https://integrate.api.nvidia.com/v1',
                'default_model': 'nvidia-llama-3',
                'models': ['nvidia-llama-3'],
                'icon': '🟢',
                'color': '#22c55e',
                'notes': 'Nvidia NIM模型接口。',
                'star': False,
            },
            {
                'id': 'aihubmix',
                'name': '⚪ AiHubMix',
                'protocol': 'openai_compatible',
                'base_url': 'https://aihubmix.com',
                'default_model': 'aihubmix-v1',
                'models': ['aihubmix-v1'],
                'icon': '⚪',
                'color': '#9ca3af',
                'notes': 'AiHubMix聚合模型接口。',
                'star': False,
            },
            {
                'id': 'cherryin',
                'name': '🔴 CherryIN',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.cherryin.com/v1',
                'default_model': 'cherry-v1',
                'models': ['cherry-v1'],
                'icon': '🔴',
                'color': '#ef4444',
                'notes': 'CherryIN模型接口。',
                'star': False,
            },
            {
                'id': 'eflowcode',
                'name': '⚪ E-FlowCode',
                'protocol': 'openai_compatible',
                'base_url': 'https://e-flowcode.cc/v1',
                'default_model': 'eflow-coder-v1',
                'models': ['eflow-coder-v1'],
                'icon': '⚪',
                'color': '#9ca3af',
                'notes': 'E-FlowCode代码模型接口。',
                'star': False,
            },
            {
                'id': 'pipellm',
                'name': '⬛ PIPELLM',
                'protocol': 'openai_compatible',
                'base_url': 'https://cc-api.pipellm.ai',
                'default_model': 'pipe-v1',
                'models': ['pipe-v1'],
                'icon': '⬛',
                'color': '#18181b',
                'notes': 'PIPELLM流水线大模型接口。',
                'star': False,
            },
            {
                'id': 'openrouter',
                'name': '🔄 OpenRouter',
                'protocol': 'openai_compatible',
                'base_url': 'https://openrouter.ai/api/v1',
                'default_model': 'anthropic/claude-3-opus',
                'models': ['anthropic/claude-3-opus'],
                'icon': '🔄',
                'color': '#6366f1',
                'notes': 'OpenRouter聚合平台，支持全球数百种模型。',
                'star': False,
            },
            {
                'id': 'therouter',
                'name': '🔄 TheRouter',
                'protocol': 'openai_compatible',
                'base_url': 'https://api.therouter.ai/v1',
                'default_model': 'router-v1',
                'models': ['router-v1'],
                'icon': '🔄',
                'color': '#6366f1',
                'notes': 'TheRouter大模型路由接口。',
                'star': False,
            },
            {
                'id': 'ollama',
                'name': '🐳 Ollama OpenAI 兼容',
                'protocol': 'openai_compatible',
                'base_url': 'http://localhost:11434/v1',
                'default_model': 'llama3.2',
                'models': ['llama3.2', 'qwen'],
                'icon': '🐳',
                'color': '#22c55e',
                'notes': '本地模型，通常不需要 API Key，可填任意占位值。',
                'star': False,
            },
        ]
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
        custom_path = Path("data") / "custom_providers.json"
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
        custom_path = Path("data") / "custom_providers.json"
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
        """将自定义供应商配置转换为LLM实例"""
        base_url = api_endpoint or provider.get('base_url', 'https://api.openai.com/v1')
        final_api_key = api_key or provider.get('api_key') or ''
        final_model = model or provider.get('default_model', 'gpt-4o-mini')
        # 支持OpenAI/Responses/Anthropic三种API格式，自动检测
        llm = OpenAICompatibleLLM(
            api_key=final_api_key,
            model=final_model,
        )
        llm.api_base = base_url
        llm.request_config = provider.get('request_config', {})
        return llm

    def _build_llm_for(self, provider_id: str, api_key: Optional[str] = None, model: Optional[str] = None, api_endpoint: Optional[str] = None):
        """根据 provider_id 构造 LLM 实例。先查 custom/builtin dict，没命中再走 factory。"""
        provider = self.get_custom_provider(provider_id)
        if provider:
            return self._custom_provider_to_llm(provider, api_key, model, api_endpoint)
        # 兜底：factory.py 注册的 provider（tongyi/openai/anthropic/edgefn/...）
        try:
            from app.llm.factory import get_llm as _factory_get_llm
            llm = _factory_get_llm(provider_id, api_key=api_key)
            if model:
                llm.model = model
            if api_endpoint and hasattr(llm, "api_base"):
                llm.api_base = api_endpoint
            return llm
        except Exception as e:
            raise ValueError(f"供应商 {provider_id} 不存在或 factory 未注册: {e}")

    def get_llm(self, provider_id: str, api_key: Optional[str] = None, model: Optional[str] = None, api_endpoint: Optional[str] = None) -> BaseLLM:
        """获取LLM实例，优先从缓存读取"""
        cache_key = f"{provider_id}:{model or 'default'}:{api_key or 'default'}:{api_endpoint or 'default'}"
        if cache_key in self._llm_cache:
            return self._llm_cache[cache_key]
        llm = self._build_llm_for(provider_id, api_key, model, api_endpoint)
        self._llm_cache[cache_key] = llm
        return llm

    async def test_connection(self, provider_id: str, api_key: Optional[str] = None, model: Optional[str] = None, api_endpoint: Optional[str] = None) -> Dict[str, Any]:
        """测试供应商连接"""
        try:
            llm = self.get_llm(provider_id, api_key, model, api_endpoint)
            # 发送简单测试请求
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

    async def fetch_models(self, provider_id: str, api_key: Optional[str] = None, api_endpoint: Optional[str] = None) -> Dict[str, Any]:
        """获取供应商的模型列表"""
        try:
            llm = self.get_llm(provider_id, api_key, "test", api_endpoint)
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

    async def test_tools(self, provider_id: str, api_key: Optional[str] = None, model: Optional[str] = None, api_endpoint: Optional[str] = None) -> Dict[str, Any]:
        """测试工具调用支持"""
        try:
            llm = self.get_llm(provider_id, api_key, model, api_endpoint)
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
