import io
import json
import os

import pytest
import requests
from PIL import Image

import libs.comfyui as comfyui
from libs import jobs

PROMPT_ID = "prompt-1"
SAVE_NODE_ID = "60"


def png_bytes(colour):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), colour).save(buffer, "PNG")
    return buffer.getvalue()


def success_entry():
    return {
        "status": {"status_str": "success", "completed": True, "messages": []},
        "outputs": {SAVE_NODE_ID: {"images": [{"filename": "x.png", "subfolder": "", "type": "output"}]}},
    }


class Response:
    def __init__(self, data=None, content=b"", status_code=200, text=""):
        self.data, self.content, self.status_code, self.text = data, content, status_code, text

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeComfy:
    """Scripts ComfyUI: `polls` is consumed one entry per poll of the history/queue pair."""

    def __init__(self):
        self.queued = []
        self.freed = 0
        self.polls = []
        self.image = png_bytes("blue")
        self.timeouts = []

    def _next(self):
        return self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]

    def get(self, url, timeout=None, params=None):
        self.timeouts.append(timeout)
        if "/history/" in url:
            step = self.polls[0]
            if isinstance(step, Exception):
                self._next()
                raise step
            return Response({PROMPT_ID: step} if step not in ("running", "pending", "gone") else {})
        if url.endswith("/queue"):
            step = self._next()
            item = [0, PROMPT_ID]
            return Response({
                "queue_running": [item] if step == "running" else [],
                "queue_pending": [item] if step == "pending" else [],
            })
        if url.endswith("/view"):
            return Response(content=self.image)
        raise AssertionError(url)

    def post(self, url, json=None, timeout=None):
        self.timeouts.append(timeout)
        if url.endswith("/prompt"):
            self.queued.append(json)
            return Response({"prompt_id": PROMPT_ID})
        if url.endswith("/free"):
            self.freed += 1
            return Response()
        raise AssertionError(url)


@pytest.fixture
def comfy(monkeypatch, config, tmp_path):
    fake = FakeComfy()
    monkeypatch.setattr(comfyui.requests, "get", fake.get)
    monkeypatch.setattr(comfyui.requests, "post", fake.post)
    monkeypatch.setattr(comfyui, "POLL_INTERVAL", 0)
    monkeypatch.setattr(comfyui.generate_image.retry, "sleep", lambda seconds: None)
    monkeypatch.setattr(comfyui, "generate_thumbnail", lambda path: None)
    monkeypatch.setattr("libs.generic.generate_thumbnail", lambda path: None)

    workflow = {
        "3": {"class_type": "KSampler", "_meta": {"title": "KSampler"}, "inputs": {"seed": 1}},
        "6": {"class_type": "CLIPTextEncode", "_meta": {"title": "Positive"}, "inputs": {"text": ""}},
        "10": {"class_type": "EmptyLatentImage", "_meta": {"title": "Empty Latent Image"},
               "inputs": {"width": 1, "height": 1}},
        "20": {"class_type": "CheckpointLoaderSimple", "_meta": {"title": "Load Checkpoint"},
               "inputs": {"ckpt_name": ""}},
        SAVE_NODE_ID: {"class_type": "SaveImage", "_meta": {"title": "Save Image"},
                       "inputs": {"filename_prefix": ""}},
    }
    fake.workflow_path = str(tmp_path / "workflow_sdxl.json")
    with open(fake.workflow_path, "w") as f:
        json.dump(workflow, f)

    config["comfyui"]["width"] = "720"
    config["comfyui"]["height"] = "1080"
    return fake


def generate(comfy):
    comfyui.generate_image("image", "a cat", workflow_path=comfy.workflow_path, model="a.safetensors")


def image_path(config):
    return os.path.join(config["comfyui"]["output_dir"], "image.png")


def pixel(path):
    with Image.open(path) as image:
        return image.getpixel((0, 0))


def archived(config):
    return [f for f in os.listdir(config["comfyui"]["output_dir"]) if f.endswith(".png") and f != "image.png"]


def seed_current_image(config):
    with open(image_path(config), "wb") as f:
        f.write(png_bytes("red"))


def test_render_writes_the_image_and_frees_memory(comfy, config, save_config):
    save_config()
    comfy.polls = ["pending", "running", success_entry()]
    generate(comfy)
    assert pixel(image_path(config)) == (0, 0, 255)
    assert len(comfy.queued) == 1
    assert comfy.freed == 1


