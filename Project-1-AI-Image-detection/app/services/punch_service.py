import logging
import math
import re
from datetime import datetime

from PIL import Image
from PIL.ExifTags import TAGS

from app.repositories.c2pa_repository import C2paRepository
from app.repositories.gemini_repository import GeminiRepository
from app.repositories.image_repository import ImageRepository
from app.repositories.sightengine_repository import SightengineRepository
from app.settings import settings

logger = logging.getLogger(__name__)

# Editor and AI tool names. They are matched as whole words only, so "Hover" or
# "Discovered" never match a short name.
SIGNATURES = [
    "adobe", "photoshop", "lightroom", "gimp", "affinity", "pixelmator",
    "corel", "paint.net", "capture one", "luminar", "photopea",
    "canva", "picsart", "snapseed", "facetune", "vsco", "pixlr", "meitu",
    "photoroom", "epik", "hypic", "remini", "lightroom mobile", "pixelmator mobile",
    "capcut", "dazz cam",
    "firefly", "stability ai", "stabilityai", "midjourney", "dall-e", "openai", "stable diffusion",
    "automatic1111", "comfyui", "fooocus", "invokeai", "flux", "leonardo", "ideogram",
]
_SIGNATURE_RE = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(re.escape(sig) for sig in SIGNATURES) + r")(?![a-z0-9])"
)
# The only EXIF tags that name the software or the description of a photo.
EXIF_TEXT_TAGS = ("Software", "HostComputer", "ImageDescription", "Artist")
# PNG text chunks that AI tools write their prompt into.
GENERATOR_KEYS = ("parameters", "workflow", "prompt", "generator")

# Reasons that are hard evidence against the photo (wrong date, time or place).
HARD_REASON_PREFIXES = ("The photo date", "The photo time", "The photo is ")
# A branch setup problem, not a problem with the photo.
NO_OFFICE_REASON = "This branch has no office coordinates."


def _xmp_strings(node):
    """All text inside a parsed XMP block, skipping the XMP toolkit tag.

    Many ordinary phone photos carry xmptk="Adobe XMP Core 5.x". That names the
    XMP library, not an editor, so it is not evidence of editing.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() == "xmptk":
                continue
            yield str(key)
            yield from _xmp_strings(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _xmp_strings(value)
    elif node is not None:
        yield str(node)


def _signature_in(text):
    """The editor or AI tool name found in text, or None."""
    match = _SIGNATURE_RE.search(str(text).lower())
    return match.group(0) if match else None


def _blank(status, error=None):
    return {
        "status": status,
        "metadata_edited": False,
        "metadata_flags": [],
        "c2pa_present": None,
        "c2pa_state": None,
        "c2pa_issuer": None,
        "sightengine_score": None,
        "sightengine_is_ai": None,
        "is_ai_generated": None,
        "is_edited": None,
        "edit_confidence": None,
        "missing_confidence": None,
        "latitude": None,
        "longitude": None,
        "timestamp": None,
        "location": None,
        "accuracy": None,
        "distance_metres": None,
        "time_match": None,
        "matched_minute": None,
        "file_name": None,
        "error": error,
    }


def _text(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() == "null":
        return None
    return text


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _confidence(value):
    """A confidence between 0 and 1, or None when it is missing or invalid."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if 0 <= number <= 1:
        return number
    return None


def _coordinate(value, limit=180):
    """A signed decimal degree from text.

    Accepts "13.0071", "-33.8688", "33.8688 S", "80.2 W" and degrees/minutes/seconds.
    South and West are negative. A value outside +-limit (90 for latitude,
    180 for longitude) is not a coordinate and gives None.
    """
    if value is None:
        return None
    text = str(value).strip().upper()
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    if not numbers or len(numbers) > 3:
        return None
    number = float(numbers[0])
    if len(numbers) > 1:
        number += float(numbers[1]) / 60
    if len(numbers) > 2:
        number += float(numbers[2]) / 3600
    if "-" in text or re.search(r"(?<![A-Z])[SW](?![A-Z])", text):
        number = -number
    if abs(number) > limit:
        return None
    return number


PHOTO_TIME_FORMATS = (
    "%d/%m/%Y %I:%M:%S %p",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %I:%M %p",
    "%d/%m/%Y %H:%M",
    # A month name is normally converted by Gemini, but read it if it slips through.
    "%d %b %Y %I:%M:%S %p",
    "%d %b %Y %H:%M:%S",
    "%d %b %Y %I:%M %p",
    "%d %b %Y %H:%M",
)


def _parse_photo_time(timestamp):
    text = " ".join(str(timestamp).split())
    for fmt in PHOTO_TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _minute(value):
    text = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return None


