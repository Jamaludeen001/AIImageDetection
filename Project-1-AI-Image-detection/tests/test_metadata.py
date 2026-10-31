import io

import pytest
from PIL import Image, PngImagePlugin

from app.services.punch_service import PunchService, _signature_in


def read(path):
    return PunchService._read_metadata(PunchService.__new__(PunchService), str(path))


def jpeg_with(tmp_path, **tags):
    exif = Image.Exif()
    ids = {"Software": 0x0131, "ImageDescription": 0x010E, "Artist": 0x013B, "HostComputer": 0x013C}
    for name, value in tags.items():
        exif[ids[name]] = value
    path = tmp_path / "a.jpg"
    Image.new("RGB", (10, 10)).save(path, exif=exif)
    return path


@pytest.mark.parametrize("software", [
    "Hover Camera 2.1", "Recovery Mode Camera", "Samsung Camera", "iPhone 13", "HDR+ 1.0.2",
])
def test_ordinary_software_is_not_flagged(tmp_path, software):
    assert read(jpeg_with(tmp_path, Software=software))["is_edited"] is False


def test_description_with_over_inside_words_is_not_flagged(tmp_path):
    assert read(jpeg_with(tmp_path, ImageDescription="Discovered near Cover St"))["is_edited"] is False


@pytest.mark.parametrize("software", ["Adobe Photoshop 25.1", "Snapseed 2.0", "Canva", "Midjourney v6"])
def test_real_editors_are_flagged(tmp_path, software):
    result = read(jpeg_with(tmp_path, Software=software))
    assert result["is_edited"] is True
    assert result["flags"] == ["EXIF tag hit [Software]"]  # reported once, not twice


def test_png_generator_chunk_is_flagged(tmp_path):
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", "a cat, Steps: 20")
    path = tmp_path / "a.png"
    Image.new("RGB", (10, 10)).save(path, pnginfo=info)
    assert read(path)["is_edited"] is True


def test_plain_png_is_clean(tmp_path):
    path = tmp_path / "a.png"
    Image.new("RGB", (10, 10)).save(path)
    assert read(path) == {"is_edited": False, "flags": []}


def test_unreadable_file(tmp_path):
    path = tmp_path / "a.img"
    path.write_bytes(b"not an image")
    assert read(path)["error"] == "The file is not a readable image."


def test_whole_word_matching():
    assert _signature_in("Made with Adobe Photoshop") == "adobe"
    assert _signature_in("paint.net 5") == "paint.net"
    assert _signature_in("Stable Diffusion XL") == "stable diffusion"
    assert _signature_in("Hover Discovered Recovery Influx") is None
    assert _signature_in("image stability") is None


def test_xmp_toolkit_tag_alone_is_not_an_editor():
    from app.services.punch_service import _xmp_strings
    plain = {"xmpmeta": {"xmptk": "Adobe XMP Core 5.1.0-jc003", "RDF": {"Description": {"Make": "Pixel"}}}}
    assert _signature_in(" ".join(_xmp_strings(plain))) is None
    edited = {"xmpmeta": {"xmptk": "Adobe XMP Core 5", "RDF": {"Description": {"CreatorTool": "Adobe Photoshop"}}}}
    assert _signature_in(" ".join(_xmp_strings(edited))) == "adobe"
