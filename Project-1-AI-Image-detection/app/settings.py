from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        extra="ignore",
    )

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"
    # Comma separated list tried, in order, after GEMINI_MODEL fails.
    GEMINI_FALLBACK_MODELS: str = "gemini-2.5-flash-lite"
    # Longest side, in pixels, of the copy sent to Gemini. Small photos are never enlarged.
    GEMINI_MAX_IMAGE_SIZE: int = 1280
    GEMINI_JPEG_QUALITY: int = 90

    SIGHTENGINE_API_USER_1: str = ""
    SIGHTENGINE_API_SECRET_1: str = ""
    SIGHTENGINE_API_USER_2: str = ""
    SIGHTENGINE_API_SECRET_2: str = ""
    # A Sightengine genai score at or above this is rejected as AI-generated.
    SIGHTENGINE_AI_THRESHOLD: float = 0.40

    # The photo GPS must be within this many metres of the office.
    OFFICE_RADIUS_METRES: float = 100.0


settings = Settings()
