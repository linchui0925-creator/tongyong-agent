"""
DomainPrompts - 领域认知提示词（代理模块）

此为向后兼容的代理层，实际内容由 domains/ 包管理。
请参见 app/domains/ 目录下的各个 .md 文件。
"""

from app.domains import get_integrator


def get_domain_prompt(domain: str) -> str:
    """获取指定领域的认知提示词"""
    integrator = get_integrator()
    return integrator.get_by_domains([domain])


def get_all_domain_prompts() -> str:
    """获取所有领域的综合认知提示词"""
    return get_integrator().get_all()


def get_relevant_domains(message: str) -> list:
    """根据用户消息判断需要注入哪些领域认知"""
    integrator = get_integrator()
    # integrator.get_filtered() 返回的是编译后的文本
    # 但我们只需要领域列表，所以从 integrator 获取匹配的域名
    matched = set()
    matched.add("identity")  # 始终注入

    domain_keywords = {
        "personality": [
            "人格", "性格", "你是谁", "你叫什么", "设定", "画像",
            "记住我", "偏好", "习惯", "风格", "语气",
        ],
        "memory": [
            "梦境", "反思", "记忆", "忘记", "还记得", "学习",
            "成长", "进步", "长期", "记住",
        ],
        "tools": [
            "运行", "执行", "创建", "删除", "修改", "启动",
            "安装", "构建", "测试", "分析", "查看", "工具",
            "命令", "shell", "terminal", "浏览器", "网页",
            "截图", "screenshot", "页面", "网址",
        ],
        "cli": [
            "运行", "执行", "命令", "shell", "terminal", "终端",
            "启动", "测试", "安装", "构建", "部署",
        ],
        "cron": [
            "定时", "调度", "计划", "周期", "每天", "cron", "定期",
        ],
    }

    message_lower = message.lower()
    for domain, keywords in domain_keywords.items():
        if any(kw in message_lower for kw in keywords):
            matched.add(domain)

    return list(matched)
