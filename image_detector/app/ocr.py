import logging
from app.final_ocr import FinalOCR

logger = logging.getLogger("OCRWrapper")
_engine = None

def _get_engine() -> FinalOCR:
    global _engine
    if _engine is None:
        logger.info("First OCR call — initializing engines...")
        _engine = FinalOCR()
        logger.info("OCR engines ready.")
    return _engine

def extract_text(image_path: str) -> str:
    engine = _get_engine()
    try:
        return engine.process(image_path) or ""
    except Exception as e:
        logger.exception(f"OCR failed for {image_path}")
        return f"[ERROR] OCR failed: {e}"