import configparser
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


@pytest.fixture
def config(monkeypatch, tmp_path):
    """Points the app at a throwaway config, so tests never read the real user_config.cfg."""
    import libs.generic as generic

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read_dict({
        "frame": {"password_for_auth": "secret", "create_requires_auth": "True", "reload_interval": "60000"},
        "comfyui": {
            "prompt": "base", "topics": "cats,dogs", "models": "a.safetensors",
            "output_dir": str(output_dir), "comfyui_url": "http://comfy:8188",
        },
        "openwebui": {"base_url": "http://openwebui", "api_key": "k", "models": "web-model"},
        "openrouter": {"enabled": "True", "api_key": "k", "models": "vendor/router-model:free"},
        "ollama": {"enabled": "True", "api_key": "k", "models": "qwen3.5:9b"},
        "freellmapi": {"enabled": "False", "base_url": "http://router", "api_key": "k", "models": "free-model"},
        "remote": {"enabled": "False", "password": "remote-secret"},
    })
    path = tmp_path / "user_config.cfg"
    with open(path, "w") as f:
        cfg.write(f)

    monkeypatch.setattr(generic.ConfigSingleton, "_path", str(path))
    monkeypatch.setattr(generic, "LOG_FILE", str(tmp_path / "prompts_log.jsonl"))
    monkeypatch.setattr(generic, "favourites_file", str(tmp_path / "favourites.json"))
    monkeypatch.setattr("routes.settings_routes.CONFIG_PATH", str(path))
    generic.ConfigSingleton.reset()
    yield cfg
    generic.ConfigSingleton.reset()


@pytest.fixture
def save_config(config):
    """Writes config changes to disk the way the settings page does."""
    import libs.generic as generic

    def save():
        with open(generic.ConfigSingleton._path, "w") as f:
            config.write(f)
        generic.ConfigSingleton.reset()

    return save


@pytest.fixture
def submitted(monkeypatch):
    """Captures jobs handed to the background executor instead of running them."""
    import routes.create_routes as create_routes

    jobs = []

    def submit(fn, *args, **fields):
        jobs.append(args)
        return create_routes.jobs.run(lambda: None, **fields)

    monkeypatch.setattr(create_routes.jobs, "submit", submit)
    monkeypatch.setattr(create_routes, "get_queue_count", lambda: 0)
    return jobs


@pytest.fixture
def client(config, submitted):
    from ai_frame_image_server import create_app

    app = create_app()
    app.testing = True
    return app.test_client()


@pytest.fixture
def logged_in(client):
    with client.session_transaction() as session:
        session["authenticated"] = True
    return client
