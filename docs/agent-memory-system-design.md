# 全公司智能体记忆系统设计方案

**文档版本**: v1.0  
**编写日期**: 2025-05-28  
**状态**: 草稿

---

## 摘要

本文档提出一套面向 200~2000 人规模企业的智能体（Agent）记忆系统设计方案。该系统基于 MySQL 8.0 构建，支持对话记忆（conversation）、摘要记忆（summary）、事实记忆（facts）和偏好记忆（preference）四种类型，提供私有（private）、共享（shared）和公开（public）三级可见性控制，采用用户/管理员（User/Admin）两级权限模型。系统分两阶段建设：第一阶段以 MySQL FULLTEXT 全文索引提供基础检索能力；第二阶段引入 Qdrant 向量数据库实现语义相似性搜索，并通过 MCP（Model Context Protocol）协议与上层 Agent 应用集成。

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [系统架构概览](#2-系统架构概览)
3. [核心数据模型](#3-核心数据模型)
4. [记忆类型与可见性](#4-记忆类型与可见性)
5. [权限模型](#5-权限模型)
6. [写入吞吐优化：批量缓冲机制](#6-写入吞吐优化批量缓冲机制)
7. [搜索能力演进：Phase 1 → Phase 2](#7-搜索能力演进-phase-1--phase-2)
8. [MCP 集成架构](#8-mcp-集成架构)
9. [技术栈总表](#9-技术栈总表)
10. [部署与运维注意事项](#10-部署与运维注意事项)

---

## 1. 背景与目标

### 1.1 企业级 Agent 系统的记忆需求

随着 AI Agent 在企业内部的普及，每个 Agent 在与用户交互过程中会产生大量有价值的信息，包括：

- **对话上下文**：跨会话保留对话历史，使 Agent 能够理解长期项目背景
- **关键事实**：用户告知的项目信息、技术栈、团队结构等结构化事实
- **行为偏好**：用户的工作方式、代码风格偏好、常用工具等信息
- **会话摘要**：长对话的摘要，帮助 Agent 快速重拾中断的话题

### 1.2 设计目标

| 维度 | 目标 |
|------|------|
| 规模 | 支持 200~2000 名员工同时使用 |
| 延迟 | 查询 P99 < 200ms，写入 P99 < 500ms |
| 可用性 | 99.9% SLA，支持故障自动恢复 |
| 扩展性 | 数据量增长 10x 时无需架构重构 |
| 安全 | 细粒度权限控制，审计日志完整 |
| 兼容性 | 通过 MCP 协议对接主流 Agent 框架 |

### 1.3 设计约束

- **数据库选型**：优先使用已有运维能力的 MySQL 8.0，不引入额外的自托管向量数据库（Phase 1）
- **向后兼容**：Phase 1 的 API 设计需预留向量搜索扩展能力
- **多租户隔离**：同一 MySQL 实例内通过 tenant_id 实现数据隔离

---

## 2. 系统架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent Applications                       │
│   (Claude Code, Cursor, Copilot, 自研 Agent 等)              │
└─────────────────────────┬───────────────────────────────────┘
                          │ MCP (Model Context Protocol)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      MCP Gateway Service                     │
│              (协议转换 / 权限校验 / 流量管控)                  │
└─────────────────────────┬───────────────────────────────────┘
                          │
          ┌───────────────┼────────────────┐
          │               │                │
          ▼               ▼                ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│   MySQL 8.0  │   │   Qdrant    │   │   Redis     │
│  (主存储)    │   │ (Phase 2)   │   │ (缓存/缓冲)  │
│  FULLTEXT    │   │  向量检索   │   │             │
└─────────────┘   └─────────────┘   └─────────────┘
```

### 2.1 核心组件

| 组件 | 职责 | 技术选型 |
|------|------|----------|
| MCP Gateway | 协议转换、路由、鉴权 | Go / Python FastAPI |
| MySQL 8.0 | 主数据存储、FULLTEXT 检索 | MySQL 8.0.36+ |
| Qdrant (Phase 2) | 向量嵌入存储与语义相似性搜索 | Qdrant Cloud / 自托管 |
| Redis | 批量写入缓冲、会话缓存 | Redis 7.x |
| Agent SDK | 客户端库，供应用集成 | TypeScript / Python |

---

## 3. 核心数据模型

### 3.1 ER 图

```
┌──────────────┐       ┌───────────────────┐       ┌───────────────────┐
│    users     │       │   agent_memories  │       │ memory_access_log │
├──────────────┤       ├───────────────────┤       ├───────────────────┤
│ id (PK)      │──┐    │ id (PK)           │       │ id (PK)           │
│ tenant_id    │  │    │ user_id (FK)      │◄──────│ user_id (FK)      │
│ username     │  │    │ memory_type       │       │ memory_id (FK)    │
│ email        │  │    │ visibility        │       │ action            │
│ role         │  └───►│ tenant_id         │       │ ip_address        │
│ created_at   │       │ content           │       │ timestamp         │
│ updated_at   │       │ metadata (JSON)   │       │ result            │
└──────────────┘       │ embedding         │       └───────────────────┘
                      │ created_at        │
                      │ updated_at        │
                      │ expires_at        │
                      └───────────────────┘
```

### 3.2 表结构详情

#### 3.2.1 `users` 表

```sql
CREATE TABLE users (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    tenant_id     BIGINT UNSIGNED NOT NULL,
    username      VARCHAR(128) NOT NULL,
    email         VARCHAR(256) NOT NULL,
    role          ENUM('user', 'admin', 'super_admin') NOT NULL DEFAULT 'user',
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_email (email),
    UNIQUE KEY uk_tenant_email (tenant_id, email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

#### 3.2.2 `agent_memories` 表

```sql
CREATE TABLE agent_memories (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id       BIGINT UNSIGNED NOT NULL,
    memory_type   ENUM('conversation', 'summary', 'facts', 'preference') NOT NULL,
    visibility    ENUM('private', 'shared', 'public') NOT NULL DEFAULT 'private',
    tenant_id     BIGINT UNSIGNED NOT NULL,
    session_id    VARCHAR(128) DEFAULT NULL,
    content       LONGTEXT NOT NULL,
    metadata      JSON DEFAULT NULL,
    embedding     VECTOR(1536) DEFAULT NULL,  -- Phase 2 启用, MySQL 8.0.37+
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    expires_at    DATETIME DEFAULT NULL,
    INDEX idx_user_id (user_id),
    INDEX idx_memory_type (memory_type),
    INDEX idx_visibility (visibility),
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_session_id (session_id),
    INDEX idx_expires_at (expires_at),
    FULLTEXT INDEX ft_content (content),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

> **注意**：`embedding` 字段依赖 MySQL 8.0.37+ 的 `vector` 数据类型支持。若 MySQL 版本低于此版本，Phase 1 可跳过该字段，待 Phase 2 切换至 Qdrant 时统一管理向量。

#### 3.2.3 `memory_access_log` 表

```sql
CREATE TABLE memory_access_log (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id       BIGINT UNSIGNED NOT NULL,
    memory_id     BIGINT UNSIGNED NOT NULL,
    action        ENUM('read', 'write', 'update', 'delete', 'share') NOT NULL,
    ip_address    VARCHAR(45) DEFAULT NULL,
    user_agent    VARCHAR(512) DEFAULT NULL,
    result        ENUM('success', 'denied', 'error') NOT NULL,
    error_detail  TEXT DEFAULT NULL,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_memory_id (memory_id),
    INDEX idx_action (action),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (memory_id) REFERENCES agent_memories(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

---

## 4. 记忆类型与可见性

### 4.1 四种记忆类型

| 类型 | 说明 | 示例 | 自动过期 |
|------|------|------|----------|
| `conversation` | 原始对话记录，按 session 组织 | "用户要求实现 REST API" | 30 天 |
| `summary` | 对话压缩后的摘要 | "用户正在开发电商后端，使用 FastAPI" | 90 天 |
| `facts` | 提取的结构化事实 | {"project": "shop-api", "framework": "fastapi"} | 180 天 |
| `preference` | 用户偏好设置 | {"format": "black", "test_framework": "pytest"} | 永久 |

### 4.2 可见性级别

| 可见性 | 描述 | 访问规则 |
|--------|------|----------|
| `private` | 仅创建者可见 | user_id = current_user |
| `shared` | 对内共享 | tenant_id 相同且在 share_list 中 |
| `public` | 租户内公开 | tenant_id 相同的所有用户可读 |

### 4.3 记忆生命周期

```
创建 → 活跃期 → 归档策略触发 → 软删除(30天) → 硬删除
```

- 所有记忆默认设置 `expires_at`
- `conversation` 类型 30 天后降级为 `summary`（自动生成摘要）
- 软删除后 30 天执行硬删除，由后台 job 处理

---

## 5. 权限模型

### 5.1 角色定义

| 角色 | 权限范围 |
|------|----------|
| `user` | 读写自己的记忆；读取共享和公开记忆；无法跨租户访问 |
| `admin` | 读写本租户所有用户的共享/公开记忆；查看审计日志；无法读取他人私有记忆 |
| `super_admin` | 跨租户管理（仅平台运营者使用）；系统配置变更 |

### 5.2 权限检查流程

```
请求 → 解析 token → 获取 user_id/tenant_id/role
     → 检查记忆 visibility
     → private: user_id 匹配？
     → shared: tenant_id 匹配 AND 在 share_list 中？
     → public: tenant_id 匹配？
     → 记录 access_log → 返回结果
```

### 5.3 共享机制

用户可将 `private` 记忆提升为 `shared`，并指定共享对象：

```json
{
  "memory_id": 12345,
  "action": "share",
  "share_with_users": [101, 102, 103],
  "share_with_teams": ["backend-team"],
  "expires_in": "30d"
}
```

---

## 6. 写入吞吐优化：批量缓冲机制

### 6.1 问题背景

高频写入场景（如多个 Agent 同时生成记忆）下，直接写入 MySQL 会产生大量小事务，影响性能。

### 6.2 解决方案：Redis 批量缓冲

```
Agent → MCP Gateway → Redis List (write_buffer:{user_id})
                           ↓ (每 5 秒或积累 100 条)
                        Batch Worker → MySQL Bulk Insert
```

### 6.3 缓冲策略

| 参数 | 值 | 说明 |
|------|----|------|
| `BUFFER_FLUSH_INTERVAL` | 5s | 定时触发 |
| `BUFFER_MAX_SIZE` | 100 条 | 批量大小触发 |
| `BUFFER_MAX_LATENCY` | 30s | 兜底超时 |
| `RETRY_ATTEMPTS` | 3 | 失败重试 |
| `RETRY_BACKOFF` | 2s | 指数退避 |

### 6.4 写入 API 示例

```python
# POST /api/v1/memories
# 请求体
{
    "memory_type": "conversation",
    "visibility": "private",
    "content": "User asked to implement user authentication",
    "metadata": {
        "session_id": "sess_abc123",
        "tokens_used": 1200
    }
}

# 响应
{
    "id": 98765,
    "status": "buffered",  # 或 "committed"（低负载时直接写入）
    "estimated_flush": "2025-05-28T12:05:00Z"
}
```

### 6.5 批量写入 SQL 示例

```sql
INSERT INTO agent_memories (user_id, memory_type, visibility, tenant_id, session_id, content, metadata, created_at)
VALUES
    (1, 'conversation', 'private', 100, 'sess_abc', '...', '{}', NOW()),
    (1, 'conversation', 'private', 100, 'sess_abc', '...', '{}', NOW()),
    (2, 'summary', 'shared', 100, NULL, '...', '{}', NOW());
```

通过 `INSERT ... VALUES (...),(...),(...)` 批量语法，单次提交可写入数百条记录，TPS 可提升 10~50 倍。

---

## 7. 搜索能力演进：Phase 1 → Phase 2

### 7.1 Phase 1：MySQL FULLTEXT 搜索

**适用场景**：200~500 人规模，文本检索需求

```sql
-- 全文搜索示例
SELECT id, content, memory_type, created_at,
       MATCH(content) AGAINST('user authentication' IN NATURAL LANGUAGE MODE) AS relevance
FROM agent_memories
WHERE tenant_id = 100
  AND visibility IN ('shared', 'public')
  AND user_id != 1
  AND MATCH(content) AGAINST('user authentication' IN NATURAL LANGUAGE MODE)
ORDER BY relevance DESC
LIMIT 20;
```

**优点**：

- 无需额外基础设施
- 运维简单（与主库同节点）
- 支持中文分词（需配置 ngram tokenizer）

**缺点**：

- 不支持语义相似性搜索
- 大数据量下 FULLTEXT 性能下降
- 无法做向量混合检索

### 7.2 Phase 2：MySQL + Qdrant 混合检索

**适用场景**：500~2000 人规模，语义搜索需求

#### 7.2.1 向量化流程

```
用户输入 → Embedding Model (e.g., text-embedding-3-small)
        → 1536 维向量 → Qdrant 存储
        → MySQL 存储原始文本 + 向量 ID
```

#### 7.2.2 检索流程

```
查询文本 → Embedding → Qdrant ANN 检索 Top-K
         → 获取 memory_ids → MySQL 获取详情 + FULLTEXT 二次排序
         → 混合分数 = 0.7*向量分数 + 0.3*文本分数
         → 返回结果
```

#### 7.2.3 Qdrant 配置示例

```yaml
# qdrant-config.yaml
collections:
  agent_memories:
    vectors:
      size: 1536
      distance: Cosine
    optimizers:
      indexing_threshold: 10000
    wal:
      wal_capacity_mb: 1024
```

#### 7.2.4 混合检索 SQL（Phase 2）

```sql
-- Phase 2: 向量 + 全文混合检索
SELECT m.id, m.content, m.memory_type, m.created_at,
       (
           SELECT COUNT(1) FROM memory_access_log l
           WHERE l.memory_id = m.id AND l.action = 'read'
       ) AS access_count,
       RANK() OVER (ORDER BY 
           (vector_score * 0.7 + fulltext_score * 0.3) DESC,
           m.created_at DESC
       ) AS ranking
FROM agent_memories m
WHERE m.tenant_id = 100
  AND m.visibility IN ('shared', 'public')
  AND m.memory_type = 'facts'
  AND m.expires_at > NOW()
```

### 7.3 Phase 演进路线图

| 阶段 | 规模 | 搜索能力 | 主要组件 |
|------|------|----------|----------|
| Phase 1 | 200~500 人 | FULLTEXT | MySQL 8.0 |
| Phase 2 | 500~2000 人 | ANN + FULLTEXT | MySQL 8.0 + Qdrant |
| Phase 3 (规划) | 2000+ 人 | 多租户向量集群 | MySQL + Qdrant Cluster + 读写分离 |

---

## 8. MCP 集成架构

### 8.1 MCP 协议概述

MCP（Model Context Protocol）是 Anthropic 提出的标准化协议，用于在 AI 模型与应用之间传递上下文信息。MCP 采用 JSON-RPC 2.0 作为传输格式，支持：

- **Resources**：应用向模型暴露的结构化数据（类比 file system）
- **Tools**：模型可调用的动作（类比 function calling）
- **Prompts**：预定义的提示模板

### 8.2 记忆系统在 MCP 架构中的定位

```
┌─────────────────┐    MCP Resources    ┌─────────────────┐
│  AI Model       │◄───────────────────►│   MCP Gateway   │
│  (Claude Code)  │                     │                 │
└─────────────────┘                     └────────┬────────┘
                                                  │
                                    ┌─────────────┼─────────────┐
                                    │             │             │
                              Memory Query   Memory Write   Memory Admin
                                    │             │             │
                              ┌─────▼─────┐ ┌────▼────┐ ┌─────▼─────┐
                              │  Search   │ │  Write  │ │  Manage   │
                              │  (Read)   │ │(Buffer) │ │  (Admin)  │
                              └───────────┘ └─────────┘ └───────────┘
```

### 8.3 MCP 资源定义（Memory Resources）

```json
{
  "protocolVersion": "2024-11-05",
  "resources": [
    {
      "uri": "memory://tenant/{tenant_id}/user/{user_id}/private",
      "name": "user_private_memories",
      "description": "当前用户的所有私有记忆",
      "mimeType": "application/json"
    },
    {
      "uri": "memory://tenant/{tenant_id}/user/{user_id}/shared",
      "name": "user_shared_memories",
      "description": "当前用户有权限访问的共享记忆",
      "mimeType": "application/json"
    },
    {
      "uri": "memory://tenant/{tenant_id}/public",
      "name": "tenant_public_memories",
      "description": "租户内公开记忆",
      "mimeType": "application/json"
    }
  ],
  "tools": [
    {
      "name": "memory_search",
      "description": "搜索记忆内容",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "搜索关键词"},
          "memory_type": {"type": "string", "enum": ["conversation", "summary", "facts", "preference"]},
          "limit": {"type": "integer", "default": 10}
        }
      }
    },
    {
      "name": "memory_write",
      "description": "写入新记忆",
      "inputSchema": {
        "type": "object",
        "properties": {
          "memory_type": {"type": "string"},
          "content": {"type": "string"},
          "visibility": {"type": "string"},
          "metadata": {"type": "object"}
        }
      }
    }
  ]
}
```

### 8.4 MCP Gateway 设计

```
                        ┌──────────────────┐
                        │  MCP Gateway     │
                        │  (Go/FastAPI)    │
                        └────────┬─────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
    ┌────▼────┐            ┌────▼────┐            ┌────▼────┐
    │  HTTP   │            │  STDIO  │            │ WebSocket│
    │ Handler │            │ Handler │            │ Handler  │
    └─────────┘            └─────────┘            └──────────┘
         │                    │                      │
         └────────────────────┼──────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │   Request Router   │
                    │  (Token验证/路由)  │
                    └─────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
        ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
        │  Memory   │   │  Memory   │   │  Admin    │
        │  Query    │   │  Write    │   │  Service  │
        │  Service  │   │  Service  │   │           │
        └─────┬─────┘   └─────┬─────┘   └───────────┘
              │               │
              ▼               ▼
         MySQL/Redis     Write Buffer
```

### 8.5 MCP 错误处理

| 错误码 | 含义 | 处理策略 |
|--------|------|----------|
| `memory.not_found` | 记忆不存在 | 返回空结果，不抛异常 |
| `memory.access_denied` | 权限不足 | 记录审计日志，返回 403 |
| `memory.quota_exceeded` | 配额超限 | 触发告警，建议用户清理旧记忆 |
| `memory.buffer_full` | 写入缓冲满 | 降级为同步写入，记录警告 |
| `memory.embedding_failed` | 向量化失败 | 回退到纯文本存储，标记降级 |

---

## 9. 技术栈总表

| 层级 | 组件 | 技术选型 | 版本 | 备注 |
|------|------|----------|------|------|
| **应用层** | | | | |
| | MCP Gateway | Go / Python FastAPI | Go 1.21+ / FastAPI 0.110+ | 推荐 Go 以获得更好并发性能 |
| | Agent SDK (Python) | Python | 3.10+ | 供自研 Agent 集成 |
| | Agent SDK (TS) | TypeScript | 5.0+ | 供 Web 应用集成 |
| **存储层** | | | | |
| | 关系存储 | MySQL | 8.0.37+ | 需支持 VECTOR 数据类型 |
| | 向量存储 (Phase 2) | Qdrant | 1.7+ | Cloud 或自托管 |
| | 缓冲/缓存 | Redis | 7.2+ | Cluster 模式 |
| | 配置存储 | etcd / Consul | | 服务发现与配置 |
| **基础设施** | | | | |
| | 容器编排 | Kubernetes | 1.28+ | 或 Docker Compose (Phase 1) |
| | 服务网格 | Istio | 1.19+ | 可选，Phase 2 考虑 |
| | 监控 | Prometheus + Grafana | | |
| | 日志 | Loki + Grafana | | |
| | 链路追踪 | Jaeger | | |
| **安全** | | | | |
| | 密钥管理 | HashiCorp Vault | | |
| | 身份认证 | JWT + Redis Blacklist | | |
| | 审计日志 | MySQL (memory_access_log) | | 长期归档可同步至 S3 |

---

## 10. 部署与运维注意事项

### 10.1 数据库配置建议

```ini
# my.cnf 关键配置
innodb_buffer_pool_size = 16G        # 建议设置为机器内存的 60-70%
innodb_write_io_threads = 8
innodb_read_io_threads = 16
innodb_flush_log_at_trx_commit = 2   # 允许一定延迟以提升写入性能
max_connections = 500
wait_timeout = 28800

# FULLTEXT 优化
ft_min_word_len = 2
ngram_tokenizer = 1                  # 中文分词支持
```

### 10.2 容量规划

假设每个用户每天产生 50 条记忆，每条平均 1KB：

| 规模 | 日增量 | 月增量 | 年增量（未压缩） |
|------|--------|--------|-----------------|
| 200 人 | 10 MB | 300 MB | 3.6 GB |
| 500 人 | 25 MB | 750 MB | 9 GB |
| 2000 人 | 100 MB | 3 GB | 36 GB |

> 实际数据量需乘以元数据 overhead（JSON/metadata），预计总存储为上述数值的 2~3 倍。

### 10.3 监控指标

| 指标 | 告警阈值 | 说明 |
|------|----------|------|
| `memory_write_latency_p99` | > 500ms | 写入延迟异常 |
| `memory_search_latency_p99` | > 200ms | 查询延迟异常 |
| `buffer_flush_failures` | > 0 | 批量写入失败 |
| `mysql_connection_usage` | > 80% | 连接池耗尽预警 |
| `quota_usage_per_user` | > 90% | 用户配额预警 |

### 10.4 备份策略

- 每日全量备份（mysqldump）
- 每小时增量 binlog 备份
- 跨区域异地容灾（Phase 2）

---

# 竞品记忆系统深度分析

**文档版本**: v1.0  
**编写日期**: 2025-05-28  
**分析对象**: 主流 AI Coding Agent 的记忆系统

---

## 目录

1. [分析方法论](#1-分析方法论)
2. [Claude (Anthropic)](#2-claude-anthropic)
3. [GitHub Copilot](#3-github-copilot)
4. [Cursor AI](#4-cursor-ai)
5. [OpenClaw](#5-openclaw)
6. [Windsurf (Codeium)](#6-windsurf-codeium)
7. [Cline](#7-cline)
8. [OpenAI Codex](#8-openai-codex)
9. [横向对比](#9-横向对比)

---

## 1. 分析方法论

### 1.1 评估维度

我们从以下六个维度对各竞品的记忆系统进行评估：

| 维度 | 说明 |
|------|------|
| **持久性** | 记忆是否跨会话保留，保留多久 |
| **结构化** | 记忆以何种形式存储（键值、向量、文件、结构化 DB） |
| **可见性** | 记忆是用户私有还是可在项目中共享 |
| **检索能力** | 支持关键词搜索还是语义向量搜索 |
| **上下文注入** | 记忆如何被注入到模型的上下文窗口中 |
| **扩展性** | 是否支持 MCP 或第三方插件扩展 |

### 1.2 分析信息来源

- 官方文档与公开技术博客
- 用户社区反馈与 Issue 追踪
- 代码开源部分（若有）
- 发布版本说明（Release Notes）

> **免责声明**：以下分析基于公开信息，部分实现细节为合理推断而非官方确认。

---

## 2. Claude (Anthropic)

### 2.1 记忆相关功能总览

Claude 的记忆功能分为三层，层层递进：

| 功能 | 发布年份 | 说明 |
|------|----------|------|
| **Memory (Beta)** | 2024 Q3 | 跨会话记忆，自动记住关键信息 |
| **Projects** | 2024 Q4 | 项目级上下文空间，持久化项目知识 |
| **Artifacts** | 2024 Q3 | 代码片段预览与持久化展示 |
| **MCP** | 2024 Q4 | Model Context Protocol，第三方数据源集成 |

### 2.2 Memory 功能（Beta）

Claude 的 Memory 功能允许模型自动从对话中提取并存储重要信息。

**工作原理**：

1. 对话结束时，模型评估哪些信息值得记住
2. 记忆以键值对形式存储在用户级别的记忆库中
3. 新对话开始时，模型自动检索相关记忆并注入上下文

**存储结构（推断）**：

```json
{
  "user_id": "user_xxx",
  "memories": [
    {
      "id": "mem_001",
      "content": "User works primarily on Python backend services",
      "created_at": "2024-10-15T09:00:00Z",
      "last_accessed": "2025-01-20T14:30:00Z",
      "access_count": 47
    },
    {
      "id": "mem_002",
      "content": "User prefers FastAPI over Flask for new projects",
      "created_at": "2024-11-02T11:00:00Z",
      "last_accessed": null,
      "access_count": 1
    }
  ]
}
```

**局限性**：

- Memory 为用户级，无法按项目隔离
- 目前无管理员视角查看用户记忆内容
- 记忆内容对用户不可见，无法手动编辑或删除

### 2.3 Projects

Projects 是 Claude 推出的项目级上下文管理功能，解决了 Memory 无法按项目隔离的问题。

**核心特性**：

| 特性 | 说明 |
|------|------|
| 持久化上下文 | 上传文件、对话历史、项目说明，跨会话保留 |
| 项目说明 (Project Description) | 用户撰写项目概述，帮助模型理解项目背景 |
| 上传文档 | 支持 PDF、代码文件、Markdown 等 |
| 对话历史保留 | 所有与该项目相关的对话均可追溯 |

**使用场景示例**：

```
Project: Shop-API Development
├── Description: "电商后端服务，使用 FastAPI + PostgreSQL"
├── Uploaded Files:
│   ├── schema.sql
│   ├── api_routes.md
│   └── architecture.png
├── Shared Memories:
│   └── "backend-team 所有成员共享项目级上下文"
└── Conversation History:
    └── [所有在该 Project 下的对话]
```

**与 Memory 的区别**：

| 维度 | Memory | Projects |
|------|--------|----------|
| 作用域 | 用户级别 | 项目级别 |
| 内容来源 | 模型自动提取 | 用户主动上传 |
| 共享性 | 私有 | 可团队共享 |
| 管理 | 无 UI | 有专用 UI |

### 2.4 Artifacts

Artifacts 允许在对话中生成和持久化代码片段、文档、SVG 等内容。

**工作流**：

1. 模型生成代码/内容
2. 以可交互卡片形式展示
3. 用户可一键保存到项目或复制
4. 保存后的 Artifacts 获得持久链接

**应用场景**：

- 快速原型代码（React 组件、数据可视化图表）
- 技术文档草稿
- 系统架构图（PlantUML / Mermaid）

### 2.5 MCP (Model Context Protocol)

MCP 是 Anthropic 提出的开放协议，允许 Claude 与外部数据源和工具集成。

**核心概念**：

| 概念 | 说明 |
|------|------|
| **Resources** | Claude 可读取的外部数据（类比文件系统的 URI） |
| **Tools** | Claude 可执行的外部操作（函数调用） |
| **Prompts** | 预定义的提示模板 |

**MCP 服务器类型**：

1. **Filesystem Server**：读写本地文件
2. **Git Server**：操作 Git 仓库
3. **Database Server**：查询数据库
4. **Custom Server**：企业自建数据源

**示例架构**：

```
┌──────────────┐       MCP        ┌──────────────────┐
│  Claude      │◄─────────────────►│  GitHub MCP Server│
│  (Model)     │                  │                   │
└──────────────┘                  └─────────┬─────────┘
                                            │
                                      ┌─────▼─────┐
                                      │  GitHub   │
                                      │    API    │
                                      └───────────┘
```

**与记忆系统的关联**：

- MCP Resources 可作为记忆系统的数据源
- 项目级 MCP 配置可实现"项目专属记忆"
- 通过 MCP 协议，记忆系统可以作为 MCP Provider 接入 Claude

### 2.6 技术架构推断

```
┌─────────────────────────────────────────────────────┐
│                   Claude Web / API                   │
└──────────────────────────┬──────────────────────────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
      ┌─────▼─────┐  ┌─────▼─────┐  ┌───▼─────┐
      │  Memory   │  │ Projects  │  │   MCP   │
      │  Service  │  │  Service  │  │ Gateway │
      └─────┬─────┘  └─────┬─────┘  └───┬─────┘
            │              │            │
      ┌─────▼─────┐  ┌─────▼─────┐  ┌───▼─────┐
      │ Redis +   │  │ PostgreSQL│  │  External│
      │  custom   │  │ + S3      │  │ Servers │
      │  storage  │  │           │  │         │
      └───────────┘  └───────────┘  └─────────┘
```

---

## 3. GitHub Copilot

### 3.1 上下文管理策略

GitHub Copilot 采用多层次上下文注入策略，而非统一的记忆系统。

**上下文层级**：

| 层级 | 来源 | 优先级 | 说明 |
|------|------|--------|------|
| **当前文件** | 打开的标签页 | 最高 | 正在编辑的文件 |
| **相邻文件** | 最近的 tabs | 高 | 相关文件 |
| **项目文件** | 打开的工作区 | 中 | `.git` 内的文件 |
| **GitHub 上下文** | PR/Issue/Discussion | 低 | 通过 `@Github` 召唤 |

### 3.2 `copilot-instructions.md`

Copilot 支持项目级别的指令文件，用于提供项目背景知识。

**文件路径与优先级**：

```
./.github/copilot-instructions.md        # 项目级（最高）
~/.config/github-copilot/instructions.md  # 用户级
```

**使用示例**：

```markdown
# .github/copilot-instructions.md

## 项目背景
- 这是一个使用 FastAPI 构建的电商后端服务
- 主要使用 PostgreSQL 数据库
- 所有 API 返回格式统一为 `{code, message, data}`

## 代码规范
- 使用 async/await 处理所有 I/O 操作
- 错误码定义在 `errors.py` 中
- 禁止使用 `print()`，统一使用 `logger`

## 技术栈
- Python 3.11+
- FastAPI 0.110+
- SQLAlchemy 2.0
- Pydantic 2.0
```

**局限性**：

- 纯文本，需要用户手动维护
- 无法自动学习项目变化
- 无向量检索，纯文本匹配

### 3.3 Codebase Indexing

Copilot 对项目代码建立索引，以提供跨文件的语义理解能力。

**索引策略**：

1. **AST 解析**：将代码解析为抽象语法树，提取函数签名、类结构
2. **Embeddings**：将代码片段转为向量，用于语义相似性检索
3. **依赖图**：理解模块间依赖关系，提供更精准的补全

**索引范围**：

```yaml
indexed:
  - "*.py, *.js, *.ts, *.go, *.java"
  - "./src/**/*.py"
  - "!./tests/**"  # 测试文件不索引（可配置）
  - "!./node_modules/**"
  - "!./dist/**"
```

**上下文注入时机**：

- 文件打开时
- 光标位置变化时（debounced）
- 显式通过 `@` 召唤文件

### 3.4 记忆持久性

| 维度 | 实现 |
|------|------|
| 会话级记忆 | 跟随 IDE 会话，关闭后清除 |
| 项目级记忆 | `.github/copilot-instructions.md` 持久化 |
| 用户级记忆 | 用户 home 目录下的 instructions.md |
| 组织级记忆 | `.github/copilot-instructions.md`（需组织配置） |

### 3.5 与记忆系统对比

| 特性 | Copilot | 我们设计的系统 |
|------|---------|----------------|
| 持久性 | 主要靠文档，无自动记忆 | 完整数据库持久化 |
| 可见性控制 | 无 | private/shared/public |
| 检索能力 | 全文匹配 | FULLTEXT + 向量 |
| 用户管理 | 无管理员视图 | 完整 RBAC |
| 批量写入 | 不支持 | Redis 缓冲批写 |

---

## 4. Cursor AI

### 4.1 Context Engine

Cursor 的 Context Engine 是其核心记忆与上下文管理组件，采用了混合检索策略。

**检索架构**：

```
用户查询 → Query Rewriting → Parallel Retriever
                              ├── BM25 (稀疏检索)
                              ├── Embedding ANN (密集检索)
                              └── Graph Index (结构化检索)
                              └── Ranker (RRF 融合)
                              → Top-K Results
                              → LLM Context
```

**BM25 vs 向量检索**：

- **BM25（稀疏）**：适合精确关键词匹配（如函数名、变量名）
- **Embedding（密集）**：适合语义理解（如"处理支付的代码"）
- **混合融合**：使用 Reciprocal Rank Fusion (RRF) 融合两路结果

### 4.2 Composer

Composer 是 Cursor 的多文件编辑模式，其中包含了项目级上下文管理能力。

**Composer 模式特性**：

- 多文件同时编辑，保持跨文件上下文
- 文件依赖图可视化
- 批量重命名与重构
- 对话历史永久保存

### 4.3 Supercompletion

Supercompletion 是 Cursor 的代码预测引擎，学习用户的编码模式。

**工作原理**：

1. 分析项目历史中的代码模式
2. 学习函数编写习惯（如命名、缩进、注释风格）
3. 在类似上下文中提供个性化补全

**与记忆的关系**：

- 本地学习，不上传代码
- 模型权重在本地微调（Diffusion-style）
- 无法跨设备同步

### 4.4 Context Sources

Cursor 支持多种上下文来源（Context Sources），用户可手动配置优先级。

| 来源 | 类型 | 说明 |
|------|------|------|
| **Tabs** | 动态 | 当前打开的文件 |
| **Entire Repository** | 静态 | 全库索引（需手动开启） |
| **Folder** | 静态 | 指定文件夹 |
| **File** | 静态 | 单个文件 |
| **Web** | 外部 | 搜索网络 |
| **Documentation** | 外部 | 集成文档站点 |

**配置示例**：

```json
{
  "contextSources": [
    {"type": "tabs", "priority": 100},
    {"type": "folder", "path": "./src", "priority": 80},
    {"type": "file", "path": "./README.md", "priority": 60},
    {"type": "web", "query": "cursor AI documentation", "priority": 40}
  ]
}
```

### 4.5 技术特点总结

| 特性 | 说明 |
|------|------|
| 混合检索 | BM25 + Embedding + Graph |
| 本地学习 | Supercompletion 不上传代码 |
| 对话持久化 | Composer 中永久保存 |
| 上下文配置 | 用户可手动管理来源 |

---

## 5. OpenClaw

### 5.1 记忆模型：Session vs Persistent

OpenClaw 将记忆分为两大类：

| 类型 | 生命周期 | 说明 |
|------|----------|------|
| **Session Memory** | 单次会话 | 随 IDE 关闭清除，存储在内存中 |
| **Persistent Memory** | 跨会话 | 持久化到磁盘，包含项目知识 |

### 5.2 Session Memory

Session Memory 包含当前会话的对话历史和临时上下文。

**内容**：

- 最近 N 条对话（可配置，默认 100 条）
- 当前文件的函数签名和导入
- 光标位置上下文
- 当前工作区状态

**存储格式**：

```json
{
  "session_id": "sess_openclaw_abc123",
  "created_at": "2025-05-28T10:00:00Z",
  "messages": [
    {"role": "user", "content": "Implement user authentication"},
    {"role": "assistant", "content": "..."}
  ],
  "context": {
    "file_path": "./src/auth.py",
    "cursor_line": 45,
    "language": "python"
  },
  "expires_at": "2025-05-28T18:00:00Z"
}
```

### 5.3 Persistent Memory：Knowledge Files

OpenClaw 将项目知识存储在特定格式的文件中，便于版本控制。

**文件结构**：

```
.project/
├── .claude/
│   ├── knowledge/
│   │   ├── project.md        # 项目概述
│   │   ├── architecture.md   # 架构说明
│   │   ├── decisions.md       # 技术决策记录
│   │   └── api-docs.md       # API 文档
│   └── memory/
│       ├── sessions/         # 会话历史
│       └── context.json      # 持久上下文
```

**knowledge 文件说明**：

| 文件 | 内容 | 更新频率 |
|------|------|----------|
| `project.md` | 项目描述、技术栈、团队成员 | 手动更新 |
| `architecture.md` | 系统架构、模块关系 | 周级 |
| `decisions.md` | ADR (Architecture Decision Records) | 按需 |
| `api-docs.md` | API 端点说明、数据模型 | 按需 |

### 5.4 上下文注入方式

OpenClaw 使用文件观察者（File Watcher）监控 knowledge 目录变化，自动更新上下文中。

**注入流程**：

```
knowledge/*.md 变化 → File Watcher → 解析 Markdown
                                       → 提取关键信息
                                       → 更新 Session Context
                                       → LLM 可访问
```

### 5.5 与传统记忆系统的区别

| 维度 | OpenClaw | 传统方案 |
|------|----------|----------|
| 存储位置 | 本地文件系统 | 数据库 |
| 版本控制 | 支持（.project 目录在 git 中） | 需额外导出 |
| 可移植性 | 直接复制项目即可迁移 | 需备份数据库 |
| 检索能力 | 弱（依赖 LLM 上下文窗口） | 强（结构化检索） |

---

## 6. Windsurf (Codeium)

### 6.1 Cascade 架构

Windsurf 的核心是 **Cascade** 架构，这是一个层次化的上下文管理框架。

**架构层级**：

```
┌─────────────────────────────────────────────────┐
│                   Cascade Layer                   │
│  (全局上下文编排器)                                 │
├─────────────────────────────────────────────────┤
│                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │  File       │  │  Chat      │  │  Actions  │ │
│  │  Context    │  │  History   │  │  History  │ │
│  └─────────────┘  └─────────────┘  └───────────┘ │
│                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │  Project    │  │  User      │  │  External │ │
│  │  Memory     │  │  Preferences│  │  Sources  │ │
│  └─────────────┘  └─────────────┘  └───────────┘ │
│                                                  │
└─────────────────────────────────────────────────┘
```

### 6.2 Codebase Awareness

Windsurf 的 codebase awareness 功能使其理解整个代码库的结构。

**理解维度**：

1. **依赖关系**：模块间 import/export 关系图
2. **调用链**：函数调用路径和调用者
3. **语义相似性**：代码功能的语义聚类
4. **命名惯例**：项目特有的命名风格

**索引构建流程**：

```
代码文件 → AST Parser → 函数/类提取 → 依赖图构建
                            │
                            ▼
                      Embedding Model → 向量索引
                            │
                            ▼
                      语义聚类 + 调用链
```

### 6.3 Flow 工程模式

Windsurf 引入了 "Flow" 概念，用于管理复杂的多步骤任务。

**Flow 状态**：

```json
{
  "flow_id": "flow_abc123",
  "steps": [
    {"id": 1, "action": "read_file", "file": "auth.py", "status": "completed"},
    {"id": 2, "action": "implement", "feature": "JWT token", "status": "in_progress"},
    {"id": 3, "action": "test", "scope": "auth_flow", "status": "pending"}
  ],
  "context": {
    "started_at": "2025-05-28T10:00:00Z",
    "last_active": "2025-05-28T11:30:00Z"
  }
}
```

### 6.4 与记忆系统的关联

- **Project Memory**：存储 Flow 执行过程中的关键决策
- **User Preferences**：学习用户的编码风格和偏好
- **Cross-Flow Context**：同一个项目的多个 Flow 之间共享上下文

### 6.5 技术特点

| 特性 | 说明 |
|------|------|
| Cascade 架构 | 层次化上下文管理 |
| 代码库感知 | AST + Embedding 双索引 |
| Flow 模式 | 复杂任务的上下文持久化 |
| 实时索引 | 文件变化时增量更新索引 |

---

## 7. Cline

### 7.1 Project Memory

Cline 采用项目级记忆方案，记忆内容存储在项目根目录。

**存储结构**：

```
./.cline/
├── memory/
│   ├── conversations/     # 对话历史
│   │   ├── 2025-05-28.md
│   │   └── 2025-05-27.md
│   ├── context.md          # 当前项目上下文
│   ├── decisions.md        # 技术决策
│   └── user-preferences.md # 用户偏好
└── config.json
```

**文件说明**：

| 文件 | 内容 | 说明 |
|------|------|------|
| `context.md` | 项目概述、技术栈、当前任务 | 每次对话前自动加载 |
| `decisions.md` | 架构决策、API 设计决策 | 手动维护 |
| `conversations/*.md` | 按日期组织的对话历史 | 可检索 |
| `user-preferences.md` | 代码风格偏好 | 自动学习 |

### 7.2 Workspace State

Cline 维护一个工作区状态文件，记录当前工作环境的信息。

**状态内容**：

```json
{
  "workspace": {
    "root": "/Users/linc/projects/shop-api",
    "language": "python",
    "framework": "fastapi",
    "open_files": ["src/auth.py", "src/models.py"],
    "git_branch": "feature/jwt-auth"
  },
  "task": {
    "current": "Implement JWT authentication",
    "started_at": "2025-05-28T10:00:00Z",
    "progress": "60%"
  },
  "context_window": {
    "max_tokens": 120000,
    "used_tokens": 85000
  }
}
```

### 7.3 上下文注入机制

Cline 在每次请求前将相关记忆注入上下文：

```
prompt = """
[Project Context]
$(cat .cline/memory/context.md)

[Recent Decisions]
$(cat .cline/memory/decisions.md)

[User Preferences]
$(cat .cline/memory/user-preferences.md)

[Current Task]
$(cat .cline/workspace_state.json | jq -r '.task.current')

---

[User Request]
{user_input}
"""
```

### 7.4 与其他竞品对比

| 维度 | Cline | OpenClaw | 说明 |
|------|-------|----------|------|
| 存储位置 | `.cline/` | `.project/` | 均为 git-friendly |
| 上下文加载 | 自动 | 自动 | 无明显差异 |
| 对话历史 | 按日期分目录 | 混合存储 | Cline 更结构化 |
| 用户偏好学习 | 有 | 有限 | Cline 有专门的 preference 学习 |

---

## 8. OpenAI Codex

### 8.1 项目上下文管理

Codex 通过项目上下文文件管理长期记忆。

**核心文件**：

| 文件 | 说明 |
|------|------|
| `INSTRUCTIONS.md` | 项目级指令（类似 Copilot 的 copilot-instructions.md） |
| `CONTEXT.md` | 当前任务上下文 |
| `MEMORY.md` | 长期记忆（手动维护） |

**INSTRUCTIONS.md 示例**：

```markdown
# Project Instructions

## 项目概述
- 名称：Shop API
- 描述：电商后端 REST API 服务

## 技术栈
- Python 3.11
- FastAPI 0.110
- PostgreSQL 15

## 代码规范
- 使用类型提示（type hints）
- 所有 async 函数需要注释说明
- 单一职责原则

## API 规范
- 路径：`/api/v1/{resource}`
- 响应格式：`{"code": 0, "message": "", "data": {}}`
```

### 8.2 指令文件加载顺序

Codex 按以下优先级加载指令文件：

```
1. 当前工作目录的 INSTRUCTIONS.md
2. 父目录的 INSTRUCTIONS.md（向上遍历）
3. 用户 home 目录的 .codex/instructions.md
4. 系统级默认指令（如果有）
```

### 8.3 记忆持久化策略

| 记忆类型 | 持久化方式 | 说明 |
|----------|------------|------|
| 项目级 | INSTRUCTIONS.md | 用户手动维护 |
| 任务级 | CONTEXT.md | 自动生成，当前任务相关 |
| 长期 | MEMORY.md | 手动维护，跨项目 |
| 会话 | 不持久化 | 随会话结束清除 |

### 8.4 上下文窗口利用

Codex 在有限上下文窗口内优化记忆利用：

```python
# 上下文分配策略
context_budget = {
    "system_instructions": 2000,    # 固定
    "project_instructions": 4000,   # INSTRUCTIONS.md
    "relevant_files": 30000,         # 最相关的文件
    "recent_decisions": 2000,       # MEMORY.md 中相关条目
    "user_input": 5000,             # 用户当前输入
    "reserved": 5000                # 模型输出空间
}
```

### 8.5 与我们的系统对比

| 维度 | Codex | 我们的系统 |
|------|-------|------------|
| 持久化 | 文件系统 | 数据库 |
| 检索 | 无自动检索 | FULLTEXT + 向量 |
| 可见性 | 均为文件 | private/shared/public |
| 管理 | 手动 | 完整 API + 管理员 UI |
| 批量写入 | 不支持 | Redis 缓冲 |

---

## 9. 横向对比

### 9.1 功能矩阵

| 产品 | 记忆类型 | 持久化 | 可见性 | 检索能力 | MCP 支持 | 架构特点 |
|------|----------|--------|--------|----------|----------|----------|
| **Claude** | Memory + Projects | 云端 | User/Project | 语义向量 | 原生 | 分层记忆 |
| **Copilot** | Instructions | 文件 | 项目级 | 全文 | 无 | 指令驱动 |
| **Cursor** | Context Engine | 本地+云 | 用户级 | 混合检索 | 无 | 混合检索 |
| **OpenClaw** | Session + Knowledge | 本地文件 | 项目级 | 无 | 无 | 文件驱动 |
| **Windsurf** | Cascade | 本地 | 项目级 | 代码感知 | 无 | 层叠架构 |
| **Cline** | Project Memory | 本地文件 | 项目级 | 有限 | 无 | 文件观察 |
| **Codex** | Instructions | 文件 | 项目级 | 无 | 无 | 指令驱动 |

### 9.2 架构风格分类

| 架构风格 | 代表产品 | 特点 |
|----------|----------|------|
| **分层云端** | Claude | 云端统一管理，用户/项目分层 |
| **指令驱动** | Copilot, Codex | 依赖文档文件，模型理解 |
| **本地文件** | OpenClaw, Cline | git-friendly，跨设备需同步 |
| **混合检索** | Cursor, Windsurf | BM25 + 向量，本地学习 |
| **数据库驱动** | **我们的系统** | 结构化，RBAC，审计日志 |

### 9.3 各产品记忆系统评分

| 维度 | Claude | Copilot | Cursor | OpenClaw | Windsurf | Cline | Codex | 我们 |
|------|--------|---------|--------|----------|----------|-------|-------|------|
| 持久性 | ★★★★★ | ★★★ | ★★★★ | ★★★★ | ★★★★ | ★★★★ | ★★★ | ★★★★★ |
| 检索能力 | ★★★★★ | ★★ | ★★★★ | ★★ | ★★★★ | ★★★ | ★★ | ★★★★★ |
| 可见性控制 | ★★★★ | ★★ | ★★★ | ★★ | ★★★ | ★★ | ★★ | ★★★★★ |
| 扩展性 | ★★★★★ | ★★ | ★★★ | ★★★ | ★★★ | ★★★ | ★★ | ★★★★ |
| 管理能力 | ★★★★ | ★★ | ★★★ | ★★ | ★★★ | ★★ | ★★ | ★★★★★ |
| 运维复杂度 | ★★★★ | ★★★★★ | ★★★★ | ★★★★★ | ★★★★ | ★★★★★ | ★★★★★ | ★★★ |

### 9.4 关键洞察

1. **Claude 是记忆系统最成熟的产品**：分层架构（Memory → Projects）+ MCP 生态，遥遥领先
2. **多数产品采用文件驱动**：Copilot/Codex/OpenClaw/Cline 依赖文件系统，简单但检索能力弱
3. **Cursor/Windsurf 代表混合检索方向**：BM25 + 向量是下一代方向
4. **企业级需求存在缺口**：现有产品在 RBAC、审计日志、跨租户管理方面普遍薄弱
5. **MCP 是未来集成标准**：Anthropic 推动的 MCP 有望成为行业标准

### 9.5 对我们系统的启示

| 竞品优势 | 可借鉴点 | 在我们系统中的落地 |
|----------|----------|-------------------|
| Claude Memory | 自动记忆提取 | Phase 2 增加记忆自动生成 |
| Claude Projects | 项目级隔离 | 实现 project_id 隔离 |
| Cursor Context Engine | 混合检索 | Phase 2 采用 BM25 + 向量 |
| Windsurf Cascade | 层次化上下文 | MCP Gateway 分层设计 |
| OpenClaw 文件格式 | git-friendly | 可选：支持导出为 Markdown |

---

## 附录

### A. 参考资源

| 资源 | 链接 |
|------|------|
| MCP 协议规范 | https://modelcontextprotocol.io |
| MySQL 8.0 Vector Type | https://dev.mysql.com/doc/refman/8.0/en/vector-type.html |
| Qdrant 文档 | https://qdrant.tech/documentation/ |
| Claude Memory | https://docs.anthropic.com/claude/docs/memory-beta |
| Copilot Instructions | https://docs.github.com/en/copilot/customizing-copilot |

### B. 术语表

| 术语 | 说明 |
|------|------|
| ANN | Approximate Nearest Neighbor，近似最近邻检索 |
| BM25 | 搜索引擎常用的排序算法，替代 TF-IDF |
| RBAC | Role-Based Access Control，基于角色的访问控制 |
| RRF | Reciprocal Rank Fusion，多路检索结果融合算法 |
| MCP | Model Context Protocol，模型上下文协议 |
| FULLTEXT | MySQL 全文索引，支持中文分词 |
| embedding | 将文本转为稠密向量的过程 |

---

*文档结束*