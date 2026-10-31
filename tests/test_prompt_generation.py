import pytest

import libs.generic as generic

SERVICES = {
    "openwebui": "libs.openwebui.create_prompt_on_openwebui",
    "openrouter": "libs.openrouter.create_prompt_on_openrouter",
    "ollama": "libs.ollama.create_prompt_on_ollama",
    "freellmapi": "libs.freellmapi.create_prompt_on_freellmapi",
}


@pytest.fixture
def calls(monkeypatch, config):
    """Replaces every provider; set calls.results[service] to a value or Exception."""

    class Calls(list):
        results = {}

    recorded = Calls()

    def fake(service):
        def provider(full_prompt, topic=None, model=None):
            recorded.append((service, full_prompt, topic))
            result = recorded.results.get(service, f"prompt from {service}")
            if isinstance(result, Exception):
                raise result
            return result

        return provider

    for service, path in SERVICES.items():
        monkeypatch.setattr(path, fake(service))
    return recorded


def test_groups_cover_enabled_services_only(config, save_config):
    config["ollama"]["enabled"] = "False"
    save_config()
    services = {service for _, service, _ in generic.load_prompt_model_groups()}
    assert services == {"openwebui", "openrouter"}


def test_service_table_matches_real_functions():
    import importlib

    for module, function in generic.PROMPT_SERVICES.values():
        assert callable(getattr(importlib.import_module(module), function))


def only(monkeypatch, *services):
    models = [(s, "model") for s in services]
    monkeypatch.setattr(generic, "load_prompt_models_from_config", lambda: models)


@pytest.mark.parametrize("service", SERVICES)
def test_every_service_is_reachable(monkeypatch, calls, service):
    only(monkeypatch, service)
    prompt, _ = generic.create_prompt_with_random_model("base", "cats")
    assert prompt == f"prompt from {service}"


def test_selected_topic_matches_the_request(monkeypatch, calls):
    only(monkeypatch, "ollama")
    _, topic = generic.create_prompt_with_random_model("base", "cats")
    _, full_prompt, provider_topic = calls[0]
    assert topic == "cats"
    assert "'cats'" in full_prompt
    assert provider_topic is None


def test_failed_service_falls_back(monkeypatch, calls):
    only(monkeypatch, "openrouter", "ollama")
    monkeypatch.setattr(generic.random, "choice", lambda seq: seq[0])
    calls.results = {"openrouter": RuntimeError("down")}
    prompt, _ = generic.create_prompt_with_random_model("base", "cats")
    assert prompt == "prompt from ollama"


def test_empty_result_falls_back(monkeypatch, calls):
    only(monkeypatch, "openrouter", "ollama")
    monkeypatch.setattr(generic.random, "choice", lambda seq: seq[0])
    calls.results = {"openrouter": ""}
    prompt, _ = generic.create_prompt_with_random_model("base", "cats")
    assert prompt == "prompt from ollama"


def test_openwebui_is_tried_twice(monkeypatch, calls):
    only(monkeypatch, "openwebui")
    calls.results = {"openwebui": None}
    generic.create_prompt_with_random_model("base", "cats")
    assert [c[0] for c in calls[:2]] == ["openwebui", "openwebui"]


def test_all_services_failing_uses_static_prompt(monkeypatch, calls):
    only(monkeypatch, "openrouter")
    calls.results = {"openrouter": RuntimeError("down")}
    assert generic.create_prompt_with_random_model("base", "cats") == ("A colorful abstract composition", "")


def test_only_duplicates_returns_none(monkeypatch, calls):
    only(monkeypatch, "ollama")
    monkeypatch.setattr(generic, "load_recent_prompts", lambda: ["prompt from ollama"])
    assert generic.create_prompt_with_random_model("base", "cats") == (None, "")
    assert len(calls) == 3


def test_no_models_configured(monkeypatch, calls):
    only(monkeypatch)
    assert generic.create_prompt_with_random_model("base", "cats") == (None, "")


