# API 文档

## 概述

本系统提供完整的 RESTful API 接口，用于管理梦境系统、技能系统和工具安全框架。

## 基础信息

- **Base URL**: `http://localhost:8000`
- **认证**: 当前版本暂未实现认证机制
- **响应格式**: JSON

## API 端点

### 1. 梦境系统 API

#### 1.1 获取梦境系统状态

```
GET /api/dreaming/status
```

**响应示例**:
```json
{
  "enabled": true,
  "last_sweep": "sweep_12345",
  "pending_candidates": 10,
  "total_promoted": 25,
  "total_candidates": 35
}
```

#### 1.2 手动触发梦境扫描

```
POST /api/dreaming/trigger
```

**请求体**:
```json
{
  "force": false
}
```

**响应示例**:
```json
{
  "sweep_id": "sweep_12345",
  "light": {
    "sessions_processed": 5,
    "candidates_created": 12
  },
  "rem": {
    "themes_discovered": 3
  },
  "deep": {
    "promoted": 3,
    "rejected": 9
  },
  "status": "completed",
  "duration_seconds": 12.5
}
```

#### 1.3 获取梦境配置

```
GET /api/dreaming/config
```

**响应示例**:
```json
{
  "enabled": true,
  "frequency": "0 3 * * *",
  "lookback_days": 7,
  "min_score": 0.8,
  "weights": {
    "relevance": 0.30,
    "frequency": 0.24,
    "query_diversity": 0.15,
    "recency": 0.15,
    "consolidation": 0.10,
    "conceptual_richness": 0.06
  },
  "thresholds": {
    "min_score": 0.8,
    "min_recall_count": 3,
    "min_unique_queries": 3
  }
}
```

#### 1.4 更新梦境配置

```
PUT /api/dreaming/config
```

**请求体**:
```json
{
  "enabled": true,
  "lookback_days": 7,
  "min_score": 0.85
}
```

#### 1.5 获取梦境候选列表

```
GET /api/dreaming/candidates?status=pending&limit=50
```

**响应示例**:
```json
{
  "total": 10,
  "candidates": [
    {
      "id": "candidate_123",
      "content": "用户对Python编程很感兴趣...",
      "status": "pending",
      "final_score": 0.75,
      "concept_tags": ["python", "编程", "学习"]
    }
  ]
}
```

### 2. 工具系统 API

#### 2.1 获取所有工具

```
GET /api/tools/
```

**响应示例**:
```json
{
  "total": 7,
  "tools": [
    {
      "id": "tool_file_read",
      "name": "file_read",
      "description": "读取文件内容",
      "category": "file",
      "permission_level": 0,
      "enabled": true,
      "requires_approval": false
    }
  ]
}
```

#### 2.2 执行工具

```
POST /api/tools/execute
```

**请求体**:
```json
{
  "tool_name": "shell",
  "parameters": {
    "command": "ls -la"
  },
  "user_role": "user",
  "session_id": "session_123"
}
```

**响应示例** (安全命令):
```json
{
  "status": "success",
  "result": "...",
  "risk_level": "low"
}
```

**响应示例** (需要审批):
```json
{
  "status": "pending_approval",
  "approval_id": "approval_123",
  "risk_level": "high",
  "message": "此操作需要审批"
}
```

#### 2.3 获取角色权限

```
GET /api/tools/permissions/{role}
```

**响应示例**:
```json
{
  "role": "user",
  "permissions": [
    {
      "tool_id": "tool_file_read",
      "tool_name": "file_read",
      "granted": true
    },
    {
      "tool_id": "tool_shell",
      "tool_name": "shell",
      "granted": false
    }
  ]
}
```

#### 2.4 更新角色权限

```
POST /api/tools/permissions/{role}
```

**请求体**:
```json
{
  "tool_name": "shell",
  "granted": true
}
```

#### 2.5 获取待审批请求

```
GET /api/tools/approvals/pending?session_id=session_123
```

