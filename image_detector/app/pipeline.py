import os
import logging
from typing import Dict, Any, Optional

import cv2
import numpy as np
import requests
from PIL import Image
from PIL.ExifTags import TAGS

from app.config import OUTPUT_DIR, AIORNOT_API_KEY

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ImageForgeryDetector")


class ImageAnalysisPipeline:
    def __init__(self, software_signatures: Optional[list] = None):
        self.signatures = software_signatures or [
            'adobe', 'photoshop', 'gimp', 'canva', 'firefly',
            'stability', 'midjourney', 'dall-e', 'stable diffusion'
        ]
        self.api_key = AIORNOT_API_KEY
        if not self.api_key:
            logger.warning("AIORNOT_API_KEY not found in .env. Cloud detection will fail.")
            
        self.endpoint = "https://api.aiornot.com/v2/image/sync"

    def detect_deepfake_cloud(self, file_path: str) -> Dict[str, Any]:
        if not self.api_key:
            return {"is_detected": False, "confidence": 0.0, "error": "API key missing"}

        logger.info(f"Calling AI or Not API on: {file_path}")
        try:
            with open(file_path, "rb") as f:
                resp = requests.post(
                    self.endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"image": f},
                    params={"only": ["deepfake", "ai_generated"]} 
                )
            resp.raise_for_status()
            data = resp.json()
            
            report = data.get("report", {})
            deepfake_data = report.get("deepfake", {})
            ai_data = report.get("ai_generated", {})
            
            is_deepfake = deepfake_data.get("is_detected", False)
            is_ai = ai_data["ai"].get("is_detected", False)
            
            df_conf = deepfake_data.get("confidence", 0.0) if is_deepfake else 0.0
            ai_conf = ai_data["ai"].get("confidence", 0.0) if is_ai else 0.0
            
            max_conf = max(df_conf, ai_conf)
            is_edited = is_deepfake or is_ai
            
            return {
                "is_detected": is_edited,
                "confidence": max_conf,
                "raw_response": data
            }
        except Exception as e:
            logger.error(f"AI or Not API failed: {e}")
            return {"is_detected": False, "confidence": 0.0, "error": str(e)}

    def extract_metadata_signatures(self, file_path: str) -> bool:
        logger.info(f"Executing Metadata Analysis on: {file_path}")
        try:
            with Image.open(file_path) as img:
                for key, value in img.info.items():
                    if any(sig in str(value).lower() for sig in self.signatures):
                        logger.warning(f"Metadata signature hit found: {key} -> {value}")
                        return True

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
            logger.error(f"Metadata extraction engine failure on {file_path}: {str(e)}")
            return False

    def compute_error_level_analysis(self, file_path: str, quality: int = 90) -> str:
        logger.info(f"Computing Error Level Analysis for: {file_path}")
        temp_path = os.path.join(OUTPUT_DIR, f"resaved_temp_{os.path.basename(file_path)}.jpg")
        output_path = os.path.join(
            OUTPUT_DIR,
            f"ela_map_{os.path.splitext(os.path.basename(file_path))[0]}.png"
        )
        try:
            with Image.open(file_path) as img:
                original = img.convert('RGB')
                original.save(temp_path, 'JPEG', quality=quality)

            with Image.open(temp_path) as resaved:
                orig_arr = np.array(original, dtype=np.int32)
                resaved_arr = np.array(resaved, dtype=np.int32)

                diff_arr = np.abs(orig_arr - resaved_arr)
                max_diff = np.max(diff_arr)
                if max_diff == 0:
                    max_diff = 1

                scale = 255.0 / max_diff
                enhanced_diff = np.clip(diff_arr * scale, 0, 255).astype(np.uint8)

                Image.fromarray(enhanced_diff).save(output_path)
                logger.info(f"ELA structural map generated and stored at: {output_path}")

            return output_path
        except Exception as e:
            logger.error(f"ELA computation logic failed on {file_path}: {str(e)}")
            return ""
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def extract_edge_continuity_map(self, file_path: str) -> str:
        logger.info(f"Extracting Edge Continuity matrix from: {file_path}")
        output_path = os.path.join(
            OUTPUT_DIR,
            f"edge_map_{os.path.splitext(os.path.basename(file_path))[0]}.png"
        )
        try:
            img = cv2.imread(file_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                raise FileNotFoundError(
                    f"OpenCV backend failed to resolve file structure at: {file_path}"
                )

            edges = cv2.Canny(img, threshold1=100, threshold2=200)
            cv2.imwrite(output_path, edges)
            logger.info(f"Edge discontinuity layout mapped and stored at: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Edge continuity extraction engine failed on {file_path}: {str(e)}")
            return ""

    def execute_pipeline(self, target_a: str, target_b: str) -> Dict[str, Any]:
        results = {}
        for target in [target_a, target_b]:
            if not os.path.exists(target):
                logger.critical(f"Target path does not exist: {target}")
                continue

            logger.info(f"=== Initializing Diagnostic Workflow for target: {target} ===")
            
            # 1. PRIMARY: Cloud API
            cloud_result = self.detect_deepfake_cloud(target)
            is_edited = cloud_result.get("is_detected", False)
            confidence = cloud_result.get("confidence", 0.0)
            
            # Backend verdict: Only flag as EDITED if > 0.65
            # (Frontend will visually display "LIKELY EDITED" for 50-65%)
            verdict = "EDITED" if is_edited and confidence > 0.65 else "UNVERIFIED"
            
            # 2. AUXILIARY: Metadata, ELA, Edge
            has_signature = self.extract_metadata_signatures(target)
            ela_map = self.compute_error_level_analysis(target)
            edge_map = self.extract_edge_continuity_map(target)

            results[target] = {
                "verdict": verdict,
                "cloud_confidence": round(confidence, 4),
                "metadata_forgery_detected": has_signature,
                "ela_map_path": ela_map,
                "edge_map_path": edge_map,
                "api_error": cloud_result.get("error")
            }
        return results