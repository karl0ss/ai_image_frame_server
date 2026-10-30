import base64
import io
import json
import os

import pytest
from PIL import Image

import libs.comfyui as comfyui
import libs.generic as generic


def png_bytes(colour):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), colour).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def router(monkeypatch):
    """Fakes the freellmapi image endpoint."""
    import libs.freellmapi as freellmapi

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(png_bytes("blue")).decode()}]}

    monkeypatch.setattr(freellmapi.requests, "post", lambda *a, **k: Response())
    monkeypatch.setattr("libs.create_thumbnail.generate_thumbnail", lambda path: None)
    monkeypatch.setattr(generic, "generate_thumbnail", lambda path: None)


def test_freellmapi_archives_the_previous_image(config, router):
    from libs.freellmapi import generate_image_on_freellmapi

    output_dir = config["comfyui"]["output_dir"]
    image = os.path.join(output_dir, "image.png")
    with open(image, "wb") as f:
        f.write(png_bytes("red"))

    generate_image_on_freellmapi("a cat")

    archived = [f for f in os.listdir(output_dir) if f.endswith(".png") and f != "image.png"]
    assert len(archived) == 1
    with Image.open(os.path.join(output_dir, archived[0])) as old:
        assert old.getpixel((0, 0)) == (255, 0, 0)
    with Image.open(image) as new:
        assert new.getpixel((0, 0)) == (0, 0, 255)


def test_freellmapi_backend_does_not_start_comfyui(config, save_config, router, monkeypatch):
    config["freellmapi"]["image_backend"] = "True"
    save_config()

    def fail():
        raise AssertionError("RemoteService should not be used")

    monkeypatch.setattr(comfyui, "RemoteService", fail)
    comfyui.create_image("a cat", topic="cats")


def test_selected_image_is_stored_on_the_output_volume(config):
    generic.set_selected_image("a.png")
    path = os.path.join(config["comfyui"]["output_dir"], "selected_image.json")
    with open(path) as f:
        assert json.load(f) == {"filename": "a.png"}
    assert generic.get_selected_image() == "a.png"

    generic.set_selected_image(None)
    assert not os.path.exists(path)
    assert generic.get_selected_image() is None
