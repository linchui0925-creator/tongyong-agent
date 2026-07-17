"""
向量记忆存储 - ChromaDB PersistentClient 的薄封装。

提供 4 个核心操作：
  - add_memory(memory)        写入向量（带 metadata: user_id, importance, created_at）
  - search(query, k=5)        语义检索 top-k
  - get_all()                 全量导出（dreaming engine 用来跨用户整合）
  - delete(memory_id)         按 vector_id 删

注意：
  - chromadb 缺失时所有 API 返回空（不抛异常）— 见 _ensure_chromadb_imported
  - embedding 维度 = 1024（DEFAULT_EMBEDDING_DIM），集合名 = "memories"
  - persistent 路径默认 ./data/chroma，可被 profile_id 覆盖
  - 跨用户共享层独立 collection "memories_shared"，dreaming engine 写
"""
from typing import List, Optional
from app.core.base import Memory
import logging
import uuid
import os
from datetime import datetime
from app.paths import data_path

logger = logging.getLogger(__name__)

chromadb = None
Settings = None


def _ensure_chromadb_imported():
    global chromadb, Settings
    if chromadb is not None and Settings is not None:
        return True
    try:
        import chromadb as _chromadb
        from chromadb.config import Settings as _Settings
        chromadb = _chromadb
        Settings = _Settings
        return True
    except Exception:
        return False

