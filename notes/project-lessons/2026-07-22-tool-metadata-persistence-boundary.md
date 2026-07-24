# 工具元数据与用户正文的存储边界

> 状态：已修复
> 日期：2026-07-22
> 关联：[项目笔记首页](../README.md)

## 现象

历史会话中的 assistant 消息显示了本不应对用户可见的内容：

```text
<<<TOOL_META_JSON>>>{"tools_used":["write_file"],"commands_executed":[]}<<<TOOL_META_JSON_END>>>
```

该问题在刷新页面、重新加载会话历史时尤其明显。

## 根因

`backend/app/core/agent_hooks.py` 的 `hook_memory_save()` 曾把 `tools_used` 和 `commands_executed` 序列化为 JSON，再以 `TOOL_META_JSON` 标记拼接到 assistant 正文中，随后将拼接后的字符串写入 SQLite `messages.content`。

前端并未生成该标记；它只是将已经被污染的历史正文渲染出来。前端对标记的剥离只能作为兼容旧数据的兜底，不能阻止新的污染写入。

## 修复

assistant 会话消息现在只持久化 `final_reply`。工具调用信息继续保留在适合机器消费的结构化通道中：

- SSE `done` 事件的 `tools_used` 和 `commands_executed`
- turn artifact 的 `final_answer` 与 `turn_manifest`
- 工具调用的 trace / settlement 记录

## 经验

### 1. 用户正文与运行元数据必须分层

用户可见正文只能包含可展示的自然语言结果。工具调用、命令、耗时、审计信息应使用显式字段、独立事件或独立持久化记录。

### 2. 不要用正文尾部 marker 传输结构化数据

把结构化数据嵌入正文会污染：

- 历史会话回放
- 全文搜索与向量检索
- 上下文注入
- 导出、复制和第三方客户端

### 3. UI 清理不是根因修复

前端剥离能降低旧数据的可见性，但数据一旦入库，其他消费者仍可能读取到。应先修写入边界，再按需要清理历史数据。

### 4. 排障应沿数据生命周期验证

本次有效的检查顺序是：

1. 检查 SSE `content` / `done` 的职责边界。
2. 检查前端流式状态和历史回放是否重组正文。
3. 检查 SQLite 写入点和写入的原始值。
4. 找到 `hook_memory_save()` 的拼接逻辑后，在源头删除它。

## 回归检查

- 新建一次包含工具调用的会话。
- 刷新页面并重载该会话。
- 确认 assistant 正文不含 `TOOL_META_JSON`、`tools_used` 或 `commands_executed` 原始 JSON。
- 确认工具调用信息仍可从 SSE 完成事件、trace 与 turn artifact 获取。

## 后续

历史 SQLite 数据可能仍含旧标记。清理前先备份数据库，并以事务执行定向迁移；不要依赖前端显示层作为数据清洗手段。