def _display_date(value):
    if not value:
        return "the attendance date"
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def _haversine_metres(lat1, lon1, lat2, lon2):
    earth = 6371000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return 2 * earth * math.asin(min(1, math.sqrt(a)))


class PunchService:
    def __init__(self):
        self.images = ImageRepository()
        self.c2pa = C2paRepository()
        self.sightengine = SightengineRepository()
        self.gemini = GeminiRepository()

    def health(self) -> dict:
        return {
            "status": "healthy",
            "sightengine_keys_loaded": len(self.sightengine.keys) > 0,
            "gemini_api_loaded": self.gemini.client is not None,
            "c2pa_loaded": self.c2pa.available,
        }

    def verify(
        self,
        images: list,
        adjustment_type: int,
        attendance_date: str | None = None,
        expected_times: list | None = None,
        office_latitude: float | None = None,
        office_longitude: float | None = None,
    ) -> dict:
        expected = expected_times or []
        count_error = self._count_error(adjustment_type, len(images))
        if count_error:
            rejected = []
            for index, item in enumerate(images):
                one = _blank("rejected", count_error)
                one["file_name"] = item.get("file_name") or ("Photo " + str(index + 1))
                rejected.append(one)
            if not rejected:
                rejected.append(_blank("rejected", count_error))
            return {"status": "rejected", "error": count_error, "results": rejected}

        results = []
        for index, item in enumerate(images):
            if item.get("preload_error"):
                one = _blank("pending", item["preload_error"])
            else:
                one = self._verify_base64(
                    item.get("image_base64"),
                    attendance_date,
                    expected,
                    office_latitude,
                    office_longitude,
                    adjustment_type,
                )
            one["file_name"] = item.get("file_name")
            logger.info(
                "photo %s of %s: status=%s error=%s",
                index + 1,
                len(images),
                one.get("status"),
                one.get("error"),
            )
            if len(images) > 1 and one.get("error"):
                label = item.get("file_name") or ("Photo " + str(index + 1))
                one["error"] = str(label) + ": " + one["error"]
            results.append(one)
        combined = self._combine(results, expected, adjustment_type)
        logger.info("request type=%s result=%s", adjustment_type, combined["status"])
        return combined

    def _verify_base64(
        self,
        image_base64: str | None,
        attendance_date: str | None,
        expected_times: list,
        office_latitude: float | None,
        office_longitude: float | None,
        adjustment_type: int,
    ) -> dict:
        if not image_base64:
            return _blank("pending", "The image could not be read.")
        path = None
        try:
            path = self.images.save_temp(image_base64)
        except Exception as exc:
            logger.error("Could not store the uploaded image: %s", exc)
            return _blank("pending", "The image could not be read.")

        try:
            return self._verify_file(
                path,
                attendance_date,
                expected_times,
                office_latitude,
                office_longitude,
                adjustment_type,
            )
        finally:
            self.images.delete(path)

    def _count_error(self, adjustment_type: int, count: int) -> str | None:
        if adjustment_type == 0 and count < 1:
            return "A proof image is required for a regular adjustment."
        if adjustment_type == 1 and count != 2:
            return "A static on-site request needs exactly two photos: one check-in and one check-out."
        if adjustment_type == 2 and count != 1:
            return "A semi punch request needs exactly one photo for the missing check-in or check-out."
        if adjustment_type == 3 and count != 1:
            return "A check-in correction needs exactly one check-in photo."
        if adjustment_type not in (0, 1, 2, 3):
            return "The adjustment type is not recognized."
        return None

    def _combine(self, results: list, expected_times: list, adjustment_type: int) -> dict:
        errors = [item["error"] for item in results if item.get("error")]
        if any(item["status"] == "rejected" for item in results):
            status = "rejected"
        elif any(item["status"] != "real" for item in results):
            status = "pending"
        else:
            status = "real"
            seen = []
            for item in expected_times:
                minute = _minute(item)
                if minute and minute not in seen:
                    seen.append(minute)
            if adjustment_type == 1 and len(results) == 2 and len(seen) > 1:
                matched = [item.get("matched_minute") for item in results if item.get("matched_minute")]
                missing = [minute for minute in seen if minute not in matched]
                if missing:
                    status = "rejected"
                    errors.append(
                        "Both the check-in time and the check-out time must appear on the photos. Missing "
                        + ", ".join(missing)
                        + "."
                    )
        return {
            "status": status,
            "error": " ".join(errors) if errors else None,
            "results": results,
        }

    def _verify_file(
        self,
        path: str,
        attendance_date: str | None,
        expected_times: list,
        office_latitude: float | None,
        office_longitude: float | None,
        adjustment_type: int,
    ) -> dict:
        # STAGE A: metadata scan
        metadata = self._read_metadata(path)
        if metadata.get("error"):
            return _blank("pending", metadata["error"])

        # STAGE B: C2PA
        c2pa = self.c2pa.inspect(path)
        c2pa_fields = {
            "c2pa_present": c2pa["present"] if self.c2pa.available else None,
            "c2pa_state": c2pa["state"],
            "c2pa_issuer": c2pa["issuer"],
        }
        if c2pa["ai_generated"] or c2pa["edited"] or metadata["is_edited"]:
            flags = metadata["flags"] + c2pa["flags"]
            if c2pa["ai_generated"]:
                message = "The photo credentials show it is AI-generated: " + "; ".join(flags)
            else:
                message = "The photo metadata shows it was edited: " + "; ".join(flags)
            result = _blank("rejected", message)
            result["metadata_edited"] = True
            result["metadata_flags"] = flags
            result.update(c2pa_fields)
            return result
        if c2pa["flags"]:
            result = _blank("pending", "; ".join(c2pa["flags"]) + ". Manual review needed.")
            result["metadata_flags"] = c2pa["flags"]
            result.update(c2pa_fields)
            return result

        # STAGE C: Gemini extraction
        extracted = self.gemini.extract(path)
        if extracted.get("error"):
            return _blank("pending", extracted["error"])

        raw_ai = _as_bool(extracted.get("is_ai_generated"))
        raw_edited = _as_bool(extracted.get("is_edited"))
        edit_conf = _confidence(extracted.get("edit_confidence"))
        missing_conf = _confidence(extracted.get("missing_confidence"))
        latitude = _text(extracted.get("latitude"))
        longitude = _text(extracted.get("longitude"))
        timestamp = _text(extracted.get("timestamp"))

        result = _blank("pending")
        result.update(c2pa_fields)
        result["is_ai_generated"] = raw_ai
        result["is_edited"] = raw_edited
        result["edit_confidence"] = edit_conf
        result["missing_confidence"] = missing_conf
        result["latitude"] = latitude
        result["longitude"] = longitude
        result["timestamp"] = timestamp
        result["location"] = _text(extracted.get("location"))
        result["accuracy"] = _text(extracted.get("accuracy"))

        # A missing verdict no longer stops the photo. A missing AI verdict is
        # covered by Sightengine. A missing edit verdict is remembered and sends
        # the photo to a person at the end, because nothing else detects edits.
        edit_unknown = raw_edited is None
        is_ai = bool(raw_ai)
        is_edited = bool(raw_edited)

        logger.info(
            "gemini verdict: ai=%s edited=%s edit_confidence=%s missing_confidence=%s",
            raw_ai,
            raw_edited,
            edit_conf,
            missing_conf,
        )

        gemini_flags = []
        if is_ai:
            gemini_flags.append("Gemini marked the photo as AI-generated.")
        if is_edited:
            gemini_flags.append("Gemini marked the photo as edited.")

        # STAGE D: GPS, date, time and distance
        reasons = []
        photo_minute = None
        lat_num = _coordinate(latitude, 90)
        lon_num = _coordinate(longitude, 180)
        photo_time = _parse_photo_time(timestamp) if timestamp else None

        if lat_num is None or lon_num is None:
            reasons.append("The photo has no readable GPS address.")
        if not timestamp or photo_time is None:
            reasons.append("The photo clock could not be read.")
        else:
            photo_date = photo_time.strftime("%Y-%m-%d")
            photo_minute = photo_time.strftime("%H:%M")
            expected = [_minute(item) for item in expected_times]
            expected = [item for item in expected if item]
            date_ok = bool(attendance_date) and photo_date == attendance_date
            time_ok = bool(expected) and photo_minute in expected
            result["time_match"] = (date_ok and time_ok)
            shown = photo_time.strftime("%d/%m/%Y %I:%M %p")
            if not date_ok:
                reasons.append(
                    "The photo date "
                    + shown
                    + " does not match the attendance date "
                    + _display_date(attendance_date)
                    + "."
                )
            if not time_ok:
                wanted = ", ".join(expected) if expected else "the requested time"
                reasons.append(
                    "The photo time "
                    + photo_minute
                    + " does not match "
                    + wanted
                    + "."
                )

        if lat_num is not None and lon_num is not None:
            if office_latitude is None or office_longitude is None:
                reasons.append(NO_OFFICE_REASON)
            else:
                distance = _haversine_metres(office_latitude, office_longitude, lat_num, lon_num)
                result["distance_metres"] = round(distance, 2)
                if distance > settings.OFFICE_RADIUS_METRES:
                    reasons.append(
                        "The photo is "
                        + format(result["distance_metres"], ".2f")
                        + " metres from the office. The allowed distance is "
                        + format(settings.OFFICE_RADIUS_METRES, "g")
                        + " metres."
                    )

        hard_reasons = [item for item in reasons if item.startswith(HARD_REASON_PREFIXES)]
        setup_reasons = [item for item in reasons if item == NO_OFFICE_REASON]
        read_reasons = [
            item for item in reasons
            if item not in hard_reasons and item not in setup_reasons
        ]
        history = " ".join(gemini_flags + reasons)

        # Rejections first. The first one that applies wins.
        # 1. Wrong date, time or distance.
        if hard_reasons:
            result["status"] = "rejected"
            result["error"] = history
            return result

        # 2. Gemini is confident the photo is edited.
        if (
            is_edited
            and edit_conf is not None
            and edit_conf >= settings.GEMINI_EDIT_REJECT_CONFIDENCE
        ):
            result["status"] = "rejected"
            result["error"] = history
            return result

        # 3. GPS or clock missing, and Gemini is confident it is truly missing.
        if (
            read_reasons
            and missing_conf is not None
            and missing_conf >= settings.GEMINI_MISSING_REJECT_CONFIDENCE
        ):
            result["status"] = "rejected"
            result["error"] = history
            return result

        # Pending next: a person decides.
        # - GPS or clock missing with low confidence (probably misread)
        # - the branch has no office coordinates (setup problem)
        # - Gemini says edited with medium confidence or no confidence at all
        #   (below the review level the edited verdict is ignored)
        edit_needs_review = is_edited and (
            edit_conf is None or edit_conf >= settings.GEMINI_EDIT_REVIEW_CONFIDENCE
        )
        if reasons or edit_needs_review:
            result["status"] = "pending"
            result["error"] = history + " Manual review needed."
            return result

        # STAGE F: Sightengine. Reached when there are no reasons and Gemini is
        # not (confidently) saying edited. Gemini saying AI does not skip it.
        sight = self.sightengine.detect(path)
        if not sight.get("ok"):
            result["status"] = "pending"
            message = sight.get("error") or "Sightengine request failed."
            result["error"] = " ".join(gemini_flags + [message])
            return result

        score = float(sight["ai_score"])
        threshold = settings.SIGHTENGINE_AI_THRESHOLD
        result["sightengine_score"] = score
        if score >= threshold:
            result["status"] = "rejected"
            result["sightengine_is_ai"] = True
            result["error"] = "Sightengine marked the photo as AI-generated."
            return result

        result["sightengine_is_ai"] = False
        if is_ai:
            # Gemini says AI but Sightengine disagrees, so a person decides.
            result["status"] = "pending"
            result["error"] = (
                " ".join(gemini_flags)
                + " Sightengine score "
                + format(score, ".2f")
                + " is below "
                + format(threshold, ".2f")
                + ". Manual review needed."
            )
            return result

        if edit_unknown:
            # Nothing else can detect an edit, so Gemini's missing verdict goes to a person.
            result["status"] = "pending"
            result["error"] = "Gemini did not return an edit verdict. Manual review needed."
            return result

        result["status"] = "real"
        result["matched_minute"] = photo_minute if result.get("time_match") else None
        result["error"] = None
        return result

    def _read_metadata(self, file_path: str) -> dict:
        flags = []
        try:
            pil_img = Image.open(file_path)
        except Exception as exc:
            logger.error("Metadata open failed: %s", exc)
            return {"error": "The file is not a readable image."}

        try:
            if hasattr(pil_img, "info") and pil_img.info:
                for key, value in pil_img.info.items():
                    key_text = str(key).lower()
                    if key_text in GENERATOR_KEYS:
                        flags.append(f"Metadata hit in image info chunk [{key}]")
                        continue
                    # Raw binary blocks (the EXIF blob, the colour profile) are read
                    # through their own checks, not as text. Only a text value or a
                    # JPEG comment is searched here.
                    if isinstance(value, (bytes, bytearray)):
                        if key_text != "comment":
                            continue
                        value = bytes(value).decode("utf-8", errors="ignore")
                    if isinstance(value, str) and _signature_in(value):
                        flags.append(f"Metadata hit in image info chunk [{key}]")

            exif_data = pil_img.getexif() if hasattr(pil_img, "getexif") else None
            if exif_data:
                for tag_id, value in exif_data.items():
                    tag_name = TAGS.get(tag_id, tag_id)
                    if tag_name in EXIF_TEXT_TAGS and _signature_in(value):
                        flags.append(f"EXIF tag hit [{tag_name}]")

            xmp_data = pil_img.getxmp() if hasattr(pil_img, "getxmp") else None
            if xmp_data:
                found = _signature_in(" \n ".join(_xmp_strings(xmp_data)))
                if found:
                    flags.append(f"XMP signature match: {found}")
        except Exception as exc:
            logger.error("Metadata parse failed: %s", exc)
            return {"error": "Image metadata could not be read."}
        finally:
            pil_img.close()

        return {"is_edited": bool(flags), "flags": flags}
