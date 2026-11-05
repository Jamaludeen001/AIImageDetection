"""Punch / attendance photo verification.

Every uploaded image runs through the same pipeline:

    A. Metadata scan   (PIL: info chunks, EXIF, XMP editor/generator signatures)
    B. C2PA inspection (content credentials)
    C. Gemini vision   (AI/edit verdict + GPS, date and time read off the photo)
    D. Rule checks     (date, time, office distance, confidence thresholds)
    E. Sightengine     (AI-image score)

Only two statuses are ever returned, per photo and for the whole request:
"approved" and "rejected".

Failures of external services (Gemini / Sightengine) or unexpected internal
errors are reported as rejections flagged with ``service_error`` so callers can
tell "try again later" apart from "this photo is not acceptable". The real
failure reason is written to the server log only, never to the response.
"""
from __future__ import annotations

import logging
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from PIL import Image
from PIL.ExifTags import TAGS

from app.repositories.c2pa_repository import C2paRepository
from app.repositories.gemini_repository import GeminiRepository
from app.repositories.image_repository import ImageRepository
from app.repositories.sightengine_repository import SightengineRepository
from app.settings import settings

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

APPROVED = "approved"
REJECTED = "rejected"

VALID_ADJUSTMENT_TYPES = (0, 1, 2, 3)
STATIC_ON_SITE = 1  # adjustment type that needs both check-in and check-out photos

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
EXIF_TEXT_TAGS = ("Software", "HostComputer", "ImageDescription", "Artist")
GENERATOR_KEYS = ("parameters", "workflow", "prompt", "generator")

HARD_REASON_PREFIXES = ("The photo date", "The photo time", "The photo is ")
NO_OFFICE_REASON = "This branch has no office coordinates."

# Shown to the caller when an external service fails or an unexpected internal
# error happens. The real reason only goes to the server log.
SERVICE_UNAVAILABLE = "Photo verification is temporarily unavailable. Please try again later."

PHOTO_TIME_FORMATS = (
    "%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %I:%M %p", "%d/%m/%Y %H:%M",
    "%d %b %Y %I:%M:%S %p", "%d %b %Y %H:%M:%S", "%d %b %Y %I:%M %p", "%d %b %Y %H:%M",
)

EARTH_RADIUS_METRES = 6_371_000


# --------------------------------------------------------------------------- #
# Small pure helpers
# --------------------------------------------------------------------------- #

def _xmp_strings(node: Any):
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


def _signature_in(text: Any) -> str | None:
    match = _SIGNATURE_RE.search(str(text).lower())
    return match.group(0) if match else None


def _blank(status: str, error: str | None = None) -> dict:
    """Per-photo result with every field present, so the response shape is stable."""
    return {
        "status": status, "metadata_edited": False, "metadata_flags": [],
        "c2pa_present": None, "c2pa_state": None, "c2pa_issuer": None,
        "sightengine_score": None, "sightengine_is_ai": None,
        "is_ai_generated": None, "is_edited": None,
        "edit_confidence": None, "missing_confidence": None,
        "latitude": None, "longitude": None, "timestamp": None,
        "location": None, "accuracy": None, "distance_metres": None,
        "time_match": None, "matched_minute": None, "file_name": None,
        "service_error": False,
        "error": error,
    }


def _service_failure() -> dict:
    """Rejected photo caused by a service/internal failure, not by the photo."""
    result = _blank(REJECTED, SERVICE_UNAVAILABLE)
    result["service_error"] = True
    return result


