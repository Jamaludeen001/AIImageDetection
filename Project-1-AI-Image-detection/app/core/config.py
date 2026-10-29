import os
from pathlib import Path
from dotenv import load_dotenv

# 1. Get the absolute path to the 'app' directory
# __file__ is app/core/config.py -> parent is core -> parent.parent is app
APP_DIR = Path(__file__).resolve().parent.parent

# 2. Define the exact path to the .env file
ENV_PATH = APP_DIR / ".env"

# 3. Load the .env file exactly once
load_dotenv(dotenv_path=ENV_PATH)

class Settings:
    # Application
    PROJECT_NAME: str = "Image Forensics API"
    
    # AI Keys
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    SIGHTENGINE_API_USER_1: str = os.getenv("SIGHTENGINE_API_USER_1", "")
    SIGHTENGINE_API_SECRET_1: str = os.getenv("SIGHTENGINE_API_SECRET_1", "")
    SIGHTENGINE_API_USER_2: str = os.getenv("SIGHTENGINE_API_USER_2", "")
    SIGHTENGINE_API_SECRET_2: str = os.getenv("SIGHTENGINE_API_SECRET_2", "")

# Instantiate it so other files can import it
settings = Settings()