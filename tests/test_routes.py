import os

import pytest

import libs.generic as generic


@pytest.mark.parametrize("path", ["/create", "/create_image"])
def test_create_pages_need_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert "/login" in response.location


def test_create_post_needs_login(client, submitted):
    response = client.post("/create", data={"prompt": "a cat"})
    assert "/login" in response.location
    assert submitted == []


def test_create_is_open_when_auth_is_off(client, config, save_config, submitted):
    config["frame"]["create_requires_auth"] = "False"
    save_config()
    assert client.get("/create_image").status_code == 200
    client.post("/create", data={"prompt": "a cat"})
    assert len(submitted) == 1


def test_cancel_rejects_get(client):
    assert client.get("/cancel").status_code == 405


def test_cancel_needs_login(client):
    assert "/login" in client.post("/cancel").location


def test_cancel_when_logged_in(logged_in, monkeypatch):
    monkeypatch.setattr("routes.job_routes.cancel_current_job", lambda: "Cancelled")
    assert logged_in.post("/cancel").data == b"Cancelled"


def test_login_without_next_goes_to_create_page(client):
    assert 'value="None"' not in client.get("/login").text
    response = client.post("/login", data={"password": "secret", "next": ""})
    assert response.location.endswith("/create_image")


def test_login_honours_next(client):
    response = client.post("/login", data={"password": "secret", "next": "/settings"})
    assert response.location.endswith("/settings")


def test_login_rejects_offsite_next(client):
    response = client.post("/login", data={"password": "secret", "next": "https://evil.example/"})
    assert response.location.endswith("/create_image")


def test_wrong_password_shows_a_message(client):
    response = client.post("/login", data={"password": "nope"}, follow_redirects=True)
    assert "Incorrect password." in response.text


def test_password_change_applies_without_restart(client, config, save_config):
    config["frame"]["password_for_auth"] = "changed"
    save_config()
    assert client.post("/login", data={"password": "secret"}).location.endswith("/login")
    assert client.post("/login", data={"password": "changed"}).location.endswith("/create_image")


@pytest.mark.parametrize("prompt_model", ["ollama:qwen3.5:9b", "openrouter:vendor/router-model:free"])
def test_prompt_models_with_punctuation_are_accepted(logged_in, monkeypatch, submitted, prompt_model):
    response = logged_in.post("/create", data={"prompt_model": prompt_model})
    assert "/image_queued?job=" in response.location
    assert submitted[0][1] == prompt_model


def test_unknown_prompt_model_is_rejected(logged_in, submitted):
    response = logged_in.post("/create", data={"prompt_model": "ollama:made-up"}, follow_redirects=True)
    assert "Invalid prompt model specified." in response.text
    assert submitted == []


def test_settings_masks_remote_password(logged_in):
    page = logged_in.get("/settings").text
    assert "remote-secret" not in page


def test_worker_uses_the_chosen_prompt_model(config, monkeypatch):
    import routes.create_routes as create_routes

    calls = []
    monkeypatch.setattr(
        create_routes, "try_prompt_service",
        lambda service, model, prompt, topic: calls.append((service, model)) or "generated",
    )
    monkeypatch.setattr(create_routes, "create_image", lambda prompt, model, topic: calls.append(prompt))
    create_routes._generate(None, "ollama:qwen3.5:9b", "Random Image Model", "")
    assert calls == [("ollama", "qwen3.5:9b"), "generated"]


def test_create_returns_immediately_with_a_job_page(logged_in):
    response = logged_in.post("/create", data={"prompt": "a cat"}, follow_redirects=True)
    assert response.status_code == 200
    assert "/api/jobs/" in response.text


def test_job_api(logged_in):
    location = logged_in.post("/create", data={"prompt": "a cat"}).location
    job_id = location.split("job=")[1]
    job = logged_in.get(f"/api/jobs/{job_id}").get_json()
    assert job["prompt"] == "a cat"


def test_unknown_job_api_and_page(client):
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.get("/image_queued?job=missing").status_code == 404


def set_image(config, name, mtime):
    path = os.path.join(config["comfyui"]["output_dir"], name)
    with open(path, "wb") as f:
        f.write(b"image-" + name.encode())
    os.utime(path, (mtime, mtime))


def test_frame_image_url_changes_with_the_image(client, config):
    set_image(config, "image.png", 1000)
    assert 'src="/images/image.png?v=1000"' in client.get("/").text
    set_image(config, "image.png", 2000)
    assert client.get("/api/frame").get_json()["url"] == "/images/image.png?v=2000"


def test_frame_page_is_revalidated(client, config):
    set_image(config, "image.png", 1000)
    assert client.get("/").headers["Cache-Control"] == "no-cache"
    assert client.get("/api/frame").headers["Cache-Control"] == "no-store"


def test_frame_state_without_an_image(client):
    state = client.get("/api/frame").get_json()
    assert state["version"] == 0
    assert state["prompt"] == "No prompt available"


def test_image_png_serves_the_selected_image(client, config):
    set_image(config, "image.png", 1000)
    set_image(config, "chosen.png", 1000)
    assert client.get("/images/image.png").data == b"image-image.png"
    generic.set_selected_image("chosen.png")
    assert client.get("/images/image.png").data == b"image-chosen.png"
    assert client.get("/api/frame").get_json()["selected"] == "chosen.png"
    generic.set_selected_image(None)
    assert client.get("/images/image.png").data == b"image-image.png"


def test_config_values_may_contain_percent(logged_in, config, save_config):
    config["frame"]["note"] = "100% done"
    save_config()
    assert logged_in.get("/settings").status_code == 200


def test_new_qwen_model_goes_to_the_qwen_section(logged_in):
    logged_in.post("/settings", data={"new_model": "qwen-new.gguf"})
    saved = generic.load_config()
    assert "qwen-new.gguf" in saved["comfyui:qwen"]["models"]
    assert "qwen-new.gguf" not in saved["comfyui"]["models"]


def test_settings_keep_masked_secrets(logged_in):
    logged_in.post("/settings", data={"remote:password": "********", "frame:reload_interval": "1000"})
    saved = generic.load_config()
    assert saved["remote"]["password"] == "remote-secret"
    assert saved["frame"]["reload_interval"] == "1000"


def test_gallery_handles_awkward_filenames(client, config):
    set_image(config, 'quo"te.png', 1000)
    assert "quo\\u0022te.png" in client.get("/images").text or 'quo\\"te.png' in client.get("/images").text