def test_previous_image_is_archived_only_after_the_render(comfy, config, save_config):
    save_config()
    seed_current_image(config)
    seen = []
    real_get = comfy.get

    def spying_get(url, **kwargs):
        if url.endswith("/view"):
            seen.append(pixel(image_path(config)))
        return real_get(url, **kwargs)

    comfyui.requests.get = spying_get
    comfy.polls = ["running", success_entry()]
    generate(comfy)
    assert seen == [(255, 0, 0)]
    assert len(archived(config)) == 1


def test_failed_render_leaves_the_current_image_alone(comfy, config, save_config):
    save_config()
    seed_current_image(config)
    comfy.polls = [{
        "status": {"status_str": "error", "messages": [["execution_error", {"exception_message": "CUDA OOM\n"}]]},
        "outputs": {},
    }]
    with pytest.raises(RuntimeError, match="CUDA OOM"):
        generate(comfy)
    assert pixel(image_path(config)) == (255, 0, 0)
    assert archived(config) == []
    assert not os.path.exists(image_path(config) + ".tmp")


def test_execution_errors_are_retried(comfy, config, save_config):
    save_config()
    comfy.polls = [{"status": {"status_str": "error", "messages": []}, "outputs": {}}]
    with pytest.raises(RuntimeError):
        generate(comfy)
    assert len(comfy.queued) == 3


def test_cancelled_render_is_not_retried(comfy, config, save_config):
    save_config()
    comfy.polls = [{"status": {"status_str": "error", "messages": [["execution_interrupted", {}]]}, "outputs": {}}]
    with pytest.raises(jobs.JobCancelled):
        generate(comfy)
    assert len(comfy.queued) == 1


def test_timeout_is_not_retried(comfy, config, save_config, monkeypatch):
    save_config()
    monkeypatch.setattr(comfyui, "RENDER_TIMEOUT", 0)
    comfy.polls = ["running"]
    with pytest.raises(comfyui.RenderTimeout):
        generate(comfy)
    assert len(comfy.queued) == 1


def test_job_lost_from_comfyui_fails_instead_of_waiting_forever(comfy, config, save_config):
    save_config()
    comfy.polls = ["gone"]
    with pytest.raises(RuntimeError, match="lost the job"):
        generate(comfy)
    assert len(comfy.queued) == 3


def test_brief_connection_errors_do_not_queue_a_duplicate(comfy, config, save_config):
    save_config()
    comfy.polls = [requests.ConnectionError("blip"), "running", success_entry()]
    generate(comfy)
    assert len(comfy.queued) == 1


def test_finished_without_an_image_is_an_error(comfy, config, save_config):
    save_config()
    comfy.polls = [{"status": {"status_str": "success", "messages": []}, "outputs": {}}]
    with pytest.raises(RuntimeError, match="without producing"):
        generate(comfy)


def test_every_comfyui_request_has_a_timeout(comfy, config, save_config):
    save_config()
    comfy.polls = ["running", success_entry()]
    generate(comfy)
    assert comfy.timeouts and all(comfy.timeouts)


def test_rendering_status_is_reported_to_the_job(comfy, config, save_config):
    save_config()
    comfy.polls = ["running", success_entry()]
    seen = []
    original = comfyui.jobs.update_current
    comfyui.jobs.update_current = lambda **fields: seen.append(fields) or original(**fields)
    try:
        generate(comfy)
    finally:
        comfyui.jobs.update_current = original
    assert {"status": "rendering"} in seen


def test_queue_details_recognises_every_workflow_loader(monkeypatch, config):
    queue = {"queue_running": [[0, "id", {"1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "qwen.gguf"}}}]]}
    monkeypatch.setattr(comfyui, "_get_queue", lambda: queue)
    assert comfyui.get_queue_details()[0]["model"] == "qwen"


def test_queue_count_is_zero_when_comfyui_is_down(monkeypatch, config):
    def down(*args, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(comfyui.requests, "get", down)
    assert comfyui.get_queue_count() == 0


def test_create_image_without_a_prompt_fails_the_job(monkeypatch, config):
    monkeypatch.setattr("libs.generic.create_prompt_with_random_model", lambda *a: (None, ""))
    job = jobs.get_job(jobs.run(comfyui.create_image))
    assert job["status"] == "failed"
    assert "No prompt" in job["error"]