**响应示例**:
```json
{
  "total": 2,
  "approvals": [
    {
      "id": "approval_123",
      "tool_id": "tool_shell",
      "session_id": "session_123",
      "user_id": "user",
      "risk_assessment": {
        "risk_level": "high",
        "matched_patterns": [
          {
            "pattern": "curl.*|.*sh",
            "risk_level": "critical",
            "description": "远程代码执行"
          }
        ]
      },
      "created_at": "2026-07-15T10:30:00"
    }
  ]
}
```

#### 2.6 处理审批

```
POST /api/tools/approvals
```

**请求体** (批准):
```json
{
  "approval_id": "approval_123",
  "action": "approve"
}
```

**请求体** (拒绝):
```json
{
  "approval_id": "approval_123",
  "action": "reject",
  "reason": "命令存在安全风险"
}
```

#### 2.7 获取审计日志

```
GET /api/tools/audit/logs?risk_level=high&limit=100
```

**响应示例**:
```json
{
  "total": 50,
  "logs": [
    {
      "id": "log_123",
      "tool_id": "tool_shell",
      "session_id": "session_123",
      "user_id": "user",
      "action": "execute",
      "result": "success",
      "risk_level": "medium",
      "approval_status": "approved",
      "approved_by": "admin",
      "created_at": "2026-07-15T10:30:00"
    }
  ]
}
```

#### 2.8 获取审计统计

```
GET /api/tools/audit/statistics
```

**响应示例**:
```json
{
  "total_executions": 150,
  "successful_executions": 145,
  "failed_executions": 5,
  "success_rate": 0.967,
  "risk_distribution": {
    "low": 120,
    "medium": 20,
    "high": 8,
    "critical": 2
  },
  "tool_usage_ranking": [
    {"tool": "file_read", "count": 50},
    {"tool": "shell", "count": 30}
  ]
}
```

## 错误响应

所有错误响应遵循以下格式：

```json
{
  "detail": "错误详情描述"
}
```

**常见错误码**:

| HTTP状态码 | 描述 |
|-----------|------|
| 400 | 请求参数错误 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

## 使用示例

### Python 示例

```python
import requests

BASE_URL = "http://localhost:8000"

# 获取梦境状态
response = requests.get(f"{BASE_URL}/api/dreaming/status")
print(response.json())

# 触发梦境扫描
response = requests.post(
    f"{BASE_URL}/api/dreaming/trigger",
    json={"force": True}
)
print(response.json())

# 执行工具
response = requests.post(
    f"{BASE_URL}/api/tools/execute",
    json={
        "tool_name": "shell",
        "parameters": {"command": "ls"},
        "user_role": "user"
    }
)
print(response.json())

# 批准危险命令
response = requests.post(
    f"{BASE_URL}/api/tools/approvals",
    json={
        "approval_id": "approval_123",
        "action": "approve"
    }
)
print(response.json())
```

### JavaScript 示例

```javascript
const BASE_URL = 'http://localhost:8000';

// 获取梦境状态
fetch(`${BASE_URL}/api/dreaming/status`)
  .then(res => res.json())
  .then(data => console.log(data));

// 触发梦境扫描
fetch(`${BASE_URL}/api/dreaming/trigger`, {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({force: true})
})
  .then(res => res.json())
  .then(data => console.log(data));

// 执行工具
fetch(`${BASE_URL}/api/tools/execute`, {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    tool_name: 'shell',
    parameters: {command: 'ls'},
    user_role: 'user'
  })
})
  .then(res => res.json())
  .then(data => console.log(data));
```

## 最佳实践

1. **错误处理**: 始终检查响应状态码，处理可能的错误
2. **权限控制**: 确保使用合适的 user_role
3. **审批流程**: 高风险操作需要额外的审批步骤
4. **审计日志**: 定期审查审计日志以监控系统安全
5. **配置管理**: 敏感配置通过环境变量管理，不要硬编码
