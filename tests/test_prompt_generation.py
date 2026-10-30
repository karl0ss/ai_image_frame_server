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


def test_provider_does_not_add_instructions_twice(monkeypatch, config):
    import libs.openwebui as openwebui

    questions = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def chat(self, question, **kwargs):
            questions.append(question)
            return {"response": '"a fine prompt"'}

    monkeypatch.setattr(openwebui, "OpenWebUIClient", FakeClient)
    monkeypatch.setattr(generic, "load_prompt_models_from_config", lambda: [("openwebui", "web-model")])

    generic.create_prompt_with_random_model("base", "cats")

    assert questions[0].count("Can you generate me") == 1


def test_openwebui_url_has_no_trailing_slash(monkeypatch, config, save_config):
    import libs.openwebui as openwebui

    seen = {}

    class FakeClient:
        def __init__(self, base_url, **kwargs):
            seen["url"] = base_url

        def chat(self, **kwargs):
            return {"response": '"a fine prompt"'}

    config["openwebui"]["base_url"] = "http://openwebui:3000/"
    save_config()
    monkeypatch.setattr(openwebui, "OpenWebUIClient", FakeClient)
    openwebui.create_prompt_on_openwebui("base", None, "web-model")
    assert seen["url"] == "http://openwebui:3000"


def test_build_request_content():
    assert generic.build_request_content("complete", None) == "complete"
