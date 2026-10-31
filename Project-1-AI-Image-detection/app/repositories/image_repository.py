import base64
import os
import tempfile
from urllib.parse import urlparse

import requests


class ImageRepository:
    def save_temp(self, image_base64: str) -> str:
        payload = (image_base64 or "").strip()
        if payload.startswith("data:"):
            payload = payload.split(",", 1)[1]
        raw = base64.b64decode(payload, validate=False)
        if not raw:
            raise ValueError("Empty image")
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".img")
        try:
            handle.write(raw)
        finally:
            handle.close()
        return handle.name

    def fetch_url(self, image_url: str) -> bytes:
        parsed = urlparse((image_url or "").strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("The image link must be a full http or https URL.")
        try:
            response = requests.get(image_url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ValueError("The image link could not be downloaded.") from exc
        raw = response.content
        if not raw:
            raise ValueError("The image link was empty.")
        if len(raw) > 10 * 1024 * 1024:
            raise ValueError("The image is larger than 10MB.")
        return raw

    def delete(self, path: str) -> None:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
