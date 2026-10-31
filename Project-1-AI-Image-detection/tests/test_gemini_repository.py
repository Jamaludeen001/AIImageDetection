import io

import pytest
from PIL import Image

from app.repositories import gemini_repository as gr
from app.settings import settings


def make(tmp_path, size, orientation=None):
    path = tmp_path / "p.jpg"
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    Image.new("RGB", size, (1, 2, 3)).save(path, exif=exif)
    return str(path)


def open_result(data):
    return Image.open(io.BytesIO(data))


def test_large_photo_is_shrunk_to_setting(tmp_path):
    out = open_result(gr.GeminiRepository._prepare_image(object(), make(tmp_path, (3000, 2000))))
    assert max(out.size) == settings.GEMINI_MAX_IMAGE_SIZE == 1280


def test_small_photo_is_never_enlarged(tmp_path):
    out = open_result(gr.GeminiRepository._prepare_image(object(), make(tmp_path, (300, 200))))
    assert out.size == (300, 200)


def test_sideways_photo_is_turned_upright(tmp_path):
    # Stored 400x200 with "rotate 90 degrees" note -> should arrive as 200x400 (portrait).
    out = open_result(gr.GeminiRepository._prepare_image(object(), make(tmp_path, (400, 200), orientation=6)))
    assert out.size == (200, 400)


def test_model_list_has_no_dead_model_and_no_repeats(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-2.5-flash-lite")
    monkeypatch.setattr(settings, "GEMINI_FALLBACK_MODELS", "gemini-2.5-flash-lite, other-model ,")
    assert gr.model_list() == ["gemini-2.5-flash-lite", "other-model"]
    assert "gemini-1.5-flash" not in gr.model_list()


def test_default_models():
    assert "gemini-1.5-flash" not in gr.model_list()


def test_prompt_has_no_placeholders():
    assert "PASTE YOUR" not in gr.PROMPT
    assert "[PASTE" not in gr.PROMPT


def test_response_schema_is_accepted_by_the_sdk():
    types = pytest.importorskip("google.genai.types")
    repo = gr.GeminiRepository.__new__(gr.GeminiRepository)
    config = repo._config(types, use_schema=True)
    schema = config.response_schema
    assert set(schema.properties) == set(gr.RESPONSE_SCHEMA["properties"])
    assert schema.properties["latitude"].nullable is True
    assert schema.properties["is_ai_generated"].type == types.Type.BOOLEAN
    assert set(schema.required) == set(gr.RESPONSE_SCHEMA["required"])
    assert repo._config(types, use_schema=False).response_schema is None


class _Client:
    """Stands in for the Gemini client; each call pops the next reply or error."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.configs = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.configs.append((model, config))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return type("R", (), {"text": reply})()


def repo_with(client, monkeypatch):
    repo = gr.GeminiRepository.__new__(gr.GeminiRepository)
    repo.client = client
    monkeypatch.setattr(gr.time, "sleep", lambda s: None)
    return repo


def test_schema_rejected_then_retried_without_schema(tmp_path, monkeypatch):
    client = _Client([Exception("400 INVALID_ARGUMENT: bad schema"), '{"is_ai_generated": false, "is_edited": false, "latitude": "13.0°"}'])
    out = repo_with(client, monkeypatch).extract(make(tmp_path, (50, 50)))
    assert out["latitude"] == "13.0"
    assert client.configs[0][1].response_schema is not None
    assert client.configs[1][1].response_schema is None


def test_falls_back_to_next_model(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODEL", "m1")
    monkeypatch.setattr(settings, "GEMINI_FALLBACK_MODELS", "m2")
    client = _Client([Exception("500 boom"), '{"is_ai_generated": false, "is_edited": false}'])
    out = repo_with(client, monkeypatch).extract(make(tmp_path, (50, 50)))
    assert out["is_ai_generated"] is False
    assert [m for m, _ in client.configs] == ["m1", "m2"]


def test_all_models_fail(tmp_path, monkeypatch):
    client = _Client([Exception("500 boom")] * 5)
    out = repo_with(client, monkeypatch).extract(make(tmp_path, (50, 50)))
    assert out == {"error": "Gemini could not read this image."}


def test_non_object_json_is_an_error(tmp_path, monkeypatch):
    client = _Client(["[1, 2]"] * 5)
    out = repo_with(client, monkeypatch).extract(make(tmp_path, (50, 50)))
    assert "error" in out
