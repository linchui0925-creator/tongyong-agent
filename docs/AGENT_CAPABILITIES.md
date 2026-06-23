# Agent 能力说明

## 核心问题

之前Agent不知道自己有什么能力！

## 解决方案

创建了完整的能力清单系统，让Agent知道自己能做什么。

## Agent现在具备的能力

### 1. 命令执行能力

```
用户：运行pytest测试
Agent：执行命令: cd backend && pytest tests/
```

### 2. 项目分析能力

```
用户：分析项目架构
Agent：
## 项目分析
backend/
├── app/      # 后端应用
frontend/
├── src/       # 前端源码
```

### 3. 智能学习能力

```
用户：记住我的编码风格
Agent：好的，已记住
```

### 4. 主动使用能力

Agent会主动执行命令，不会只是回答"我可以帮你..."

## API端点

### 智能对话

```bash
POST /api/intelligent/chat
{
  "message": "运行pytest测试"
}
```

### 获取能力清单

```bash
GET /api/intelligent/capabilities
```

### 获取使用指南

```bash
GET /api/intelligent/guide
```

## 使用示例

### 1. 分析项目架构

```python
import requests

response = requests.post(
    "http://localhost:8000/api/intelligent/chat",
    json={"message": "分析项目架构"}
)
print(response.json()["reply"])
```

### 2. 执行命令

```python
response = requests.post(
    "http://localhost:8000/api/intelligent/chat",
    json={"message": "运行pytest"}
)
print(response.json())
# {"reply": "...", "executed_command": "pytest tests/", "success": True}
```

### 3. 学习用户习惯

```python
response = requests.post(
    "http://localhost:8000/api/intelligent/chat",
    json={"message": "记住我的编码风格：详细注释"}
)
```

## 能力清单

Agent现在知道自己能：
- 运行命令
- 分析项目
- 学习用户偏好
- 使用已学习的技能
- 提供优化建议
