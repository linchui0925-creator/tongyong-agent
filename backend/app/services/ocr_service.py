"""
OCR 图片文字识别服务，支持中英文识别
优先使用PaddleOCR（识别率更高，对中文支持更好），如果未安装自动降级到pytesseract
"""
import io
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ocr_backend = None
_paddle_available = False
_tesseract_available = False

# 尝试导入PaddleOCR（优先）
try:
    from paddleocr import PaddleOCR
    _paddle_available = True
    _paddle_ocr = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)
    _ocr_backend = "paddle"
    logger.info("PaddleOCR 已加载，识别能力更强，支持更优的中英文识别")
except ImportError:
    logger.warning("PaddleOCR未安装，使用pytesseract作为后备。安装PaddleOCR可获得更好的识别效果：pip install paddlepaddle paddleocr")
    try:
        from PIL import Image
        import pytesseract
        _tesseract_available = True
        _ocr_backend = "tesseract"
    except ImportError:
        logger.warning("pytesseract也未安装，OCR功能不可用。安装命令：pip install pillow pytesseract && brew install tesseract tesseract-lang")


def is_ocr_available() -> bool:
    """检查OCR是否可用"""
    return _ocr_backend is not None


def get_ocr_backend() -> Optional[str]:
    """获取当前使用的OCR后端"""
    return _ocr_backend


def extract_text_from_image(image_path: Path) -> Optional[str]:
    """从图片中提取文字，优先使用PaddleOCR"""
    if not is_ocr_available():
        return None
    
    try:
        if _ocr_backend == "paddle":
            result = _paddle_ocr.ocr(str(image_path), cls=True)
            text_parts = []
            for idx in range(len(result)):
                res = result[idx]
                if res:
                    for line in res:
                        text_parts.append(line[1][0])
            return "\n".join(text_parts).strip() if text_parts else None
        
        elif _ocr_backend == "tesseract":
            from PIL import Image
            img = Image.open(image_path)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
            return text.strip() if text.strip() else None
    
    except Exception as e:
        logger.error(f"OCR识别失败: {e}")
        return None


def extract_text_from_image_bytes(image_bytes: bytes) -> Optional[str]:
    """从图片字节流提取文字"""
    if not is_ocr_available():
        return None
    
    try:
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(image_bytes)
            temp_path = Path(f.name)
        try:
            return extract_text_from_image(temp_path)
        finally:
            os.unlink(temp_path)
    except Exception as e:
        logger.error(f"OCR识别失败: {e}")
        return None
