"""
安全配置 - 命令白名单和禁止模式

供 terminal 工具和 CLI executor 共同使用。
"""

_ALLOWED_COMMANDS = [
    # 文件查看
    "cat", "less", "more", "head", "tail", "wc", "diff",
    # 文件操作
    "cp", "mv", "rm", "touch", "mkdir", "chmod", "chown",
    # 文本处理
    "grep", "rg", "awk", "sed", "sort", "uniq",
    # 文件查找
    "find", "locate", "which", "type",
    # 目录与路径
    "ls", "pwd", "cd", "tree", "du", "df",
    # 进程管理
    "ps", "top", "htop", "kill", "killall",
    # 网络
    "curl", "wget", "ping", "nc", "ss", "netstat",
    # 压缩
    "tar", "gzip", "gunzip", "zip", "unzip", "bzip2", "xz",
    # SHELL 内置
    "echo", "printf", "source", "export",
    # Python 生态
    "python", "python3", "pip", "pip3", "pytest", "mypy", "ruff", "black", "flake8", "uv",
    # Node 生态
    "node", "npm", "npx", "yarn", "pnpm", "bun",
    # 版本控制
    "git", "svn",
    # 容器
    "docker", "docker-compose",
    # 数据库
    "sqlite3", "redis-cli", "psql", "mysql",
    # 构建工具
    "make", "cmake", "cargo", "rustc", "go", "gcc", "g++", "clang",
    # 系统信息
    "date", "cal", "whoami", "id", "uname", "hostname", "uptime", "dmesg",
    # macOS 特定
    "open", "brew", "sw_vers", "defaults", "plutil",
    # 环境
    "env", "printenv", "xargs", "time", "watch",
    # 编码与校验
    "base64", "shasum", "sha256sum", "md5sum",
    # 杂项
    "jq", "yq", "rsync", "screen", "tmux",
]

_FORBIDDEN_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"sudo\s+",
    r"curl.*\|.*sh",
    r"wget.*\|.*sh",
    r">\s*/etc/",
    r"mkfs",
    r"dd\s+.*of=/dev/",
    r":\(\)\{\s*:\|:",
]