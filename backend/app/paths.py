"""运行时数据路径单一事实源 (2026-07-12 结构优化)。

历史问题: 全库 ~35 处硬编码 "./data/..." 依赖启动 cwd,
从仓库根 / backend / app 不同目录启动会各写一份 data, 造成
`data/`、`backend/data/`、`backend/app/data/` 三份分裂。

此模块以本文件位置推导 backend/ 根, 使数据路径与 cwd 解耦;
可用 TONGYONG_DATA_DIR 环境变量整体覆盖 (部署 / 测试)。

本模块零依赖 (只用 os / pathlib), 供 config.py 及各持久化模块导入,
不会引入循环依赖。
"""
import os
from pathlib import Path

# .../backend
BACKEND_ROOT = Path(__file__).resolve().parent.parent

# 统一运行时数据目录
DATA_DIR = Path(os.environ.get("TONGYONG_DATA_DIR") or (BACKEND_ROOT / "data"))


def data_path(*parts: str) -> str:
    """拼出 data 目录下的绝对路径字符串。"""
    return str(DATA_DIR.joinpath(*parts))
