# 必修 1 改动备份
# 文件: backend/app/core/langchain_agent.py
# 内容: 删 hasattr(_build_system_prompt) 错名字检查 + 加 system_prompt 读 ctx + 加 3 件 prompt 注入 (if/else 双路径)

# --- 删除 ---
#         system_prompt = ""
#         if hasattr(agent_engine, '_build_system_prompt'):
#             try:
#                 system_prompt = agent_engine._build_system_prompt()
#             except Exception as e:
#                 logger.warning(f"构建 system prompt 失败: {e}")
#         if not system_prompt:
#             system_prompt = "你是一个有用的 AI 助手，可以使用工具来完成任务。"

# --- 新增（替换上面 7 行）---
#         # 构建 system prompt
#         # ⚠️ 必修 1 修复（2026-06-07）：从 agent_engine.ctx.messages 拼出 system
#         # 旧代码用 hasattr(agent_engine, '_build_system_prompt')，但 agent.py 实际方法
#         # 叫 _inject_base_system_prompt()，导致 hasattr 永远 False → system_prompt 永
#         # 远落到 fallback "你是一个有用的 AI 助手"（降级路径）。修复后用 ctx 里的真
#         # 实 system messages 拼接（_inject_base_system_prompt() 已经在下面 else 分支
#         # 调过，ctx.messages[0] 就是完整的 base + memory + domain 装配）。
#         system_prompt = "\n\n".join(
#             m.content for m in ctx.messages if m.role == "system"
#         )
#         if not system_prompt:
#             system_prompt = "你是一个有用的 AI 助手，可以使用工具来完成任务。"

# --- 新增 (if session_id: 块里) ---
#     else:
#         # 必修 1 配套：旧代码只在 session_id 存在时调 _inject_base_system_prompt，
#         # 但新 session 也要带身份认知（跟 agent.chat() / stream_chat 一致）。
#         # 跟 agent.py line 290-292 保持一致：base + memory + domain 三件必调。
#         try:
#             agent_engine._inject_base_system_prompt()
#         except Exception as e:
#             logger.warning(f"[langchain] 注入 base system prompt 失败: {e}")
#         try:
#             await agent_engine._inject_memory(session_id or "default")
#         except Exception as e:
#             logger.warning(f"[langchain] 注入 memory 失败: {e}")
#         try:
#             await agent_engine._ensure_domain_prompts(session_id or "default")
#         except Exception as e:
#             logger.warning(f"[langchain] 注入 domain 失败: {e}")
#         yield _progress("加载历史对话...")
