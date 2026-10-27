import logging
from PIL import Image
from PIL.ExifTags import TAGS
import cv2
import numpy as np

# Configure logging to track forensic steps
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class ImageForensicsAnalyzer:
    def __init__(self, software_signatures=None):
        self.signatures = software_signatures or [
            'adobe', 'photoshop', 'gimp', 'canva', 'firefly',
            'stability', 'midjourney', 'dall-e', 'stable diffusion'
        ]

    def extract_metadata_signatures(self, file_path: str) -> bool:
        """Inspects both file info blocks (PNG) and EXIF data for editing/AI signatures."""
        logger.info(f"Executing Metadata Analysis on: {file_path}")
        try:
            with Image.open(file_path) as img:
                # 1. Check img.info (crucial for PNG text chunks, software tags, embedded prompts)
                for key, value in img.info.items():
                    if any(sig in str(value).lower() for sig in self.signatures):
                        logger.warning(f"Metadata signature hit found: {key} -> {value}")
                        return True

                # 2. Check EXIF data (standard for JPEGs and traditional image formats)
                exif_data = img._getexif()
                if exif_data:
                    for tag_id, value in exif_data.items():
                        tag_name = TAGS.get(tag_id, tag_id)
                        if tag_name == 'Software' and any(
                            sig in str(value).lower() for sig in self.signatures
                        ):
                            logger.warning(f"EXIF tag signature hit found: Software -> {value}")
                            return True
                            
            logger.info("Metadata verification passed clean.")
            return False
            
        except Exception as e:
            logger.error(f"Could not parse metadata for {file_path}: {e}")
            return False

    def analyze_comprehensive(self, file_path: str) -> dict:
        """Runs a complete check combining metadata footprints and pixel anomalies."""
        report = {
            "file_path": file_path,
            "is_suspicious": False,
            "flags": []
        }

        # Step 1: Metadata Signature Check
        has_bad_metadata = self.extract_metadata_signatures(file_path)
        if has_bad_metadata:
            report["is_suspicious"] = True
            report["flags"].append("Editing/AI software signature detected in metadata.")

        # Step 2: Pixel Noise & Edge Variance Check (OpenCV fallback for stripped metadata)
        cv_img = cv2.imread(file_path)
        if cv_img is not None:
            gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            
            # Local block variation check for pasted sections
            h, w = gray.shape
            block_size = 64
            block_variances = []
            
            for y in range(0, h - block_size, block_size):
                for x in range(0, w - block_size, block_size):
                    block = laplacian[y:y+block_size, x:x+block_size]
                    block_variances.append(np.var(block))
                    
            if block_variances:
                var_std = np.std(block_variances)
                if var_std > (np.mean(block_variances) * 1.5):
                    report["is_suspicious"] = True
                    report["flags"].append("Localized texture/noise inconsistency detected (possible paste/splice).")

        return report

# ==========================================
# 🧪 EXECUTION
# ==========================================
if __name__ == "__main__":
    analyzer = ImageForensicsAnalyzer()
    test_path = r"D:\Jamaludeen\Project-1-AI-Image-detection\images\manual_Edited_img.jpg"
    
    result = analyzer.analyze_comprehensive(test_path)
    print("\n--- Final Forensic Report ---")
    print(f"🚨 Is Suspicious: {result['is_suspicious']}")
    for flag in result['flags']:
        print(f"   - {flag}")