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


@pytest.mark.parametrize("failure", [None, RuntimeError("render failed"), jobs.JobCancelled()])
def test_memory_is_freed_after_every_outcome(monkeypatch, config, failure):
    freed = []

    def fake_generate(*args, **kwargs):
        if failure:
            raise failure

    monkeypatch.setattr(comfyui, "generate_image", fake_generate)
    monkeypatch.setattr(comfyui, "free_comfy_memory", lambda: freed.append(True))
    monkeypatch.setattr(comfyui, "select_model", lambda model: ("SDXL", "a.safetensors"))
    jobs.run(comfyui.create_image, "a cat")
    assert freed == [True]


@pytest.fixture
def zimage_config(config, save_config):
    config["comfyui"]["zimage"] = "True"
    config["comfyui"]["only_flux"] = "True"
    config["comfyui:zimage"] = {"models": "z_image_turbo-Q8_0.gguf"}
    save_config()


def test_random_selection_can_pick_zimage(zimage_config):
    assert comfyui.select_model("Random Image Model") == ("ZImage", "z_image_turbo-Q8_0.gguf")


@pytest.mark.parametrize("model", ["z_image_turbo-Q8_0.gguf", "Z-Image-Turbo.gguf"])
def test_named_zimage_model_uses_the_zimage_workflow(config, model):
    assert comfyui.select_model(model) == ("ZImage", model)


def test_zimage_is_skipped_at_random_when_disabled(config):
    assert comfyui.select_model("Random Image Model")[0] == "SDXL"


def test_zimage_models_are_listed_only_when_enabled(config, save_config):
    from libs.generic import load_models_from_config

    config["comfyui:zimage"] = {"models": "z.gguf"}
    save_config()
    assert load_models_from_config()[3] == []
    config["comfyui"]["zimage"] = "True"
    save_config()
    assert load_models_from_config()[3] == ["z.gguf"]


def test_create_image_renders_zimage_with_every_node_the_app_sets(monkeypatch, zimage_config):
    queued = []
    monkeypatch.setattr(comfyui, "unload_local_models", lambda: None)
    monkeypatch.setattr(comfyui, "free_comfy_memory", lambda: None)
    monkeypatch.setattr(comfyui, "_queue_prompt", lambda wf: queued.append(wf) or "id")
    monkeypatch.setattr(comfyui, "_wait_for_render", lambda prompt_id: {"outputs": {"10": {"images": [{}]}}})
    monkeypatch.setattr(comfyui, "_fetch_image", lambda image: png_bytes("red"))
    monkeypatch.setattr(comfyui, "rename_image", lambda: None)

    job = jobs.get_job(jobs.run(comfyui.create_image, "a cat", "z_image_turbo-Q8_0.gguf"))

    assert job["status"] == "done", job
    nodes = {node["_meta"]["title"]: node["inputs"] for node in queued[0].values()}
    assert nodes["Positive"]["text"] == "a cat"
    assert nodes["Load Checkpoint"]["unet_name"] == "z_image_turbo-Q8_0.gguf"
    assert (nodes["CR Aspect Ratio"]["width"], nodes["CR Aspect Ratio"]["height"]) == ("720", "1080")


@pytest.fixture
def me_config(config, save_config, monkeypatch):
    config["comfyui:me"] = {"enabled": "True", "photos": "me.jpg, gone.jpg", "nightly_chance": "100"}
    save_config()
    info = {
        "LoadImage": {"input": {"required": {"image": [["me.jpg", "other.png"], {}]}}},
        "FaceSwapFromPhoto": {},
    }
    monkeypatch.setattr(comfyui.requests, "get", lambda url, timeout=None: Response(info))
    return config


def test_me_photos_are_only_those_comfyui_has(me_config):
    assert comfyui.get_available_me_photos() == ["me.jpg"]


def test_me_photos_are_empty_when_disabled(me_config, save_config):
    me_config["comfyui:me"]["enabled"] = "False"
    save_config()
    assert comfyui.get_available_me_photos() == []


def test_me_photos_are_empty_when_comfyui_is_down(me_config, monkeypatch):
    def down(url, timeout=None):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(comfyui.requests, "get", down)
    assert comfyui.get_available_me_photos() == []


def test_daily_image_is_me_only_when_the_chance_hits(me_config, save_config, monkeypatch):
    monkeypatch.setattr(comfyui.random, "random", lambda: 0.5)
    assert comfyui.picks_me_tonight() is True
    me_config["comfyui:me"]["nightly_chance"] = "25"
    save_config()
    assert comfyui.picks_me_tonight() is False


def test_daily_image_is_not_me_without_a_usable_photo(me_config, save_config):
    me_config["comfyui:me"]["photos"] = "gone.jpg"
    save_config()
    assert comfyui.picks_me_tonight() is False


def test_create_image_renders_me_with_the_photo_and_likeness(monkeypatch, me_config, save_config):
    me_config["freellmapi"]["image_backend"] = "True"
    save_config()
    queued = []
    monkeypatch.setattr(comfyui, "unload_local_models", lambda: None)
    monkeypatch.setattr(comfyui, "free_comfy_memory", lambda: None)
    monkeypatch.setattr(comfyui, "_queue_prompt", lambda wf: queued.append(wf) or "id")
    monkeypatch.setattr(comfyui, "_wait_for_render", lambda prompt_id: {"outputs": {"11": {"images": [{}]}}})
    monkeypatch.setattr(comfyui, "_fetch_image", lambda image: png_bytes("red"))
    monkeypatch.setattr(comfyui, "rename_image", lambda: None)

    job = jobs.get_job(jobs.run(comfyui.create_image, "Photo of him cooking.", comfyui.ME_MODEL))

    assert job["status"] == "done", job
    assert job["model"] == "Me (me.jpg)"
    nodes = {node["_meta"]["title"]: node["inputs"] for node in queued[0].values()}
    assert nodes["Positive"]["prompt"] == f"Photo of him cooking. {comfyui.ME_FRAMING} {comfyui.ME_LIKENESS}"
    assert (nodes["Render size"]["width"], nodes["Render size"]["height"]) == (1024, 1536)
    assert "Pixel grid" not in nodes
    assert nodes["Your photo"]["image"] == "me.jpg"
    assert nodes["Load Checkpoint"]["unet_name"] == comfyui.ME_CHECKPOINT
    assert (nodes["CR Aspect Ratio"]["width"], nodes["CR Aspect Ratio"]["height"]) == ("720", "1080")


