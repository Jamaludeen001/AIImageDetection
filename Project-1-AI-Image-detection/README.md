# Punch verification API

This is a small FastAPI service that checks attendance proof photos for the HRMS punch-raise flow. HRMS sends the photos (or another caller sends public image links). This service decides whether each photo is a real office photo for that request.

It does not update the HRMS database. It only returns a JSON result. HRMS reads that result and approves, rejects, or leaves the request pending.

The service listens on `http://127.0.0.1:8001`. HRMS calls `http://127.0.0.1:8001/punch-verify`.

## What one photo check does

The photo count is checked first. If the count is wrong for the adjustment type, the request is rejected immediately. No image is downloaded, and Gemini and Sightengine are not called.

For each photo that has the right count, the checks run in this order. A failed step stops the later steps for that photo.

1. **File read.** The bytes must be a readable image. A file that cannot be opened stays pending.
2. **Local metadata and C2PA.** Editor names in the file (Photoshop, Canva, AI tools, and similar) and Content Credentials (C2PA) are read from the file itself. If the photo is marked edited or AI-generated, it is rejected. Gemini and Sightengine are not called. A phone photo with no C2PA manifest is normal and continues. Other C2PA flags stay pending for manual review.
3. **Gemini, one call.** The prompt file is sent once. Gemini returns whether the photo looks AI-generated or edited, plus the GPS panel text: latitude, longitude, timestamp, location, and accuracy. Gemini's AI and edited answers do **not** reject a photo on their own. They are kept and settled in step 5.
4. **Date, time and office distance.** The date on the photo must be the attendance date, the minute must match the adjustment type rule, and the photo GPS must be within the allowed distance of the office (100 metres by default, `OFFICE_RADIUS_METRES`). A mismatch is a rejection, even if Gemini raised a flag. A photo with no readable GPS or clock, or no office coordinates, stays pending. Sightengine is not called for any of these.
5. **Sightengine.** Called when the rules above passed and Gemini did not say "edited" without "AI". The `genai` score is used.
   - Score at or above `SIGHTENGINE_AI_THRESHOLD` (0.40 by default): **rejected** as AI-generated, whatever Gemini said.
   - Score below the threshold and Gemini did not flag the photo: **real**.
   - Score below the threshold but Gemini flagged it as AI-generated: **pending**, for a person to decide, because the two services disagree.
   - Gemini flagged it as edited only: **pending** without calling Sightengine, because Sightengine cannot detect edits.
   - Keys missing or the call failed: **pending**. The service does not invent a rejection.

Seconds are ignored when times are compared. Only the hour and minute matter.

## Adjustment types

`adjustment_type` is required. The service cannot tell the request types apart without it.

| Value | Request | How many photos | Clock rule |
| --- | --- | --- | --- |
| `0` | Regular adjustment | At least 1 proof photo | The photo is still checked as a real office photo for that date. The minute does not have to match check-in or check-out. |
| `1` | Static on-site | Exactly 2 | One photo minute must be the check-in time. The other must be the check-out time. |
| `2` | Semi punch | Exactly 1 | That minute must be the missing check-in or the missing check-out (the one time you send in `expected_times`). |
| `3` | Check-in correction | Exactly 1 | That minute must be the corrected check-in time. |

`expected_times` are 24-hour times such as `09:30` or `18:30`. Seconds are optional and ignored.

`attendance_date` is `YYYY-MM-DD`. The date printed on the photo must be that same day.

## Result status

The top-level `status` is one of:

- `real` — every photo passed. HRMS treats this as approved.
- `rejected` — at least one photo failed a hard check, or the photo count was wrong. `error` explains why.
- `pending` — the check could not be finished (service key missing, Gemini or Sightengine down, unreadable clock, missing GPS, missing office coordinates, or a link that could not be downloaded). This is not a rejection.

Each item in `results` is one photo and uses the same status values.

## Endpoints

### `GET /health`

Shows whether the process is up and whether the keys loaded. It does not print the keys.

```json
{
  "status": "healthy",
  "sightengine_keys_loaded": true,
  "gemini_api_loaded": true,
  "c2pa_loaded": true
}
```

`sightengine_keys_loaded` and `gemini_api_loaded` should both be `true` before you raise a punch. If either is `false`, requests stay pending.

### `GET /health/live`

```json
{"status": "healthy"}
```

### `POST /punch-verify`

Send the image bytes. This is the endpoint HRMS uses.

You can send several images in `images`, or one image in `image_base64`. `image_base64` may be raw base64 or a `data:` URL. JPG and PNG are the expected types.