class VectorStore:
    DEFAULT_EMBEDDING_DIM = 1024  # 与ChromaDB集合维度匹配

    def __init__(self, persist_directory: str = None, profile_id: str = "default"):
        # 支持profile_id参数化路径
        if profile_id and profile_id != "default" and persist_directory is None:
            self.persist_directory = data_path("hermes", "profiles", profile_id, "chroma")
        elif persist_directory:
            self.persist_directory = persist_directory
        else:
            self.persist_directory = data_path("chroma")
        self.profile_id = profile_id
        os.makedirs(self.persist_directory, exist_ok=True)
        self.client = None
        self.collection = None

        if not _ensure_chromadb_imported():
            logger.warning("chromadb不可用，向量库已降级为禁用状态")
            return

        settings_kwargs = {
            "anonymized_telemetry": False,
        }
        try:
            settings = Settings(**settings_kwargs)
        except TypeError:
            settings = Settings()

        try:
            self.client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=settings
            )
        except BaseException as e:
            logger.error(f"初始化 ChromaDB 失败，向量库降级为禁用状态: {e}")
            self.client = None
            self.collection = None
            return
        
        self._init_collection()
        
        logger.info(f"向量库初始化完成: {persist_directory}")
    
    def _init_collection(self):
        if not self.client:
            self.collection = None
            return

        # 自动修复 ChromaDB SQLite schema 版本不匹配的问题
        try:
            import sqlite3
            chroma_db = os.path.join(self.persist_directory, 'chroma.sqlite3')
            if os.path.exists(chroma_db):
                conn = sqlite3.connect(chroma_db)
                cursor = conn.cursor()
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='collections'")
                row = cursor.fetchone()
                if row:
                    # 修复缺失的 topic 列
                    if 'topic' not in row[0]:
                        cursor.execute("ALTER TABLE collections ADD COLUMN topic TEXT")
                        conn.commit()
                        logger.info("已自动修复 ChromaDB schema: 添加 topic 列")
                    # 修复缺失的 embedding_dim 列（如果有）
                    if 'embedding_dim' not in row[0]:
                        try:
                            cursor.execute("ALTER TABLE collections ADD COLUMN embedding_dim INTEGER")
                            conn.commit()
                            logger.info("已自动修复 ChromaDB schema: 添加 embedding_dim 列")
                        except Exception as e:
                            logger.debug(f"embedding_dim 列添加失败（可能已存在）: {e}")
                conn.close()
        except Exception as e:
            logger.warning(f"ChromaDB schema 修复失败: {e}")

        # 使用profile-specific collection名称
        collection_name = f"memories_{self.profile_id}" if self.profile_id != "default" else "memories"

        try:
            self.collection = self.client.get_collection(name=collection_name)
            logger.info(f"向量库已存在: {self.persist_directory} ({collection_name})")
        except Exception as e:
            logger.warning(f"获取向量集合失败，尝试创建: {e}")
            try:
                self.collection = self.client.create_collection(
                    name=collection_name,
                    metadata={"hnsw:space": "cosine"}
                )
            except Exception as e2:
                logger.error(f"创建向量集合失败: {e2} — 向量库将降级为禁用状态")
                self.collection = None
    
    def _ensure_dimension(self, embedding: List[float]):
        if not embedding or not self.collection:
            return
        
        expected_dim = len(embedding)
        
        if expected_dim != self.DEFAULT_EMBEDDING_DIM:
            logger.warning(f"注意: embedding维度 {expected_dim} 可能与已存储向量维度不匹配({self.DEFAULT_EMBEDDING_DIM}). 当前向量数量: {self.collection.count()}")

    async def add(self, memory: Memory, embedding: List[float]) -> str:
        try:
            if not self.collection:
                return ""
            self._ensure_dimension(embedding)
            
            # 明确区分会话记忆和共享记忆
            is_shared = memory.session_id is None  # 只有 session_id 为 None 才是共享记忆
            session_id_value = memory.session_id if memory.session_id else ""
            
            self.collection.add(
                ids=[memory.id],
                documents=[memory.content],
                embeddings=[embedding],
                metadatas=[{
                    "type": memory.type,
                    "importance": memory.importance,
                    "session_id": session_id_value,
                    "is_shared": "true" if is_shared else "false",
                    "created_at": memory.created_at or ""
                }]
            )
            logger.info(f"添加记忆到向量库: {memory.id} (共享记忆: {is_shared})")
            return memory.id
        except Exception as e:
            logger.error(f"添加记忆失败: {e}")
            return ""

    async def add_text(
        self,
        session_id: str,
        role: str,
        content: str,
        embedding: List[float]
    ) -> str:
        try:
            if not self.collection:
                return ""
            self._ensure_dimension(embedding)
            text_id = str(uuid.uuid4())

            self.collection.add(
                ids=[text_id],
                documents=[content],
                embeddings=[embedding],
                metadatas=[{
                    "type": "对话",
                    "role": role,
                    "importance": 1,
                    "session_id": session_id,
                    "is_shared": "false",
                    "created_at": datetime.now().isoformat()
                }]
            )
            logger.info(f"对话消息已向量化: {text_id}")
            return text_id
        except Exception as e:
            logger.error(f"对话向量化失败: {e}")
            return ""

    async def add_shared(self, content: str, embedding: List[float], memory_type: str = "操作习惯") -> str:
        try:
            if not self.collection:
                return ""
            self._ensure_dimension(embedding)
            text_id = str(uuid.uuid4())

            self.collection.add(
                ids=[text_id],
                documents=[content],
                embeddings=[embedding],
                metadatas=[{
                    "type": memory_type,
                    "importance": 2,
                    "session_id": "",
                    "is_shared": "true",
                    "created_at": datetime.now().isoformat()
                }]
            )
            logger.info(f"共享记忆已添加: {text_id}")
            return text_id
        except Exception as e:
            logger.error(f"共享记忆添加失败: {e}")
            return ""

    async def search(
        self,
        query: str,
        embedding: List[float],
        k: int = 5,
        session_id: Optional[str] = None,
        is_shared: bool = False
    ) -> List[Memory]:
        try:
            if not self.collection:
                return []
            if is_shared:
                where_clause = {"is_shared": "true"}
                results = self.collection.query(
                    query_embeddings=[embedding],
                    n_results=k * 2,
                    where=where_clause
                )
                return self._parse_search_results(results, k)
            elif session_id:
                results_session = self.collection.query(
                    query_embeddings=[embedding],
                    n_results=k,
                    where={"session_id": session_id}
                )
                results_shared = self.collection.query(
                    query_embeddings=[embedding],
                    n_results=k,
                    where={"is_shared": "true"}
                )
                return self._parse_search_results_with_session(results_session, results_shared, k, session_id)
            else:
                results = self.collection.query(
                    query_embeddings=[embedding],
                    n_results=k * 2,
                    where=None
                )
                return self._parse_search_results(results, k)
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return []

    async def search_all(self, query: str, embedding: List[float], k: int = 5) -> List[Memory]:
        results = await self.search(query, embedding, k=k)
        return results

    async def delete(self, memory_id: str):
        try:
            if not self.collection:
                return
            self.collection.delete(ids=[memory_id])
            logger.info(f"删除记忆: {memory_id}")
        except Exception as e:
            logger.error(f"删除失败: {e}")

    async def get_all(
        self,
        session_id: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0
    ) -> List[Memory]:
        """获取记忆列表（支持分页）
        
        Args:
            session_id: 会话ID（可选）
            limit: 返回的最大记录数（默认1000）
            offset: 跳过的记录数（默认0）
            
        Returns:
            List[Memory]: 记忆列表
        """
        try:
            if not self.collection:
                return []
            where_clause = {"session_id": session_id} if session_id else None
            results = self.collection.get(
                where=where_clause,
                limit=limit,
                offset=offset
            )
        except Exception as e:
            logger.error(f"获取记忆列表失败: {e}")
            return []

        memories = []
        if results and results.get("documents") and results["documents"]:
            for i, doc in enumerate(results["documents"]):
                memories.append(Memory(
                    id=results["ids"][i],
                    type=results["metadatas"][i].get("type", ""),
                    content=doc,
                    importance=results["metadatas"][i].get("importance", 1),
                    session_id=results["metadatas"][i].get("session_id"),
                    created_at=""
                ))

        return memories

    async def get_shared(self) -> List[Memory]:
        """获取共享记忆列表（操作习惯等）
        
        Returns:
            List[Memory]: 共享记忆列表
        """
        try:
            if not self.collection:
                return []
            results = self.collection.get(where={"is_shared": "true"})
            if not results or not results.get("documents"):
                results = self.collection.get(where={"type": "操作习惯"})
        except Exception as e:
            logger.error(f"获取共享记忆失败: {e}")
            return []

        memories = []
        if results and results.get("documents") and results["documents"]:
            for i, doc in enumerate(results["documents"]):
                memories.append(Memory(
                    id=results["ids"][i],
                    type=results["metadatas"][i].get("type", ""),
                    content=doc,
                    importance=results["metadatas"][i].get("importance", 1),
                    session_id=None,
                    created_at=""
                ))

        return memories

    def _parse_search_results(self, results, k: int) -> List[Memory]:
        memories = []
        if results and results.get("documents") and results["documents"]:
            seen = set()
            for i, doc in enumerate(results["documents"][0]):
                mem_id = results["ids"][0][i]
                if mem_id in seen:
                    continue
                seen.add(mem_id)

                metadata = results["metadatas"][0][i]
                memories.append(Memory(
                    id=mem_id,
                    type=metadata.get("type", ""),
                    content=doc,
                    importance=metadata.get("importance", 1),
                    session_id=metadata.get("session_id"),
                    created_at=metadata.get("created_at", "")
                ))
                if len(memories) >= k:
                    break

        logger.info(f"搜索结果: {len(memories)} 条记忆")
        return memories

    def _parse_search_results_with_session(
        self,
        results_session,
        results_shared,
        k: int,
        session_id: str
    ) -> List[Memory]:
        memories = []
        seen = set()

        if results_session and results_session.get("documents") and results_session["documents"]:
            for i, doc in enumerate(results_session["documents"][0]):
                mem_id = results_session["ids"][0][i]
                if mem_id in seen:
                    continue
                seen.add(mem_id)

                metadata = results_session["metadatas"][0][i]
                memories.append(Memory(
                    id=mem_id,
                    type=metadata.get("type", ""),
                    content=doc,
                    importance=metadata.get("importance", 1),
                    session_id=metadata.get("session_id"),
                    created_at=metadata.get("created_at", "")
                ))
                if len(memories) >= k:
                    break

        if results_shared and results_shared.get("documents") and results_shared["documents"]:
            for i, doc in enumerate(results_shared["documents"][0]):
                mem_id = results_shared["ids"][0][i]
                if mem_id in seen:
                    continue
                seen.add(mem_id)

                metadata = results_shared["metadatas"][0][i]
                memories.append(Memory(
                    id=mem_id,
                    type=metadata.get("type", ""),
                    content=doc,
                    importance=metadata.get("importance", 1),
                    session_id=metadata.get("session_id"),
                    created_at=metadata.get("created_at", "")
                ))
                if len(memories) >= k:
                    break

        logger.info(f"搜索结果(含共享记忆): {len(memories)} 条记忆")
        return memories

    async def count(self) -> int:
        try:
            return self.collection.count()
        except Exception:
            return 0
