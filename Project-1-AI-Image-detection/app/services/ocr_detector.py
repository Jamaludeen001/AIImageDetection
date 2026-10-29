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
            You are a strict forensic auditor validating an attendance selfie watermark. 
            Analyze the image and return ONLY a valid JSON object with these exact keys.

            Rules for extraction:
            1. "latitude": The raw latitude number ONLY (e.g., 13.007155).
            2. "longitude": The raw longitude number ONLY (e.g., 80.206531).
            3. "location": The full address text shown.
            4. "accuracy": The GPS accuracy (e.g., 23.2 m).
            5. "timestamp": Read the date and time printed in the GPS box. If logically invalid, return "invalid".
            
            6. "watermark": Look for the REPEATING DIAGONAL text stamped across the photo. 
               - DO NOT extract the static text at the bottom of the GPS box that says "This photo is taken from HRMS DRAIVF application".
               - ONLY extract the diagonal repeating stamp. If there is NO diagonal watermark anywhere in the image, return null.

            STRICT VALIDATION RULES:
            7. "is_valid_timestamp": 
               - TRUE only if the time in the GPS box is logically valid.
               - FALSE if logically impossible (e.g., hour > 12 with AM/PM).

            8. "is_valid_watermark": 
               - This key MUST be a boolean (true or false).
               - If the "watermark" field is null, this MUST be false.
               - TRUE ONLY IF ALL of the following are met:
                 a) The diagonal watermark is present and clearly readable.
                 b) The text strictly follows the pattern: "HRMS DRAIVF • [Date] • [Coordinates]".
                 c) The Date/Time inside the diagonal watermark EXACTLY MATCHES the Date/Time in the GPS box.
               - FALSE if ANY of the following occur:
                 a) The diagonal watermark is completely MISSING from the image.
                 b) The text is overlapping/scrambled so badly it breaks the pattern.
                 c) The timestamp in the watermark does NOT match the timestamp in the GPS box.

            Return ONLY valid JSON.
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
                        
                        # Clean up coordinates
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

            return {"error": "All AI models are currently experiencing high demand."}

        except Exception as e:
            logger.error(f"Gemini OCR failed for {image_path}: {e}")
            return {"error": str(e)}
