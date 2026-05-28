"""
ProfileManager - 网关多Profile管理服务

提供Profile的CRUD操作和持久化，支持JSON文件存储。
每个Profile有独立的数据目录（数据库、向量库、auth.json等）。
"""

import json
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.gateway.config import Profile, GatewaySettings

logger = logging.getLogger(__name__)

# 默认profile数据根目录
DEFAULT_PROFILE_BASE = Path("./data/hermes/profiles")


class ProfileManager:
    """网关Profile管理器"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def _init(self):
        if self._initialized:
            return
        self._initialized = True
        self._profiles: Dict[str, Profile] = {}
        self._active_profile_id: Optional[str] = None
        self._llm_managers: Dict[str, object] = {}  # per-profile LLMManager instances
        self._base_port = 8001  # Profile网关起始端口
        self._load_profiles()

    def _get_config_path(self) -> Path:
        settings = GatewaySettings()
        return Path(settings.profile_config_path)

    def _get_profile_base(self) -> Path:
        """获取profile数据根目录"""
        settings = GatewaySettings()
        base = getattr(settings, 'profile_data_dir', None)
        if base:
            return Path(base)
        return DEFAULT_PROFILE_BASE

    # ── Profile数据目录管理 ─────────────────────────────────

    def get_profile_home(self, profile_id: str) -> Path:
        """获取Profile的数据目录"""
        return self._get_profile_base() / profile_id

    def get_profile_db_path(self, profile_id: str) -> Path:
        """获取Profile的SQLite数据库路径"""
        return self.get_profile_home(profile_id) / "tongyong.db"

    def get_profile_chroma_path(self, profile_id: str) -> Path:
        """获取Profile的ChromaDB路径"""
        return self.get_profile_home(profile_id) / "chroma"

    def get_profile_auth_path(self, profile_id: str) -> Path:
        """获取Profile的auth.json路径"""
        return self.get_profile_home(profile_id) / "auth.json"

    def ensure_profile_dirs(self, profile_id: str):
        """创建Profile所需目录结构"""
        home = self.get_profile_home(profile_id)
        home.mkdir(parents=True, exist_ok=True)
        (home / "chroma").mkdir(exist_ok=True)
        (home / "skills").mkdir(exist_ok=True)
        logger.info(f"Created profile directories: {home}")
        return home

    def init_profile_auth(self, profile: Profile):
        """初始化Profile的auth.json"""
        auth_path = self.get_profile_auth_path(profile.id)
        if not auth_path.exists():
            auth_data = {
                "provider": profile.provider,
                "model": profile.model,
                "api_key": profile.api_key or "",
                "api_endpoint": profile.api_endpoint or "",
                "temperature": profile.temperature,
                "max_tokens": profile.max_tokens,
                "top_p": profile.top_p,
                "max_tool_rounds": profile.max_tool_rounds,
            }
            auth_path.write_text(json.dumps(auth_data, ensure_ascii=False, indent=2))
            logger.info(f"Initialized auth.json for profile: {profile.id}")

    def cleanup_profile_dirs(self, profile_id: str):
        """删除Profile的数据目录（危险操作）"""
        import shutil
        home = self.get_profile_home(profile_id)
        if home.exists():
            shutil.rmtree(home)
            logger.info(f"Cleaned up profile directories: {home}")

    # ── 端口管理 ─────────────────────────────────────────

    def allocate_port(self, profile_id: str) -> int:
        """为Profile分配独立网关端口"""
        # 如果已有端口，直接返回
        if profile_id in self._profiles:
            existing = self._profiles[profile_id]
            if existing.gateway_port > 0:
                return existing.gateway_port

        # 查找可用端口
        used_ports = set(p.gateway_port for p in self._profiles.values() if p.gateway_port > 0)
        for port in range(self._base_port, self._base_port + 99):
            if port not in used_ports:
                # 更新profile的端口
                if profile_id in self._profiles:
                    self._profiles[profile_id].gateway_port = port
                    self._save_profiles()
                return port
        raise RuntimeError("无可用端口（8001-8099已满）")

    def release_port(self, profile_id: str):
        """释放Profile的网关端口"""
        if profile_id in self._profiles:
            self._profiles[profile_id].gateway_port = 0
            self._save_profiles()

    def get_gateway_port(self, profile_id: str) -> int:
        """获取Profile的网关端口"""
        if profile_id in self._profiles:
            return self._profiles[profile_id].gateway_port
        return 0

    # ── Per-Profile LLM Manager ──────────────────────────────

    def get_llm_manager(self, profile_id: str):
        """获取指定Profile的LLMManager实例"""
        if profile_id not in self._llm_managers:
            from app.services.llm_manager import LLMManager
            self._llm_managers[profile_id] = LLMManager(profile_id)
        return self._llm_managers[profile_id]

    def _load_profiles(self):
        config_path = self._get_config_path()
        if not config_path.exists():
            self._profiles = {}
            return

        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            self._profiles = {
                p["id"]: Profile(**p)
                for p in data.get("profiles", [])
            }
            self._active_profile_id = data.get("active_profile_id")
            logger.info(f"Loaded {len(self._profiles)} profiles from {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load profiles: {e}")
            self._profiles = {}

    def _save_profiles(self):
        config_path = self._get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "profiles": [p.model_dump() for p in self._profiles.values()],
            "active_profile_id": self._active_profile_id,
        }
        config_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.debug(f"Saved {len(self._profiles)} profiles to {config_path}")

    # ── CRUD Operations ─────────────────────────────────────

    def list_profiles(self) -> List[Profile]:
        self._init()
        return list(self._profiles.values())

    def get_profile(self, profile_id: str) -> Optional[Profile]:
        self._init()
        return self._profiles.get(profile_id)

    def create_profile(self, profile: Profile) -> Profile:
        self._init()
        profile.id = profile.id or uuid.uuid4().hex[:12]
        profile.created_at = datetime.now().isoformat()
        profile.updated_at = profile.created_at
        self._profiles[profile.id] = profile
        self._save_profiles()

        # 创建Profile数据目录和auth.json
        self.ensure_profile_dirs(profile.id)
        self.init_profile_auth(profile)

        logger.info(f"Created profile: {profile.id} ({profile.name})")
        return profile

    def update_profile(self, profile_id: str, updates: dict) -> Optional[Profile]:
        self._init()
        if profile_id not in self._profiles:
            return None

        profile = self._profiles[profile_id]
        for key, value in updates.items():
            if hasattr(profile, key) and value is not None:
                setattr(profile, key, value)

        profile.updated_at = datetime.now().isoformat()
        self._save_profiles()
        logger.info(f"Updated profile: {profile_id}")
        return profile

    def delete_profile(self, profile_id: str) -> bool:
        self._init()
        if profile_id in self._profiles:
            del self._profiles[profile_id]
            if self._active_profile_id == profile_id:
                self._active_profile_id = None
            self._save_profiles()
            # 清理profile数据目录
            self.cleanup_profile_dirs(profile_id)
            # 清理per-profile LLMManager
            if profile_id in self._llm_managers:
                del self._llm_managers[profile_id]
            logger.info(f"Deleted profile: {profile_id}")
            return True
        return False

    # ── Active Profile ───────────────────────────────────────

    def get_active_profile_id(self) -> Optional[str]:
        self._init()
        return self._active_profile_id

    def set_active_profile(self, profile_id: str) -> bool:
        self._init()
        if profile_id not in self._profiles:
            return False
        self._active_profile_id = profile_id
        self._save_profiles()
        logger.info(f"Set active profile: {profile_id}")
        return True

    def get_active_profile(self) -> Optional[Profile]:
        self._init()
        if not self._active_profile_id:
            return None
        return self._profiles.get(self._active_profile_id)


# ── 全局单例 ──────────────────────────────────────────────

profile_manager = ProfileManager()