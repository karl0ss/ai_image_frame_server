import pytest

import libs.local_llm as local_llm
from libs import jobs


class Response:
    def __init__(self, payload=None, ok=True):
        self.payload, self.ok = payload, ok

    def raise_for_status(self):
        if not self.ok:
            raise local_llm.requests.HTTPError("500 Server Error")

    def json(self):
        return self.payload


@pytest.fixture
def servers(monkeypatch, config, save_config):
    """Fake llama-swap and Ollama, whose models really disappear once unloaded."""

    class Servers:
        swap = ["qwen3.8-flash-next-128k", "maple-20b-cpu-131k"]
        ollama = [{"name": "gpt-oss:20b", "size_vram": 9000}, {"name": "glm-5.3:cloud", "size_vram": 0}]
        stuck = False
        down = False
        unloaded = []

    def get(url, timeout):
        if Servers.down:
            raise local_llm.requests.ConnectionError("refused")
        if url.endswith("/running"):
            return Response({"running": [{"model": m} for m in Servers.swap]})
        return Response({"models": Servers.ollama})

    def post(url, timeout, json=None):
        name = json["model"] if json else url.rsplit("/", 1)[1]
        Servers.unloaded.append(name)
        if not Servers.stuck:
            Servers.swap = [m for m in Servers.swap if m != name]
            Servers.ollama = [m for m in Servers.ollama if m["name"] != name]
        return Response()

    Servers.unloaded = []
    monkeypatch.setattr(local_llm.requests, "get", get)
    monkeypatch.setattr(local_llm.requests, "post", post)
    monkeypatch.setattr(local_llm, "UNLOAD_POLL_INTERVAL", 0)
    monkeypatch.setattr(local_llm, "UNLOAD_TIMEOUT", 0.05)
    config["local_llm"] = {
        "llama_swap_url": "http://swap/", "ollama_url": "http://ollama", "keep_loaded": "maple-20b-cpu-131k",
    }
    save_config()
    return Servers


def steps(fn) -> list[str]:
    return [s["text"] for s in jobs.get_job(jobs.run(fn))["steps"]]


def test_unloads_gpu_models_and_keeps_the_rest(servers):
    local_llm.unload_local_models()
    assert servers.unloaded == ["qwen3.8-flash-next-128k", "gpt-oss:20b"]
    assert servers.swap == ["maple-20b-cpu-131k"]


def test_cloud_models_are_left_alone(servers):
    local_llm.unload_local_models()
    assert "glm-5.3:cloud" not in servers.unloaded


def test_steps_say_what_was_unloaded(servers):
    reported = steps(local_llm.unload_local_models)
    assert "Unloading qwen3.8-flash-next-128k from llama-swap" in reported
    assert "llama-swap unloaded" in reported


def test_reports_a_model_that_would_not_unload(servers):
    servers.stuck = True
    assert "llama-swap still has qwen3.8-flash-next-128k loaded" in steps(local_llm.unload_local_models)


def test_unreachable_server_does_not_stop_the_render(servers):
    servers.down = True
    reported = steps(local_llm.unload_local_models)
    assert any(s.startswith("Could not unload llama-swap models") for s in reported)


def test_does_nothing_when_no_urls_are_set(servers, config, save_config):
    del config["local_llm"]
    save_config()
    local_llm.unload_local_models()
    assert servers.unloaded == []


def test_render_unloads_before_queueing(monkeypatch, config):
    import libs.comfyui as comfyui

    order = []

    class Workflow:
        def __init__(self, path):
            pass

        def set_node_param(self, *args):
            pass

        def get_node_id(self, name):
            return "1"

    monkeypatch.setattr(comfyui, "ComfyWorkflowWrapper", Workflow)
    monkeypatch.setattr(comfyui, "unload_local_models", lambda: order.append("unload"))
    monkeypatch.setattr(comfyui, "_queue_prompt", lambda wf: order.append("queue") or "id")
    monkeypatch.setattr(comfyui, "_wait_for_render", lambda prompt_id: {})
    monkeypatch.setattr(comfyui, "_first_output_image", lambda entry, node: {})
    monkeypatch.setattr(comfyui, "_fetch_image", lambda image: b"png")
    monkeypatch.setattr(comfyui, "rename_image", lambda: None)
    monkeypatch.setattr(comfyui, "generate_thumbnail", lambda path: None)

    comfyui.generate_image("image", "a prompt", model="a.safetensors")

    assert order == ["unload", "queue"]
