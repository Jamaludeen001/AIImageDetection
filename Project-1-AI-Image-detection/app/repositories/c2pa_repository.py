import json
import logging

from PIL import Image

logger = logging.getLogger(__name__)

MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "TIFF": "image/tiff",
    "AVIF": "image/avif",
    "HEIF": "image/heif",
    "HEIC": "image/heic",
}

# IPTC digital source types (the last path segment of the URL in the manifest).
AI_SOURCE_TYPES = {
    "trainedalgorithmicmedia",
    "compositewithtrainedalgorithmicmedia",
    "algorithmicmedia",
    "compositesynthetic",
    "trainedalgorithmicdata",
}
# Types that are not a plain camera capture of a real scene.
NON_CAPTURE_SOURCE_TYPES = {
    "digitalart",
    "digitalcreation",
    "virtualrecording",
    "screencapture",
    "composite",
    "algorithmicallyenhanced",
    "humanedits",
    "datadrivenmedia",
}
EDIT_ACTIONS = {
    "c2pa.edited",
    "c2pa.filtered",
    "c2pa.color_adjustments",
    "c2pa.drawing",
    "c2pa.cropped",
    "c2pa.placed",
}


def _blank():
    return {
        "present": False,
        "state": None,
        "issuer": None,
        "ai_generated": False,
        "edited": False,
        "flags": [],
        "error": None,
    }


def _last_segment(value) -> str:
    return str(value).rstrip("/").rsplit("/", 1)[-1].strip().lower()


def _generator_name(manifest: dict):
    info = manifest.get("claim_generator_info")
    if isinstance(info, list) and info and isinstance(info[0], dict) and info[0].get("name"):
        return info[0]["name"]
    return manifest.get("claim_generator")


class C2paRepository:
    """Reads C2PA / Content Credentials from an image.

    A missing manifest is normal (most phone photos have none) and is never an
    error. The check also degrades safely when the c2pa package is not installed.
    """

    def __init__(self):
        self.module = None
        try:
            import c2pa

            self.module = c2pa
        except Exception as exc:
            logger.warning("c2pa-python is not available, C2PA check is skipped: %s", exc)

    @property
    def available(self) -> bool:
        return self.module is not None

    def _mime(self, image_path: str):
        with Image.open(image_path) as img:
            return MIME_BY_FORMAT.get((img.format or "").upper())

    def inspect(self, image_path: str) -> dict:
        result = _blank()
        if not self.module:
            return result

        try:
            mime = self._mime(image_path)
        except Exception as exc:
            logger.warning("C2PA could not detect the image type: %s", exc)
            return result
        if not mime:
            return result

        c2pa = self.module
        try:
            with open(image_path, "rb") as handle:
                with c2pa.Reader(mime, handle) as reader:
                    store = json.loads(reader.json())
                    try:
                        result["state"] = reader.get_validation_state()
                    except Exception:
                        result["state"] = store.get("validation_state")
        except Exception as exc:
            if "ManifestNotFound" in type(exc).__name__ or "ManifestNotFound" in str(exc):
                return result
            logger.warning("C2PA read failed: %s", exc)
            result["error"] = "The C2PA data could not be read."
            return result

        result["present"] = True
        self._scan(store, result)
        return result

    def _scan(self, store: dict, result: dict) -> None:
        manifests = store.get("manifests") or {}
        active_id = store.get("active_manifest")
        active = manifests.get(active_id) or {}
        result["issuer"] = (active.get("signature_info") or {}).get("issuer")

        state = str(result["state"] or "").lower()
        if state == "invalid":
            result["flags"].append("C2PA signature is invalid, the file was changed after it was signed")

        # Walk every manifest, including those of ingredients, so an AI source
        # image that was later re-signed by a camera or editor is still found.
        for manifest in manifests.values():
            for assertion in manifest.get("assertions") or []:
                label = str(assertion.get("label") or "")
                if not label.startswith("c2pa.actions"):
                    continue
                for action in (assertion.get("data") or {}).get("actions") or []:
                    name = str(action.get("action") or "")
                    source = _last_segment(action.get("digitalSourceType") or "")
                    if source in AI_SOURCE_TYPES:
                        result["ai_generated"] = True
                        generator = _generator_name(manifest) or result["issuer"] or "unknown tool"
                        result["flags"].append(
                            "C2PA says the image is AI-generated (" + source + ", " + str(generator) + ")"
                        )
                    elif source in NON_CAPTURE_SOURCE_TYPES:
                        result["edited"] = True
                        result["flags"].append("C2PA source type is not a camera capture (" + source + ")")
                    if name in EDIT_ACTIONS:
                        result["edited"] = True
                        result["flags"].append("C2PA records an edit action (" + name + ")")

            # Older manifests put the source type on the assertion itself.
            for assertion in manifest.get("assertions") or []:
                data = assertion.get("data") or {}
                source = _last_segment(data.get("digitalSourceType") or "") if isinstance(data, dict) else ""
                if source in AI_SOURCE_TYPES and not result["ai_generated"]:
                    result["ai_generated"] = True
                    result["flags"].append("C2PA says the image is AI-generated (" + source + ")")

        result["flags"] = list(dict.fromkeys(result["flags"]))