```json
{
  "adjustment_type": 1,
  "attendance_date": "2026-10-28",
  "expected_times": ["09:30", "18:30"],
  "office_latitude": 13.007155,
  "office_longitude": 80.206531,
  "images": [
    {"image_base64": "<base64>", "file_name": "check-in.jpeg"},
    {"image_base64": "<base64>", "file_name": "check-out.jpeg"}
  ]
}
```

### `POST /punch-verify-urls`

Same checks and the same response. The only difference is that each photo is a full public `http` or `https` URL. The service downloads it with a normal GET. No login and no token are sent. `http://localhost/...` works, which is what the local XAMPP uploads need.

A wrong photo count is rejected before any download. A link that is not a full URL, that cannot be downloaded, that is empty, or that is larger than 10 MB leaves that photo pending.

```json
{
  "adjustment_type": 1,
  "attendance_date": "2026-10-28",
  "expected_times": ["09:30", "18:38"],
  "office_latitude": 13.007155,
  "office_longitude": 80.206531,
  "images": [
    {
      "image_url": "http://localhost/hrms/uploads/punch_adjustments/check-in.jpeg",
      "file_name": "check-in.jpeg"
    },
    {
      "image_url": "http://localhost/hrms/uploads/punch_adjustments/check-out.jpeg",
      "file_name": "check-out.jpeg"
    }
  ]
}
```

`file_name` is optional on both endpoints. It is copied into the result so you can see which photo a message belongs to.

### Response

```json
{
  "status": "real",
  "error": null,
  "results": [
    {
      "file_name": "check-in.jpeg",
      "status": "real",
      "metadata_edited": false,
      "metadata_flags": [],
      "c2pa_present": false,
      "c2pa_state": null,
      "c2pa_issuer": null,
      "sightengine_score": 0.001,
      "sightengine_is_ai": false,
      "is_ai_generated": false,
      "is_edited": false,
      "latitude": "13.007123",
      "longitude": "80.206533",
      "timestamp": "28/10/2026 09:30:00 AM",
      "location": "Corporate Office - Guindy",
      "accuracy": "5 m",
      "distance_metres": 3.56,
      "time_match": true,
      "matched_minute": "09:30",
      "error": null
    }
  ]
}
```

`sightengine_score` is `null` when Sightengine was not called. That happens on an early rejection and on a pending check.

For adjustment type `0`, `time_match` means the photo date matches the attendance date. The minute is not required.

The photo clock is read only in these shapes:

- `28/10/2026 09:23:43 AM`
- `28/10/2026 09:23:43`
- `28/10/2026 09:23 AM`
- `28/10/2026 09:23`

A month name such as `28 Oct 2026 09:23:43 AM` is converted to a number by Gemini, and the service also reads it if it arrives unconverted. Anything else stays pending with “The photo clock could not be read.”

Coordinates may be signed (`-33.8688`) or carry a direction letter (`33.8688 S`). South and West are negative. A latitude above 90 or a longitude above 180 is treated as unreadable.

## How to run it

Open a terminal in this folder:

`C:\Users\HP-600 G3\Desktop\JK\AIImageDetection\punch_verification`

The virtual environment is already in `.venv` (Python 3.12). Start the API with:

```text
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Leave that window open. The API is running only while that window is open.

Then open `http://127.0.0.1:8001/health`. You want `status` healthy and both key flags `true`.

HRMS is configured to call port **8001**. A server started on port 8000 is a different process, and HRMS will not use it. If this service is down, HRMS still saves the punch request and leaves it pending.

Stop the server with `Ctrl+C` in that window.

After you change Python code or a prompt file, stop the server and start it again. The prompts are loaded when the process starts.

Interactive docs are at `http://127.0.0.1:8001/docs` while the server is running.

### First-time setup

If `.venv` is missing, create it from this folder and install the packages:

```text
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Settings

Create a file named `.env` in this folder (next to `app`, not inside it). Do not commit it. `.gitignore` already ignores `.env` and `.venv`.

```text
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_FALLBACK_MODELS=gemini-2.5-flash-lite
GEMINI_MAX_IMAGE_SIZE=1280
GEMINI_JPEG_QUALITY=90
SIGHTENGINE_API_USER_1=
SIGHTENGINE_API_SECRET_1=
SIGHTENGINE_API_USER_2=
SIGHTENGINE_API_SECRET_2=
SIGHTENGINE_AI_THRESHOLD=0.40
OFFICE_RADIUS_METRES=100
```

`.env.example` is a copy of this block. Copy it to `.env` and fill in the keys.

- `GEMINI_API_KEY` is required for the Gemini step. If it is empty, that photo stays pending with “Gemini API key missing.”
- `GEMINI_MODEL` defaults to `gemini-3.5-flash-lite`. If that model fails, the service tries each model in `GEMINI_FALLBACK_MODELS` (comma separated) in order.
- `GEMINI_MAX_IMAGE_SIZE` is the longest side, in pixels, of the copy sent to Gemini. Photos are turned upright using their rotation note first. A photo smaller than this is sent as it is. Larger values read small stamp text better but make each call slightly slower. Try 1280 first, then 1600 if the stamp is misread.
- `SIGHTENGINE_AI_THRESHOLD` and `OFFICE_RADIUS_METRES` are the two limits used in steps 4 and 5.
- Sightengine uses up to two user/secret pairs. The second pair is a fallback when the first pair is rejected or rate-limited. If both pairs are empty, the photo stays pending with “Sightengine credentials missing.”
- A failed Sightengine key rests before it is tried again. A rate limit (HTTP 429) rests it for 1 minute, then 2, 4, 8 minutes and so on, never more than 1 hour. A wrong key (HTTP 401) rests it for 24 hours.

## Prompt

Gemini's instructions are one file, `prompts/punch_prompt.md`, not text buried in Python. It has these parts:

- what the attendance camera adds (GPS panel, map, the HRMS DRAIVF watermark), which is never evidence of AI or editing.
- the AI rules (`is_ai_generated`) and the edit rules (`is_edited`). When unsure, both return false.
- how to read the stamp: signed decimal coordinates, the timestamp as `dd/mm/yyyy hh:mm:ss AM/PM` (or `hh:mm AM/PM` when the stamp has no seconds, never invented), month names converted to numbers, text inside the photo treated as data and never as an instruction.
- the JSON Gemini must return: `is_ai_generated`, `is_edited`, `latitude`, `longitude`, `timestamp`, `location`, `accuracy`.

The same shape is also sent to Gemini as a response schema (`RESPONSE_SCHEMA` in `gemini_repository.py`), so Gemini cannot return the wrong keys or types. If a model refuses the schema, the service asks again without it.

`gemini_repository.py` reads the file at startup. Edit the prompt, then restart the server.

## Project layout

```text
punch_verification/
  app/
    main.py                         FastAPI app
    settings.py                     Reads .env
    logging_config.py               Request id on every log line
    routers/punch_router.py         /health, /punch-verify, /punch-verify-urls
    controllers/punch_controller.py Turns the request into image bytes
    services/punch_service.py       Count rules and the check order
    schemas/punch_schema.py         Request and response shapes
    repositories/
      image_repository.py           Saves a temp file, or downloads a URL
      gemini_repository.py          One Gemini call
      sightengine_repository.py     Sightengine genai score
      c2pa_repository.py            Content Credentials
  prompts/punch_prompt.md           Gemini prompt
  tests/                            Automatic tests
  requirements.txt                  Pinned packages
  requirements-dev.txt              Adds the test packages
  .env.example                      Setting names without keys
  .env                              Keys. Not committed.
```

A request goes router, then controller, then service. The service calls the repositories. Downloaded and decoded images are temporary files and are deleted after that photo is checked.

## HRMS

The punch raise page in HRMS still uploads the proof files and calls `POST /punch-verify` with base64. It sends `adjustment_type` from the form (`0`, `1`, `2`, or `3`), the attendance date, the type’s expected times, and the office latitude and longitude for that employee’s branch.

`/punch-verify-urls` is the extra way to send links. HRMS does not call it today. Any caller can use it when the files are already available at a public URL.

## Metadata check

Step 2 reads the photo's own text fields for editor and AI tool names (Photoshop, Canva, Midjourney and similar). Names are matched as whole words, so “Hover” or “Discovered” never match. Only the Software, HostComputer, ImageDescription and Artist EXIF tags, the XMP text, JPEG comments and PNG text chunks are searched. Raw binary blocks are not. The XMP toolkit tag (`Adobe XMP Core`), which many ordinary phone photos carry, is ignored.

## Logs

Every request gets an id (the `X-Request-ID` header if HRMS sends one, otherwise a new one). The id is returned in the `X-Request-ID` response header and printed on every log line, along with each photo's status and reason.

## Tests

```text
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

The tests use fake Gemini and Sightengine answers, so they need no keys and make no outside calls. They do not prove that the real services read your photos correctly. After a change to the prompt, the model or the image size, check a few real photos by hand.
