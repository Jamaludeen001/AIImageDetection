import cv2
import pytesseract
import easyocr
import logging
import time
import os
import re
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class FinalOCR:
    def __init__(self):
        logger.info("Initializing lightweight OCR engines (EasyOCR + Tesseract)...")
        self.reader = easyocr.Reader(['en'], gpu=False)
        
        self.tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(self.tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_path

        logger.info("Lightweight OCR engines initialized.")

    def process(self, image_path):
        t_start = time.time()
        logger.info(f"Processing OCR for: {image_path}")

        try:
            results = self.reader.readtext(image_path, detail=0, paragraph=True)
            easy_text = "\n".join(results)
        except Exception as e:
            logger.error(f"EasyOCR failed: {e}")
            easy_text = ""

        if not easy_text.strip():
            logger.info("EasyOCR found nothing, falling back to Tesseract...")
            try:
                img = cv2.imread(image_path)
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                tess_text = pytesseract.image_to_string(gray, lang='eng')
                final_output = tess_text.strip()
            except Exception as e:
                logger.error(f"Tesseract failed: {e}")
                final_output = "[ERROR] Text extraction failed."
        else:
            final_output = easy_text.strip()

        logger.info(f"OCR Complete in {time.time() - t_start:.2f} seconds.")
        return final_output

    def extract_location_and_time(self, ocr_text: str) -> dict:
        """
        Extracts ONLY the latitude and longitude from messy OCR text.
        Strategy: Look for "IST", grab everything until "Hospital", 
        and extract the first two decimal numbers.
        """
        extracted_data = {
            "latitude": None,
            "longitude": None
        }

        if not ocr_text:
            return extracted_data

        # Isolate the block between "IST" and "Hospital"
        block_match = re.search(r'IST(.*?)Hospital', ocr_text, re.IGNORECASE | re.DOTALL)
        
        if block_match:
            location_block = block_match.group(1)
            # Find all decimal numbers in that block
            coords = re.findall(r'(\d{1,3}\.\d{4,8})', location_block)
            
            if len(coords) >= 2:
                extracted_data["latitude"] = coords[0]
                extracted_data["longitude"] = coords[1]

        return extracted_data


class HeavyFinalOCR:
    """
    Preserved for future use if PaddleOCR is needed.
    """
    def __init__(self):
        from paddleocr import PaddleOCR, PPStructureV3
        logger.info("Initializing HEAVY OCR engines (PaddleOCR)...")
        self.paddleocr_reader = PaddleOCR(
            lang='en', use_textline_orientation=True, use_doc_orientation_classify=False,
            use_doc_unwarping=False, enable_mkldnn=True
        )
        try:
            self.table_engine = PPStructureV3(enable_mkldnn=True)
            self.has_table_engine = True
        except Exception as e:
            logger.warning(f"Table engine unavailable: {e}")
            self.has_table_engine = False

    def process(self, image_path):
        # (Preserved as is from previous version)
        pass 