@pytest.fixture
def fake_openwebui(monkeypatch, config):
    """Stands in for the OpenWebUI API; models in `failing` return HTTP 400."""
    import requests

    import libs.openwebui as openwebui

    class Fake:
        listed = [{"id": "live-model"}, {"id": "nomic-embed-v1.5"}, {"id": "arena-model"}]
        failing = set()
        asked = []
        bodies = []
        urls = []
        folders = [{"id": "folder-1", "name": "ai-frame-image-server"}]
        saved = []
        created_folders = []
        save_fails = False

    class Response:
        def __init__(self, payload, ok=True):
            self.payload, self.ok = payload, ok

        def raise_for_status(self):
            if not self.ok:
                raise requests.HTTPError("400 Client Error")

        def json(self):
            return self.payload

    def request(method, url, headers, timeout, json=None):
        if url.endswith("/api/models"):
            return Response({"data": Fake.listed})
        if url.endswith("/api/v1/folders/"):
            if method == "GET":
                return Response(Fake.folders)
            Fake.created_folders.append(json["name"])
            return Response({"id": "new-folder"})
        if url.endswith("/api/v1/chats/new"):
            Fake.saved.append(json)
            return Response({}, ok=not Fake.save_fails)
        Fake.urls.append(url)
        Fake.bodies.append(json)
        Fake.asked.append(json["model"])
        if json["model"] in Fake.failing:
            return Response({}, ok=False)
        return Response({"choices": [{"message": {"content": '"a fine prompt"'}}]})

    Fake.failing, Fake.asked, Fake.bodies, Fake.urls = set(), [], [], []
    Fake.saved, Fake.created_folders = [], []
    monkeypatch.setattr(openwebui.requests, "request", request)
    monkeypatch.setattr(openwebui, "_ALL_MODELS_CACHE", None)
    return Fake


def test_provider_does_not_add_instructions_twice(monkeypatch, fake_openwebui):
    monkeypatch.setattr(generic, "load_prompt_models_from_config", lambda: [("openwebui", "web-model")])

    generic.create_prompt_with_random_model("base", "cats")

    assert fake_openwebui.bodies[0]["messages"][0]["content"].count("Can you generate me") == 1


def test_openwebui_url_has_no_trailing_slash(fake_openwebui, config, save_config):
    import libs.openwebui as openwebui

    config["openwebui"]["base_url"] = "http://openwebui:3000/"
    save_config()
    openwebui.create_prompt_on_openwebui("base", None, "web-model")
    assert fake_openwebui.urls == ["http://openwebui:3000/api/chat/completions"]


def test_openwebui_request_sends_no_chat_id(fake_openwebui):
    import libs.openwebui as openwebui

    openwebui.create_prompt_on_openwebui("base", None, "web-model")
    assert fake_openwebui.bodies[0]["model"] == "web-model"
    assert "chat_id" not in fake_openwebui.bodies[0]


def test_openwebui_saves_the_exchange_as_a_chat(fake_openwebui):
    import libs.openwebui as openwebui

    openwebui.create_prompt_on_openwebui("base", None, "web-model")

    saved = fake_openwebui.saved[0]
    assert saved["folder_id"] == "folder-1"
    messages = saved["chat"]["history"]["messages"]
    reply = messages[saved["chat"]["history"]["currentId"]]
    assert reply["content"] == '"a fine prompt"'
    assert messages[reply["parentId"]]["role"] == "user"


def test_openwebui_creates_the_chat_folder_when_missing(fake_openwebui, monkeypatch):
    import libs.openwebui as openwebui

    monkeypatch.setattr(fake_openwebui, "folders", [])
    openwebui.create_prompt_on_openwebui("base", None, "web-model")
    assert fake_openwebui.created_folders == ["ai-frame-image-server"]
    assert fake_openwebui.saved[0]["folder_id"] == "new-folder"


def test_openwebui_keeps_the_prompt_when_saving_fails(fake_openwebui, monkeypatch):
    import libs.openwebui as openwebui

    monkeypatch.setattr(fake_openwebui, "save_fails", True)
    assert openwebui.create_prompt_on_openwebui("base", None, "web-model") == "a fine prompt"