def _request_result(
    status: str,
    error: str | None,
    results: list,
    service_error: bool = False,
    service_errors: list | None = None,
) -> dict:
    """Request-level response. Every return path of verify() goes through here."""
    return {
        "status": status,
        "error": error,
        "service_error": service_error,
        "service_errors": service_errors or [],
        "results": results,
    }


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() == "null":
        return None
    return text


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _confidence(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 1 else None


def _coordinate(value: Any, limit: float = 180) -> float | None:
    """Parse decimal or degrees/minutes/seconds text such as 13°05'30"N."""
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


def _parse_photo_time(timestamp: Any) -> datetime | None:
    text = " ".join(str(timestamp).split())
    for fmt in PHOTO_TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _minute(value: Any) -> str | None:
    text = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return None


def _display_date(value: Any) -> str:
    if not value:
        return "the attendance date"
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return str(value)


def _haversine_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_METRES * math.asin(min(1, math.sqrt(a)))


def _reject(result: dict, message: str | None) -> dict:
    result["status"] = REJECTED
    result["error"] = message
    return result


# --------------------------------------------------------------------------- #
# Internal value objects
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class _Thresholds:
    """Validated snapshot of the numeric settings used by the pipeline."""

    office_radius_metres: float
    edit_reject: float
    edit_review: float
    missing_reject: float
    sightengine_ai: float


@dataclass(frozen=True)
class _Context:
    """Everything one request needs, shared by all of its photos."""

    request_id: str
    adjustment_type: int
    attendance_date: str | None
    expected_minutes: tuple
    office_latitude: float | None
    office_longitude: float | None
    thresholds: _Thresholds


@dataclass
class _Provenance:
    """Outcome of stages A and B."""

    rejection: dict | None = None
    c2pa_fields: dict = field(default_factory=dict)
    c2pa_flags: list = field(default_factory=list)
    notes: list = field(default_factory=list)


@dataclass
class _Findings:
    """Outcome of stages C and D for one photo."""

    result: dict
    notes: list
    gemini_flags: list
    reasons: list
    hard_reasons: list
    read_reasons: list
    is_ai: bool
    is_edited: bool
    edit_unknown: bool
    edit_conf: float | None
    missing_conf: float | None
    photo_minute: str | None


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #

class PunchService:
    def __init__(self):
        self.images = ImageRepository()
        self.c2pa = C2paRepository()
        self.sightengine = SightengineRepository()
        self.gemini = GeminiRepository()
        # Fail fast at start-up if the configuration is unusable.
        self._load_thresholds()

    # ----------------------------------------------------------------- config

    @staticmethod
    def _load_thresholds() -> _Thresholds:
        def read(name: str, low: float, high: float | None = None) -> float:
            try:
                value = float(getattr(settings, name))
            except (AttributeError, TypeError, ValueError) as exc:
                raise ValueError(f"Setting {name} is missing or not a number.") from exc
            if value < low or (high is not None and value > high):
                raise ValueError(f"Setting {name}={value} is outside the allowed range.")
            return value

        thresholds = _Thresholds(
            office_radius_metres=read("OFFICE_RADIUS_METRES", 0),
            edit_reject=read("GEMINI_EDIT_REJECT_CONFIDENCE", 0, 1),
            edit_review=read("GEMINI_EDIT_REVIEW_CONFIDENCE", 0, 1),
            missing_reject=read("GEMINI_MISSING_REJECT_CONFIDENCE", 0, 1),
            sightengine_ai=read("SIGHTENGINE_AI_THRESHOLD", 0, 1),
        )
        if thresholds.edit_review > thresholds.edit_reject:
            logger.warning(
                "GEMINI_EDIT_REVIEW_CONFIDENCE is above GEMINI_EDIT_REJECT_CONFIDENCE; "
                "the review band will never apply."
            )
        return thresholds

    # ----------------------------------------------------------------- health

    def health(self) -> dict:
        return {
            "status": "healthy",
            "sightengine_keys_loaded": len(self.sightengine.keys) > 0,
            "gemini_api_loaded": self.gemini.client is not None,
            "c2pa_loaded": self.c2pa.available,
        }

    # ----------------------------------------------------------- public entry

    def verify(
        self,
        images: list,
        pdfs: list | None = None,
        adjustment_type: int = 0,
        attendance_date: str | None = None,
        expected_times: list | None = None,
        office_latitude: float | None = None,
        office_longitude: float | None = None,
    ) -> dict:
        pdfs = pdfs or []

        if adjustment_type not in VALID_ADJUSTMENT_TYPES:
            return _request_result(REJECTED, "The adjustment type is not recognized.", [])

        # PDFs are ignored: only uploaded images are verified.
        if not images:
            if pdfs:
                # PDF-only upload: nothing to verify, so it is approved.
                return _request_result(APPROVED, None, [])
            return _request_result(REJECTED, "No photo was uploaded.", [])

        expected_minutes = tuple(
            minute for minute in (_minute(item) for item in (expected_times or [])) if minute
        )
        ctx = _Context(
            request_id=uuid.uuid4().hex[:8],
            adjustment_type=adjustment_type,
            attendance_date=attendance_date,
            expected_minutes=expected_minutes,
            office_latitude=office_latitude,
            office_longitude=office_longitude,
            thresholds=self._load_thresholds(),
        )

        # Every image goes through the full verification flow on its own.
        results = []
        for index, item in enumerate(images):
            one = self._verify_item(item, ctx)
            one["file_name"] = getattr(item, "file_name", None)

            logger.info(
                "[%s] photo %s/%s status=%s service_error=%s error=%s",
                ctx.request_id, index + 1, len(images),
                one.get("status"), one.get("service_error"), one.get("error"),
            )
            if len(images) > 1 and one.get("error"):
                label = one["file_name"] or ("Photo " + str(index + 1))
                one["error"] = str(label) + ": " + one["error"]
            results.append(one)

        combined = self._combine(results, ctx)
        logger.info(
            "[%s] request type=%s status=%s service_error=%s",
            ctx.request_id, adjustment_type, combined["status"], combined["service_error"],
        )
        return combined

    # ------------------------------------------------------ per-photo plumbing

    def _verify_item(self, item: Any, ctx: _Context) -> dict:
        preload_error = getattr(item, "preload_error", None)
        if preload_error:
            return _blank(REJECTED, preload_error)

        image_base64 = getattr(item, "image_base64", None)
        if not image_base64:
            return _blank(REJECTED, "The image could not be read.")

        try:
            path = self.images.save_temp(image_base64)
        except Exception as exc:
            logger.error("[%s] could not store the uploaded image: %s", ctx.request_id, exc)
            return _blank(REJECTED, "The image could not be read.")

        try:
            return self._verify_file(path, ctx)
        except Exception:
            # Safety net: an unexpected exception must never become an HTTP 500.
            logger.exception("[%s] unexpected error while verifying the image", ctx.request_id)
            return _service_failure()
        finally:
            try:
                self.images.delete(path)
            except Exception:
                logger.warning("[%s] could not delete temp file", ctx.request_id, exc_info=True)

    def _combine(self, results: list, ctx: _Context) -> dict:
        rejected = [item for item in results if item["status"] == REJECTED]
        if rejected:
            real = [item for item in rejected if not item.get("service_error")]
            service = [item for item in rejected if item.get("service_error")]

            # Service failures are always listed, whatever else was rejected.
            service_errors = [
                {"file_name": item.get("file_name"), "error": item.get("error")}
                for item in service
            ]
            if real:
                # At least one photo was rejected for a real reason, so this is
                # not a service error: `error` carries only the real reasons.
                service_error = False
                errors = [item["error"] for item in real if item.get("error")]
            else:
                # Every rejection was a service failure.
                service_error = True
                errors = [item["error"] for item in service if item.get("error")]
            return _request_result(
                REJECTED, " ".join(errors) if errors else None,
                results, service_error, service_errors,
            )

        # All photos approved. Static on-site still needs both the check-in and
        # check-out times to appear across the photos, but only when every
        # photo was fully read and matched a time.
        seen = list(dict.fromkeys(ctx.expected_minutes))
        if (
            ctx.adjustment_type == STATIC_ON_SITE
            and len(results) >= 2
            and len(seen) > 1
            and all(item.get("matched_minute") for item in results)
        ):
            matched = [item["matched_minute"] for item in results]
            missing = [minute for minute in seen if minute not in matched]
            if missing:
                return _request_result(
                    REJECTED,
                    "Both the check-in time and the check-out time must appear on the photos. Missing "
                    + ", ".join(missing)
                    + ".",
                    results,
                )

        return _request_result(APPROVED, None, results)

    # ------------------------------------------------------------ the pipeline

    def _verify_file(self, path: str, ctx: _Context) -> dict:
        provenance = self._check_provenance(path)
        if provenance.rejection is not None:
            return provenance.rejection

        extracted = self._call_gemini(path)
        if extracted.get("error"):
            logger.error("[%s] gemini failed: %s", ctx.request_id, extracted["error"])
            result = _service_failure()
            result["metadata_flags"] = list(provenance.c2pa_flags)
            result.update(provenance.c2pa_fields)
            return result

        findings = self._assess(extracted, provenance, ctx)
        decision = self._decide(findings, ctx)
        if decision is not None:
            return decision

        return self._check_sightengine(path, findings, ctx)

    # Stage A + B ------------------------------------------------------------

    def _check_provenance(self, path: str) -> _Provenance:
        metadata = self._read_metadata(path)
        if metadata.get("error"):
            return _Provenance(rejection=_blank(REJECTED, metadata["error"]))

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
            result = _blank(REJECTED, message)
            result["metadata_edited"] = True
            result["metadata_flags"] = flags
            result.update(c2pa_fields)
            return _Provenance(rejection=result)

        # C2PA flags alone are notes, not a verdict: keep them and carry on.
        notes = ["; ".join(c2pa["flags"]) + "."] if c2pa["flags"] else []
        return _Provenance(c2pa_fields=c2pa_fields, c2pa_flags=list(c2pa["flags"]), notes=notes)

    # Stage C (external call) ------------------------------------------------

    def _call_gemini(self, path: str) -> dict:
        """Never raises. Failures come back as {"error": ...}."""
        try:
            extracted = self.gemini.extract(path)
        except Exception as exc:
            logger.exception("Gemini call raised")
            return {"error": str(exc)}
        if not isinstance(extracted, dict):
            return {"error": "Gemini returned an unexpected response."}
        return extracted

    # Stage C + D (interpretation) -------------------------------------------

    def _assess(self, extracted: dict, provenance: _Provenance, ctx: _Context) -> _Findings:
        raw_ai = _as_bool(extracted.get("is_ai_generated"))
        raw_edited = _as_bool(extracted.get("is_edited"))
        edit_conf = _confidence(extracted.get("edit_confidence"))
        missing_conf = _confidence(extracted.get("missing_confidence"))
        latitude = _text(extracted.get("latitude"))
        longitude = _text(extracted.get("longitude"))
        timestamp = _text(extracted.get("timestamp"))

        result = _blank(APPROVED)
        result.update(provenance.c2pa_fields)
        result["metadata_flags"] = list(provenance.c2pa_flags)
        result["is_ai_generated"] = raw_ai
        result["is_edited"] = raw_edited
        result["edit_confidence"] = edit_conf
        result["missing_confidence"] = missing_conf
        result["latitude"] = latitude
        result["longitude"] = longitude
        result["timestamp"] = timestamp
        result["location"] = _text(extracted.get("location"))
        result["accuracy"] = _text(extracted.get("accuracy"))

        is_ai = bool(raw_ai)
        is_edited = bool(raw_edited)
        logger.info(
            "[%s] gemini verdict: ai=%s edited=%s edit_confidence=%s missing_confidence=%s",
            ctx.request_id, raw_ai, raw_edited, edit_conf, missing_conf,
        )

        gemini_flags = []
        if is_ai:
            gemini_flags.append("Gemini marked the photo as AI-generated.")
        if is_edited:
            gemini_flags.append("Gemini marked the photo as edited.")

        reasons = []
        photo_minute = None
        lat_num = _coordinate(latitude, 90)
        lon_num = _coordinate(longitude, 180)
        photo_time = _parse_photo_time(timestamp) if timestamp else None

        if lat_num is None or lon_num is None:
            reasons.append("The photo has no readable GPS address.")

        if photo_time is None:
            reasons.append("The photo clock could not be read.")
        else:
            photo_date = photo_time.strftime("%Y-%m-%d")
            photo_minute = photo_time.strftime("%H:%M")
            date_ok = bool(ctx.attendance_date) and photo_date == ctx.attendance_date
            time_ok = bool(ctx.expected_minutes) and photo_minute in ctx.expected_minutes
            result["time_match"] = date_ok and time_ok
            if not date_ok:
                reasons.append(
                    "The photo date "
                    + photo_time.strftime("%d/%m/%Y %I:%M %p")
                    + " does not match the attendance date "
                    + _display_date(ctx.attendance_date)
                    + "."
                )
            if not time_ok:
                wanted = ", ".join(ctx.expected_minutes) if ctx.expected_minutes else "the requested time"
                reasons.append("The photo time " + photo_minute + " does not match " + wanted + ".")

        if lat_num is not None and lon_num is not None:
            if ctx.office_latitude is None or ctx.office_longitude is None:
                reasons.append(NO_OFFICE_REASON)
            else:
                distance = _haversine_metres(
                    ctx.office_latitude, ctx.office_longitude, lat_num, lon_num
                )
                result["distance_metres"] = round(distance, 2)
                allowed = ctx.thresholds.office_radius_metres
                if distance > allowed:
                    reasons.append(
                        "The photo is "
                        + format(result["distance_metres"], ".2f")
                        + " metres from the office. The allowed distance is "
                        + format(allowed, "g")
                        + " metres."
                    )

        hard_reasons = [item for item in reasons if item.startswith(HARD_REASON_PREFIXES)]
        read_reasons = [
            item for item in reasons
            if item not in hard_reasons and item != NO_OFFICE_REASON
        ]
        return _Findings(
            result=result,
            notes=provenance.notes,
            gemini_flags=gemini_flags,
            reasons=reasons,
            hard_reasons=hard_reasons,
            read_reasons=read_reasons,
            is_ai=is_ai,
            is_edited=is_edited,
            edit_unknown=raw_edited is None,
            edit_conf=edit_conf,
            missing_conf=missing_conf,
            photo_minute=photo_minute,
        )

    # Stage D (decision) -----------------------------------------------------

    def _decide(self, f: _Findings, ctx: _Context) -> dict | None:
        """Return a final result, or None when the photo should go on to Sightengine."""
        limits = ctx.thresholds
        history = " ".join(f.notes + f.gemini_flags + f.reasons)

        if f.hard_reasons:
            return _reject(f.result, history)

        if f.is_edited and f.edit_conf is not None and f.edit_conf >= limits.edit_reject:
            return _reject(f.result, history)

        if f.read_reasons and f.missing_conf is not None and f.missing_conf >= limits.missing_reject:
            return _reject(f.result, history)

        edit_needs_review = f.is_edited and (
            f.edit_conf is None or f.edit_conf >= limits.edit_review
        )
        if f.reasons or edit_needs_review:
            f.result["status"] = APPROVED
            f.result["error"] = history
            return f.result

        return None

    # Stage E ----------------------------------------------------------------

    def _call_sightengine(self, path: str) -> dict:
        """Never raises. Failures come back as {"ok": False, ...}."""
        try:
            sight = self.sightengine.detect(path)
        except Exception as exc:
            logger.exception("Sightengine call raised")
            return {"ok": False, "error": str(exc)}
        if not isinstance(sight, dict):
            return {"ok": False, "error": "Sightengine returned an unexpected response."}
        return sight

    def _check_sightengine(self, path: str, f: _Findings, ctx: _Context) -> dict:
        result = f.result
        sight = self._call_sightengine(path)

        score = None
        if sight.get("ok"):
            try:
                score = float(sight["ai_score"])
            except (KeyError, TypeError, ValueError):
                logger.error("[%s] sightengine returned no usable score", ctx.request_id)
        else:
            logger.error("[%s] sightengine failed: %s", ctx.request_id, sight.get("error"))

        if score is None:
            # Everything gathered so far stays on the result; only the verdict changes.
            result["status"] = REJECTED
            result["error"] = SERVICE_UNAVAILABLE
            result["service_error"] = True
            return result

        threshold = ctx.thresholds.sightengine_ai
        result["sightengine_score"] = score
        if score >= threshold:
            result["sightengine_is_ai"] = True
            return _reject(result, " ".join(f.notes + ["Sightengine marked the photo as AI-generated."]))

        result["sightengine_is_ai"] = False
        result["status"] = APPROVED

        if f.is_ai:
            # Gemini says AI but Sightengine disagrees: only hard rules or
            # Sightengine reject, so approve and note the conflict.
            result["error"] = (
                " ".join(f.notes + f.gemini_flags)
                + " Sightengine score "
                + format(score, ".2f")
                + " is below "
                + format(threshold, ".2f")
                + "."
            )
            return result

        if f.edit_unknown:
            result["error"] = " ".join(f.notes + ["Gemini did not return an edit verdict."])
            return result

        result["matched_minute"] = f.photo_minute if result.get("time_match") else None
        result["error"] = " ".join(f.notes) if f.notes else None
        return result

    # Stage A (metadata) -----------------------------------------------------

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