def test_me_fails_clearly_without_a_photo(monkeypatch, me_config, save_config):
    me_config["comfyui:me"]["photos"] = "gone.jpg"
    save_config()
    monkeypatch.setattr(comfyui, "free_comfy_memory", lambda: None)

    job = jobs.get_job(jobs.run(comfyui.create_image, "a scene", comfyui.ME_MODEL))

    assert job["status"] == "failed"
    assert "Me photos" in job["error"]


def test_queue_details_show_a_me_prompt(monkeypatch):
    with open("workflow_me.json") as f:
        workflow = json.load(f)
    workflow["8"]["inputs"]["prompt"] = "a scene"
    monkeypatch.setattr(comfyui, "_get_queue", lambda: {"queue_running": [[0, "id", workflow]]})
    assert comfyui.get_queue_details()[0]["prompt"] == "a scene"


def test_daily_task_uses_me_prompt_and_any_topic_when_picked(monkeypatch, me_config):
    import ai_frame_image_server as server

    calls = []
    monkeypatch.setattr(server, "picks_me_tonight", lambda: True)
    monkeypatch.setattr(
        server, "create_prompt_with_random_model", lambda base, topic: calls.append((base, topic)) or ("scene", "cats")
    )
    monkeypatch.setattr(server, "create_image", lambda *args: calls.append(args))
    server.scheduled_task()
    assert calls == [(server.ME_PROMPT, "random"), ("scene", comfyui.ME_MODEL, "cats")]


def test_daily_task_is_unchanged_when_not_picked(monkeypatch, me_config):
    import ai_frame_image_server as server

    calls = []
    monkeypatch.setattr(server, "picks_me_tonight", lambda: False)
    monkeypatch.setattr(
        server, "create_prompt_with_random_model", lambda base, topic: calls.append((base, topic)) or ("scene", "")
    )
    monkeypatch.setattr(server, "create_image", lambda *args: calls.append(args))
    server.scheduled_task()
    assert calls == [("base", ""), ("scene", "Random Image Model", "")]


def test_daily_image_is_not_me_without_the_face_swap_node(me_config, monkeypatch):
    info = {"LoadImage": {"input": {"required": {"image": [["me.jpg"], {}]}}}}
    monkeypatch.setattr(comfyui.requests, "get", lambda url, timeout=None: Response(info))
    monkeypatch.setattr(comfyui.random, "random", lambda: 0.1)
    assert comfyui.picks_me_tonight() is False


@pytest.mark.parametrize("scene", ["Pixel art of him cooking", "16-bit pixel art of him cooking", "Pixelart of him cooking"])
def test_pixel_scene_is_drawn_then_pixelated(scene):
    prompt = comfyui._me_prompt(scene, True)
    assert prompt.startswith("Bold retro video game illustration of him cooking.")
    assert "pixel" not in prompt.lower()
    assert comfyui.ME_PIXEL_STYLE in prompt


@pytest.mark.parametrize("scene, topic", [("Pixel art of him cooking", ""), ("Photo of him cooking", "pixelart")])
def test_me_uses_the_pixel_workflow_for_pixel_scenes(monkeypatch, me_config, scene, topic):
    queued = []
    monkeypatch.setattr(comfyui, "unload_local_models", lambda: None)
    monkeypatch.setattr(comfyui, "free_comfy_memory", lambda: None)
    monkeypatch.setattr(comfyui, "_queue_prompt", lambda wf: queued.append(wf) or "id")
    monkeypatch.setattr(comfyui, "_wait_for_render", lambda prompt_id: {"outputs": {"11": {"images": [{}]}}})
    monkeypatch.setattr(comfyui, "_fetch_image", lambda image: png_bytes("red"))
    monkeypatch.setattr(comfyui, "rename_image", lambda: None)

    job = jobs.get_job(jobs.run(comfyui.create_image, scene, comfyui.ME_MODEL, topic))

    assert job["status"] == "done", job
    nodes = {node["_meta"]["title"]: node["inputs"] for node in queued[0].values() if "_meta" in node}
    assert (nodes["Pixel grid"]["width"], nodes["Pixel grid"]["height"]) == (240, 360)
    assert nodes["CR Aspect Ratio"]["upscale_method"] == "nearest-exact"


@pytest.mark.parametrize("path", ["workflow_me.json", "workflow_me_pixel.json"])
def test_me_workflows_swap_the_face_before_saving(path):
    with open(path) as f:
        workflow = json.load(f)
    swap = next(node_id for node_id, node in workflow.items() if node["class_type"] == "FaceSwapFromPhoto")
    node = next(node for node in workflow.values() if node["class_type"] == "SaveImage")
    while "image" in node["inputs"] or "images" in node["inputs"]:
        source = node["inputs"].get("images", node["inputs"].get("image"))[0]
        if source == swap:
            return
        node = workflow[source]
    pytest.fail("The face swap is not on the path to the saved image.")
