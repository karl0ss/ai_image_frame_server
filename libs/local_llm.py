import logging
import time

import requests

from libs import jobs
from libs.generic import load_config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10
UNLOAD_TIMEOUT = 60
UNLOAD_POLL_INTERVAL = 1


def _llama_swap_running(url: str, keep: set[str]) -> list[str]:
    response = requests.get(f"{url}/running", timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return [m["model"] for m in response.json()["running"] if m["model"] not in keep]


def _llama_swap_unload(url: str, model: str) -> None:
    requests.post(f"{url}/api/models/unload/{model}", timeout=UNLOAD_TIMEOUT).raise_for_status()


def _ollama_running(url: str, keep: set[str]) -> list[str]:
    response = requests.get(f"{url}/api/ps", timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return [m["name"] for m in response.json()["models"] if m.get("size_vram") and m["name"] not in keep]


def _ollama_unload(url: str, model: str) -> None:
    response = requests.post(f"{url}/api/generate", json={"model": model, "keep_alive": 0}, timeout=UNLOAD_TIMEOUT)
    response.raise_for_status()


def _unload_all(label: str, url: str, keep: set[str], running, unload) -> None:
    models = running(url, keep)
    if not models:
        jobs.log_step(f"No {label} models to unload")
        return

    for model in models:
        jobs.log_step(f"Unloading {model} from {label}")
        unload(url, model)

    deadline = time.monotonic() + UNLOAD_TIMEOUT
    while models and time.monotonic() < deadline:
        time.sleep(UNLOAD_POLL_INTERVAL)
        models = running(url, keep)
    jobs.log_step(f"{label} still has {', '.join(models)} loaded" if models else f"{label} unloaded")


def unload_local_models() -> None:
    """Clears local LLMs off the GPU before a render.

    Best effort: a model left loaded slows the render, which beats not rendering.
    """
    config = load_config()
    keep = {m.strip() for m in config.get("local_llm", "keep_loaded", fallback="").split(",") if m.strip()}
    servers = (
        ("llama-swap", "llama_swap_url", _llama_swap_running, _llama_swap_unload),
        ("Ollama", "ollama_url", _ollama_running, _ollama_unload),
    )
    for label, key, running, unload in servers:
        url = config.get("local_llm", key, fallback="").strip().rstrip("/")
        if not url:
            continue
        try:
            _unload_all(label, url, keep, running, unload)
        except Exception as e:
            logger.warning("Could not unload %s models: %s", label, e)
            jobs.log_step(f"Could not unload {label} models: {e}")
