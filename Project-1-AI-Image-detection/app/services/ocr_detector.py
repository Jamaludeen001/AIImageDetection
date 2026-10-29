import json
import time
import logging
from PIL import Image
from io import BytesIO
from google import genai
from google.genai import types
from ..core.config import settings

logger = logging.getLogger(__name__)

class AttendanceOCR:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not found in settings.")
            self.client = None
        else:
            self.client = genai.Client(api_key=self.api_key)
            
        self.model_id = "gemini-3.5-flash-lite"

    def _prepare_image(self, image_path: str, max_size: int = 800) -> bytes:
        with Image.open(image_path) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            return buffer.getvalue()

    def extract_attendance_data(self, image_path: str) -> dict:
        if not self.client:
            return {"error": "Gemini API key missing."}

        try:
            image_bytes = self._prepare_image(image_path)

            prompt = """
            Extract the following information from this attendance selfie image. 
            Return ONLY a valid JSON object with these exact keys:
            {
                "latitude": "The raw latitude number ONLY (e.g., 13.007155). No symbols or letters.",
                "longitude": "The raw longitude number ONLY (e.g., 80.206531). No symbols or letters.",
                "timestamp": "The date and time shown STRICTLY FOLLOW the format dd/mm/yyyy hh:mm:ss AM/PM)",
                "location": "The full address text shown",
                "accuracy": "The GPS accuracy (e.g., 23.2 m)"
            }
            If a field is not visible, return null for that key.
            """

            models_to_try = [
                self.model_id,          
                "gemini-2.5-flash-lite",
                "gemini-1.5-flash"      
            ]

            for model in models_to_try:
                for attempt in range(2): 
                    try:
                        response = self.client.models.generate_content(
                            model=model,
                            contents=[
                                types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
                                prompt
                            ],
                            config=types.GenerateContentConfig(
                                temperature=0.0,
                                response_mime_type="application/json"
                            )
                        )

                        data = json.loads(response.text)
                        
                        if data.get("latitude"): data["latitude"] = str(data["latitude"]).replace("°", "").strip()
                        if data.get("longitude"): data["longitude"] = str(data["longitude"]).replace("°", "").strip()

                        return data

                    except Exception as e:
                        error_msg = str(e)
                        if "503" in error_msg or "UNAVAILABLE" in error_msg or "429" in error_msg:
                            logger.warning(f"Model {model} busy (Attempt {attempt+1}). Retrying in 2s...")
                            time.sleep(2)
                        else:
                            logger.error(f"Hard error with {model}: {error_msg}")
                            break 
                
                logger.warning(f"Model {model} failed completely. Switching to next fallback...")

            return {"error": "All AI models are currently experiencing high demand. Please try again later."}

        except Exception as e:
            logger.error(f"Gemini OCR failed for {image_path}: {e}")
            return {"error": str(e)}