def test_openwebui_saves_no_chat_for_a_failed_model(fake_openwebui):
    import libs.openwebui as openwebui

    fake_openwebui.failing = {"web-model"}
    assert openwebui.create_prompt_on_openwebui("base", None, "web-model") is None
    assert fake_openwebui.saved == []


def test_openwebui_lists_only_chat_models_when_flag_is_on(fake_openwebui, config, save_config):
    config["openwebui"]["list_all_models"] = "True"
    save_config()
    groups = {label: models for label, _, models in generic.load_prompt_model_groups()}
    assert groups["OpenWebUI (All)"] == ["live-model"]


def test_openwebui_flag_off_adds_no_group(fake_openwebui):
    labels = [label for label, _, _ in generic.load_prompt_model_groups()]
    assert "OpenWebUI (All)" not in labels


def test_openwebui_flag_works_with_no_models_listed(fake_openwebui, config, save_config):
    import libs.openwebui as openwebui

    config["openwebui"]["models"] = ""
    config["openwebui"]["list_all_models"] = "True"
    save_config()
    assert openwebui.create_prompt_on_openwebui("base", None) == "a fine prompt"
    assert fake_openwebui.asked == ["live-model"]


def test_openwebui_stale_model_falls_back_to_a_listed_one(fake_openwebui, config, save_config):
    import libs.openwebui as openwebui

    config["openwebui"]["list_all_models"] = "True"
    save_config()
    fake_openwebui.failing = {"web-model"}
    assert openwebui.create_prompt_on_openwebui("base", None, "web-model") == "a fine prompt"
    assert fake_openwebui.asked == ["web-model", "live-model"]


def test_openwebui_gives_up_when_every_model_fails(fake_openwebui, config, save_config):
    import libs.openwebui as openwebui

    config["openwebui"]["list_all_models"] = "True"
    save_config()
    fake_openwebui.failing = {"web-model", "live-model"}
    assert openwebui.create_prompt_on_openwebui("base", None, "web-model") is None


def test_secondary_topic_reaches_every_generated_prompt(config, save_config):
    config["comfyui"]["secondary_topic"] = "christmas"
    save_config()
    assert "'christmas'" in generic.build_user_content("cats", [])[0]
    assert "'christmas'" in generic.build_user_content("", [])[0]
    assert "'christmas'" in generic.build_request_content("base", "random")


def test_prompt_steps_name_the_selected_model(monkeypatch, calls):
    from libs import jobs

    only(monkeypatch, "ollama")
    job_id = jobs.run(lambda: generic.create_prompt_with_random_model("base", "cats"))
    steps = [s["text"] for s in jobs.get_job(job_id)["steps"]]
    assert "Prompt model selected: model (ollama)" in steps
    assert steps[-1] == "Prompt written"


def test_failed_prompt_service_is_reported_as_a_step(monkeypatch, calls):
    from libs import jobs

    only(monkeypatch, "ollama")
    calls.results = {"ollama": RuntimeError("boom")}
    job_id = jobs.run(lambda: generic.create_prompt_with_random_model("base", "cats"))
    assert "ollama failed: boom" in [s["text"] for s in jobs.get_job(job_id)["steps"]]


def test_build_request_content():
    assert generic.build_request_content("complete", None) == "complete"


def test_me_request_asks_for_one_scene_and_not_a_second_idea(config):
    content = generic.build_request_content(generic.ME_PROMPT, "pixelart")
    assert "random image idea" not in content
    assert "exactly one scene" in content
    assert "'pixelart'" in content


def test_me_request_is_used_when_generating_with_a_random_model(config, monkeypatch):
    sent = []
    monkeypatch.setattr(generic, "try_prompt_service", lambda service, model, prompt, attempts=1: sent.append(prompt) or "scene")
    generic._generate_prompt([("ollama", "m")], generic.ME_PROMPT, "pixelart", [])
    assert "random image idea" not in sent[0]


def test_normal_requests_still_ask_for_a_random_idea(config):
    assert "random image idea" in generic.build_request_content("base", "cats")
