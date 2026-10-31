import json
import logging
import time
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from app.settings import settings

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
PROMPT_FILE = "punch_prompt.md"


def load_punch_prompt() -> str:
    path = PROMPTS_DIR / PROMPT_FILE
    if not path.is_file():
        raise FileNotFoundError(f"Gemini prompt file is missing: {path}")
    return path.read_text(encoding="utf-8").strip()


PROMPT = load_punch_prompt()

# Tells Gemini the exact shape of the answer, so it cannot return the wrong keys or types.
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "is_ai_generated": {"type": "BOOLEAN"},
        "is_edited": {"type": "BOOLEAN"},
        "latitude": {"type": "STRING", "nullable": True},
        "longitude": {"type": "STRING", "nullable": True},
        "timestamp": {"type": "STRING", "nullable": True},
        "location": {"type": "STRING", "nullable": True},
        "accuracy": {"type": "STRING", "nullable": True},
    },
    "required": [
        "is_ai_generated",
        "is_edited",
        "latitude",
        "longitude",
        "timestamp",
        "location",
        "accuracy",
    ],
}


def model_list() -> list:
    """The main model first, then the fallbacks from settings, without repeats."""
    names = [settings.GEMINI_MODEL or "gemini-3.5-flash-lite"]
    names += [item.strip() for item in (settings.GEMINI_FALLBACK_MODELS or "").split(",")]
    seen = []
    for name in names:
        if name and name not in seen:
            seen.append(name)
    return seen


class GeminiRepository:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.model_id = settings.GEMINI_MODEL or "gemini-3.5-flash-lite"
        self.client = None
        if self.api_key:
            from google import genai
            self.client = genai.Client(api_key=self.api_key)
        else:
            logger.warning("GEMINI_API_KEY is missing.")

    def _prepare_image(self, image_path: str, max_size: int | None = None) -> bytes:
        """A JPEG copy for Gemini: turned upright, and shrunk only if it is larger than max_size."""
        limit = max_size or settings.GEMINI_MAX_IMAGE_SIZE
        with Image.open(image_path) as img:
            # Phones often store a portrait photo sideways plus a "rotate me" note.
            img = ImageOps.exif_transpose(img)
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail((limit, limit), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=settings.GEMINI_JPEG_QUALITY)
            return buffer.getvalue()

    def _config(self, types, use_schema: bool):
        options = {"temperature": 0.0, "response_mime_type": "application/json"}
        if use_schema:
            options["response_schema"] = types.Schema.model_validate(RESPONSE_SCHEMA)
        return types.GenerateContentConfig(**options)

    def extract(self, image_path: str) -> dict:
        if not self.client:
            return {"error": "Gemini API key missing."}

        try:
            from google.genai import types
            image_bytes = self._prepare_image(image_path)
        except Exception as exc:
            logger.error("Could not prepare image for Gemini: %s", exc)
            return {"error": "Could not read the image for text extraction."}

        for model in model_list():
            use_schema = True
            for attempt in range(3):
                try:
                    response = self.client.models.generate_content(
                        model=model,
                        contents=[
                            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                            PROMPT,
                        ],
                        config=self._config(types, use_schema),
                    )
                    data = json.loads(response.text)
                    if not isinstance(data, dict):
                        raise ValueError("Gemini did not return a JSON object.")
                    if data.get("latitude") is not None:
                        data["latitude"] = str(data["latitude"]).replace("°", "").strip()
                    if data.get("longitude") is not None:
                        data["longitude"] = str(data["longitude"]).replace("°", "").strip()
                    return data
                except Exception as exc:
                    error_msg = str(exc)
                    if "503" in error_msg or "UNAVAILABLE" in error_msg or "429" in error_msg:
                        logger.warning("Model %s busy (attempt %s).", model, attempt + 1)
                        time.sleep(2)
                    elif use_schema and ("INVALID_ARGUMENT" in error_msg or "schema" in error_msg.lower()):
                        # This model did not accept the response schema. Ask again without it.
                        logger.warning("Model %s rejected the response schema, retrying without it.", model)
                        use_schema = False
                    else:
                        logger.error("Gemini error with %s: %s", model, error_msg)
                        break
            logger.warning("Model %s failed. Trying the next model.", model)

        return {"error": "Gemini could not read this image."}
