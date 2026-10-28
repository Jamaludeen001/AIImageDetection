import os
import time
import requests
import logging
from pathlib import Path
from dotenv import load_dotenv

# Point exactly to the .env file inside the app folder
APP_DIR = Path(__file__).resolve().parent.parent
env_path = APP_DIR / ".env"
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)

class AIImageDetector:
    def __init__(self):
        self.keys = [
            (os.getenv("SIGHTENGINE_API_USER_1"), os.getenv("SIGHTENGINE_API_SECRET_1")),
            (os.getenv("SIGHTENGINE_API_USER_2"), os.getenv("SIGHTENGINE_API_SECRET_2"))
        ]
        self.keys = [k for k in self.keys if k[0] and k[1]]
        
        self.key_cooldowns = {} 
        self.fail_counts = {} 
        
        if not self.keys:
            logger.warning("No Sightengine API credentials found in .env file.")

    def _get_lockout_time(self, fail_count: int) -> int:
        if fail_count == 1:
            return 86400  # First failure: 24 hours
        else:
            hours = min(2 ** (fail_count - 2), 24)
            return hours * 3600

    def detect(self, image_path: str) -> dict:
        if not self.keys:
            return {"error": "API credentials missing."}

        url = 'https://api.sightengine.com/1.0/check.json'
        current_time = time.time()

        keys_to_try = []
        for i in range(len(self.keys)):
            if i in self.key_cooldowns:
                if current_time < self.key_cooldowns[i]:
                    continue
            keys_to_try.append(i)

        if not keys_to_try:
            return {"error": "All API keys are currently in cooldown. Please try again later."}

        for key_index in keys_to_try:
            api_user, api_secret = self.keys[key_index]
            data = {'models': 'genai', 'api_user': api_user, 'api_secret': api_secret}
            
            try:
                with open(image_path, 'rb') as f:
                    files = {'media': f}
                    response = requests.post(url, files=files, data=data, timeout=15)
                
                if response.status_code in [429, 401]:
                    self.fail_counts[key_index] = self.fail_counts.get(key_index, 0) + 1
                    count = self.fail_counts[key_index]
                    lockout_seconds = self._get_lockout_time(count)
                    self.key_cooldowns[key_index] = time.time() + lockout_seconds
                    logger.warning(f"Key {key_index + 1} failed (Count: {count}). Locking for {lockout_seconds/3600}h. Trying next key...")
                    continue
                
                self.fail_counts[key_index] = 0
                response.raise_for_status()
                result = response.json()

                if result.get('status') == 'success':
                    scores = result.get('type', {})
                    ai_score = scores.get('ai_generated', 0)
                    ops = result.get('request', {}).get('operations', 5)
                    
                    return {
                        "success": True,
                        "is_ai_generated": ai_score >= 0.40,
                        "ai_score": ai_score,
                        "operations_used": ops,
                        "estimated_cost_usd": ops * 0.002
                    }
                else:
                    return {"error": f"Sightengine error: {result}"}

            except requests.exceptions.RequestException as e:
                logger.error(f"Network error with key {api_user}: {e}")
                return {"error": "AI detection API timeout or network failure."}

        return {"error": "All API keys have failed. Please try again later."}