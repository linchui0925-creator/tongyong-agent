"""
Vision Model - MiniCPM-V-2_6 本地视觉分析

用于 Agent 截屏分析，理解屏幕内容并指导下一步操作。
"""

import importlib
import importlib.util
import logging
import sys
import types
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# 模型路径
MODEL_PATH = Path(__file__).resolve().parent.parent.parent / "models"

# 全局模型缓存
_model = None
_tokenizer = None
_processor = None


def _ensure_pkg_structure():
    """确保模型文件可以作为包加载（处理相对导入）"""
    pkg_name = "minicpmv_local"
    if pkg_name in sys.modules:
        return

    pkg = types.ModuleType(pkg_name)
    sys.modules[pkg_name] = pkg

    def load_sub(parent_name: str, name: str, path: Path):
        full_name = f"{parent_name}.{name}" if parent_name else name
        spec = importlib.util.spec_from_file_location(full_name, str(path))
        m = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = m
        spec.loader.exec_module(m)
        return m

    # 依赖顺序
    load_sub(pkg_name, "resampler", MODEL_PATH / "resampler.py")
    load_sub(pkg_name, "modeling_navit_siglip", MODEL_PATH / "modeling_navit_siglip.py")
    load_sub(pkg_name, "configuration_minicpm", MODEL_PATH / "configuration_minicpm.py")
    load_sub(pkg_name, "modeling_minicpmv", MODEL_PATH / "modeling_minicpmv.py")
    load_sub(pkg_name, "image_processing_minicpmv", MODEL_PATH / "image_processing_minicpmv.py")
    load_sub(pkg_name, "processing_minicpmv", MODEL_PATH / "processing_minicpmv.py")
    load_sub(pkg_name, "tokenization_minicpmv_fast", MODEL_PATH / "tokenization_minicpmv_fast.py")


def load_minicpm_model() -> Tuple:
    """加载 MiniCPM-V-2_6 模型和处理器（懒加载，单例）"""
    global _model, _tokenizer, _processor

    if _model is not None and _tokenizer is not None:
        return _model, _tokenizer, _processor

    logger.info("正在加载 MiniCPM-V-2_6 模型...")

    try:
        import torch
        from transformers import AutoTokenizer

        _ensure_pkg_structure()

        # 导入模型类
        import minicpmv_local.modeling_minicpmv as modeling_mod
        import minicpmv_local.processing_minicpmv as processing_mod
        import minicpmv_local.image_processing_minicpmv as image_proc_mod
        MiniCPMVConfig = modeling_mod.MiniCPMVConfig

        # 从本地加载配置（不访问 HuggingFace）
        config = MiniCPMVConfig.from_pretrained(str(MODEL_PATH), trust_remote_code=True)

        import minicpmv_local.tokenization_minicpmv_fast as tok_mod
        MiniCPMVTokenizerFast = tok_mod.MiniCPMVTokenizerFast

        # 使用自定义 tokenizer 类（支持 MiniCPMV 特殊 token）
        _tokenizer = MiniCPMVTokenizerFast.from_pretrained(str(MODEL_PATH))

        # 手动从本地文件加载 image processor（避免访问 HuggingFace）
        import json
        image_proc_dict = json.load(open(MODEL_PATH / 'preprocessor_config.json'))
        image_processor = image_proc_mod.MiniCPMVImageProcessor.from_dict(image_proc_dict)
        _processor = processing_mod.MiniCPMVProcessor(image_processor=image_processor, tokenizer=_tokenizer)

        device = "cpu"
        logger.info(f"使用设备: {device} (MPS 显存不足，切换到 CPU)")

        _model = modeling_mod.MiniCPMV(config)
        _model.to(device)
        _model.eval()

        # 加载权重
        logger.info("正在加载模型权重...")
        from safetensors import safe_open

        state_dict = {}
        for i in range(1, 5):
            sf_path = MODEL_PATH / f"model-0000{i}-of-00004.safetensors"
            if sf_path.exists():
                with safe_open(sf_path, framework="pt", device="cpu") as f:
                    for key in f.keys():
                        state_dict[key] = f.get_tensor(key)
                logger.info(f"Loaded {sf_path.name}")

        _model.load_state_dict(state_dict, strict=False)
        _model.to(device)
        _model.eval()
        logger.info("MiniCPM-V-2_6 模型加载完成")

        return _model, _tokenizer, _processor

    except Exception as e:
        logger.error(f"MiniCPM-V-2_6 模型加载失败: {e}", exc_info=True)
        raise


def analyze_screenshot(
    image_path: str,
    prompt: str = "你是一个桌面助手。描述这张截图的内容，包括：1)这是什么应用/界面；2)界面上有哪些可点击的元素（如按钮、输入框、列表项等）；3)如果要进行操作（如点击、输入），应该在屏幕什么位置。请用中文描述。",
    max_tokens: int = 512,
) -> str:
    """
    分析截图内容。

    Args:
        image_path: 截图文件路径
        prompt: 给模型的指令
        max_tokens: 最大生成 token 数

    Returns:
        模型对截图的文字描述
    """
    model, tokenizer, processor = load_minicpm_model()

    from PIL import Image

    try:
        image = Image.open(image_path).convert("RGB")
    except Exception as e:
        return f"无法读取截图: {e}"

    try:
        result = model.chat(
            image=image,
            msgs=[{"role": "user", "content": prompt}],
            tokenizer=tokenizer,
            processor=processor,
            max_new_tokens=max_tokens,
            sampling=True,
        )
        return result

    except Exception as e:
        logger.error(f"MiniCPM-V 推理失败: {e}", exc_info=True)
        return f"截图分析失败: {e}"


def quick_analyze(image_path: str) -> str:
    """快速截图分析（默认 prompt）"""
    return analyze_screenshot(image_path)