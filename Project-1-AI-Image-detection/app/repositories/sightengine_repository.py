import logging
import time

import requests

from app.settings import settings

logger = logging.getLogger(__name__)

# 401 means the key itself is wrong, so wait a long time before trying it again.
BAD_KEY_LOCKOUT_SECONDS = 24 * 3600
# 429 means "too many requests", which clears quickly.
RATE_LIMIT_FIRST_SECONDS = 60
RATE_LIMIT_MAX_SECONDS = 3600


class SightengineRepository:
    cooldowns = {}
    fail_counts = {}

    def __init__(self):
        pairs = [
            (settings.SIGHTENGINE_API_USER_1, settings.SIGHTENGINE_API_SECRET_1),
            (settings.SIGHTENGINE_API_USER_2, settings.SIGHTENGINE_API_SECRET_2),
        ]
        self.keys = [pair for pair in pairs if pair[0] and pair[1]]

    def _lockout_seconds(self, fail_count: int, status_code: int = 429) -> int:
        """How long a key rests after a failure.

        401 (bad key): 24 hours every time.
        429 (rate limit): 1 minute, then 2, 4, 8 ... minutes, never more than 1 hour.
        """
        if status_code == 401:
            return BAD_KEY_LOCKOUT_SECONDS
        seconds = RATE_LIMIT_FIRST_SECONDS * (2 ** max(fail_count - 1, 0))
        return min(seconds, RATE_LIMIT_MAX_SECONDS)

    def detect(self, image_path: str) -> dict:
        if not self.keys:
            return {"ok": False, "error": "Sightengine credentials missing."}

        url = "https://api.sightengine.com/1.0/check.json"
        now = time.time()
        keys_to_try = []
        for index in range(len(self.keys)):
            locked_until = self.cooldowns.get(index, 0)
            if now >= locked_until:
                keys_to_try.append(index)

        if not keys_to_try:
            return {"ok": False, "error": "All Sightengine keys are in cooldown."}

        for key_index in keys_to_try:
            api_user, api_secret = self.keys[key_index]
            data = {"models": "genai,deepfake", "api_user": api_user, "api_secret": api_secret}
            try:
                with open(image_path, "rb") as handle:
                    response = requests.post(
                        url,
                        files={"media": handle},
                        data=data,
                        timeout=15,
                    )
            except requests.RequestException as exc:
                logger.error("Sightengine network error: %s", exc)
                return {"ok": False, "error": "Sightengine request failed."}

            if response.status_code in (429, 401):
                count = self.fail_counts.get(key_index, 0) + 1
                self.fail_counts[key_index] = count
                wait = self._lockout_seconds(count, response.status_code)
                self.cooldowns[key_index] = time.time() + wait
                logger.warning(
                    "Sightengine key %s got HTTP %s, resting it for %s seconds.",
                    key_index + 1,
                    response.status_code,
                    wait,
                )
                continue

            self.fail_counts[key_index] = 0
            try:
                response.raise_for_status()
                result = response.json()
            except (requests.RequestException, ValueError) as exc:
                logger.error("Sightengine response error: %s", exc)
                return {"ok": False, "error": "Sightengine response could not be read."}

            if result.get("status") != "success":
                return {"ok": False, "error": "Sightengine did not return success."}

            score = float(result.get("type", {}).get("ai_generated", 0) or 0)
            return {"ok": True, "ai_score": score}

        return {"ok": False, "error": "All Sightengine keys failed."}
