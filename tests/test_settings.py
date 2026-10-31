import re

import pytest

import libs.generic as generic
import libs.settings as settings

COMMENTED = """[frame]
# keep this comment
reload_interval = 30000
port = 5000

# about the model list
[comfyui]
models = a,b
"""


def page_version(client):
    return re.search(r'name="config_version" value="(\w+)"', client.get("/settings").text).group(1)


def save(client, **fields):
    data = {key.replace("__", ":"): value for key, value in fields.items()}
    data["config_version"] = page_version(client)
    return client.post("/settings", data=data, follow_redirects=True)


def file_text():
    return settings.read_config_text()


def test_only_changed_lines_are_rewritten():
    result = settings.update_config_text(COMMENTED, {("frame", "port"): "8000"})
    assert result == COMMENTED.replace("port = 5000", "port = 8000")


def test_new_key_joins_the_end_of_its_section():
    result = settings.update_config_text(COMMENTED, {("frame", "auto_regen"): "True"})
    assert "port = 5000\nauto_regen = True\n\n# about the model list" in result


def test_new_key_in_each_of_two_sections():
    result = settings.update_config_text(COMMENTED, {("frame", "a"): "1", ("comfyui", "b"): "2"})
    config = settings.parse_config(result)
    assert config["frame"]["a"] == "1"
    assert config["comfyui"]["b"] == "2"
    assert config["comfyui"]["models"] == "a,b"


def test_new_section_is_appended():
    result = settings.update_config_text(COMMENTED, {("freellmapi", "enabled"): "True"})
    assert result.startswith(COMMENTED)
    assert result.endswith("[freellmapi]\nenabled = True\n")


def test_empty_value_stays_readable():
    result = settings.update_config_text(COMMENTED, {("frame", "port"): ""})
    assert settings.parse_config(result)["frame"]["port"] == ""


def test_multiline_value_is_replaced_whole():
    text = "[comfyui]\nmodels = a,\n    b,\n    c\nwidth = 1\n"
    result = settings.update_config_text(text, {("comfyui", "models"): "x"})
    assert result == "[comfyui]\nmodels = x\nwidth = 1\n"


def test_keys_are_matched_case_insensitively_and_keep_their_case():
    result = settings.update_config_text("[frame]\nPort: 5000\n", {("frame", "port"): "1"})
    assert result == "[frame]\nPort = 1\n"


def test_keys_are_matched_within_their_own_section():
    text = "[a]\nmodels = 1\n[b]\nmodels = 2\n"
    assert settings.update_config_text(text, {("b", "models"): "9"}) == "[a]\nmodels = 1\n[b]\nmodels = 9\n"


def test_saving_keeps_comments_through_the_page(logged_in):
    with open(generic.ConfigSingleton._path, "a") as f:
        f.write("# a comment of mine\n")
    save(logged_in, frame__reload_interval="1000")
    assert "# a comment of mine" in file_text()
    assert generic.load_config()["frame"]["reload_interval"] == "1000"


def test_save_confirms_and_reports_the_count(logged_in):
    assert "Saved 1 setting(s)." in save(logged_in, frame__reload_interval="1000").text


def test_no_changes_leaves_the_file_alone(logged_in):
    before = file_text()
    assert "No changes to save." in save(logged_in, frame__reload_interval="60000").text
    assert file_text() == before


def test_restart_settings_are_called_out(logged_in):
    page = save(logged_in, frame__port="6000").text
    assert "Restart the server to apply: Server port." in page


def test_live_settings_need_no_restart(logged_in):
    assert "Restart the server" not in save(logged_in, frame__reload_interval="1000").text


def test_settings_page_needs_login(client):
    assert "/login" in client.get("/settings").location
    assert "/login" in client.post("/settings", data={}).location


@pytest.mark.parametrize("field, value, message", [
    ("frame__regen_time", "3pm", "HH:MM"),
    ("frame__reload_interval", "soon", "whole number"),
    ("frame__reload_interval", "1", "at least 1000"),
    ("frame__port", "70000", "at most 65535"),
    ("comfyui__comfyui_url", "comfyui:8188", "http://"),
    ("comfyui__comfyui_url", "", "required"),
    ("frame__port", "", "required"),
    ("comfyui__width", "", "required"),
    ("comfyui__prompt", "one\nmore_key = injected", "single line"),
])
def test_invalid_values_are_rejected_and_nothing_is_saved(logged_in, field, value, message):
    before = file_text()
    response = save(logged_in, **{"comfyui__secondary_topic": "changed", field: value})
    assert response.status_code == 400
    assert message in response.text
    assert "Nothing was saved." in response.text
    assert file_text() == before


def test_rejected_save_keeps_what_was_typed(logged_in):
    page = save(logged_in, frame__regen_time="3pm", comfyui__secondary_topic="kept text").text
    assert 'value="kept text"' in page
    assert 'value="3pm"' in page


def test_settings_missing_from_the_file_can_be_set(logged_in):
    page = logged_in.get("/settings").text
    assert "Use for images instead of ComfyUI" in page
    save(logged_in, freellmapi__models="auto", remote__host="box")
    saved = generic.load_config()
    assert saved["freellmapi"]["models"] == "auto"
    assert saved["remote"]["host"] == "box"


def test_defaults_are_not_written_for_untouched_settings(config, save_config, logged_in):
    del config["remote"]
    save_config()
    save(logged_in, remote__port="22", remote__service="comfyui", remote__enabled="False")
    assert "[remote]" not in file_text()


def test_lists_accept_lines_commas_and_blanks(logged_in):
    save(logged_in, comfyui__topics="cats\n\n  dogs , birds\n")
    assert generic.load_config()["comfyui"]["topics"] == "cats,dogs,birds"


def test_list_spacing_alone_is_not_a_change(config, save_config, logged_in):
    config["comfyui:qwen"] = {"models": "a, b"}
    save_config()
    assert "No changes" in save(logged_in, comfyui__qwen__models="a\nb").text
    assert "models = a, b" in file_text()


def test_model_goes_where_it_was_entered(logged_in):
    save(logged_in, comfyui__qwen__models="qwen-new.gguf", comfyui__models="flux-looking-sdxl.safetensors")
    saved = generic.load_config()
    assert saved["comfyui:qwen"]["models"] == "qwen-new.gguf"
    assert saved["comfyui"]["models"] == "flux-looking-sdxl.safetensors"


def test_checkbox_last_value_wins(logged_in):
    data = {"config_version": page_version(logged_in), "frame:auto_regen": ["False", "True"]}
    logged_in.post("/settings", data=data)
    assert generic.load_config()["frame"]["auto_regen"] == "True"


def test_unticked_checkbox_turns_a_setting_off(logged_in):
    data = {"config_version": page_version(logged_in), "frame:create_requires_auth": ["False"]}
    logged_in.post("/settings", data=data)
    assert generic.load_config()["frame"]["create_requires_auth"] == "False"


def test_secrets_are_never_shown(logged_in, config):
    page = logged_in.get("/settings").text
    assert "remote-secret" not in page
    assert config["openrouter"]["api_key"] not in re.findall(r'value="([^"]*)"', page)
    assert "Set. Leave blank to keep it." in page


def test_blank_secret_keeps_the_stored_value(logged_in):
    save(logged_in, remote__password="", openrouter__api_key="")
    saved = generic.load_config()
    assert saved["remote"]["password"] == "remote-secret"
    assert saved["openrouter"]["api_key"] == "k"


def test_secret_can_be_replaced(logged_in):
    save(logged_in, openrouter__api_key="new-key")
    assert generic.load_config()["openrouter"]["api_key"] == "new-key"


def test_rejected_save_does_not_echo_a_typed_secret(logged_in):
    page = save(logged_in, openrouter__api_key="typed-secret", frame__regen_time="3pm").text
    assert "typed-secret" not in page


def test_password_is_hashed_and_works(logged_in):
    save(logged_in, frame__password_for_auth="new-pass", frame__password_for_auth_confirm="new-pass")
    stored = generic.load_config()["frame"]["password_for_auth"]
    assert stored.startswith("scrypt:")
    assert generic.verify_password("new-pass", stored)


def test_mismatched_password_is_rejected(logged_in):
    response = save(logged_in, frame__password_for_auth="one", frame__password_for_auth_confirm="two")
    assert "The passwords don&#39;t match." in response.text
    assert generic.load_config()["frame"]["password_for_auth"] == "secret"


def test_blank_password_is_ignored(logged_in):
    assert "No changes" in save(logged_in, frame__password_for_auth="").text


def test_stale_page_cannot_overwrite_newer_changes(logged_in):
    version = page_version(logged_in)
    with open(generic.ConfigSingleton._path, "a") as f:
        f.write("# edited elsewhere\n")
    before = file_text()
    response = logged_in.post("/settings", data={"config_version": version, "frame:reload_interval": "1000"})
    assert response.status_code == 409
    assert file_text() == before


def test_percent_in_a_value_is_fine(logged_in):
    save(logged_in, comfyui__secondary_topic="100% cats")
    assert generic.load_config()["comfyui"]["secondary_topic"] == "100% cats"


def test_unknown_settings_stay_editable(logged_in, config, save_config):
    config["frame"]["my_note"] = "hello"
    save_config()
    assert 'name="frame:my_note"' in logged_in.get("/settings").text
    save(logged_in, frame__my_note="changed")
    assert generic.load_config()["frame"]["my_note"] == "changed"


def test_value_that_would_not_read_back_is_refused(logged_in):
    field = settings.GROUPS[0].fields[0]
    with pytest.raises(ValueError):
        settings.save_changes(file_text(), {field: " padded "})


def test_every_setting_the_sample_defines_is_on_the_page():
    with open("user_config.cfg.sample") as f:
        sample = settings.parse_config(f.read())
    known = {field.name for group in settings.GROUPS for field in group.fields}
    missing = {f"{s}:{k}" for s in sample.sections() for k in sample[s]} - known
    assert missing == set()


def test_field_defaults_are_ones_the_code_also_falls_back_to():
    """A default is shown but only saved when changed, so the code must behave the same without it."""
    defaulted = {field.name for group in settings.GROUPS for field in group.fields if field.default}
    assert defaulted == {
        "frame:reload_interval", "frame:regen_time", "frame:port", "comfyui:output_dir", "comfyui:me:nightly_chance",
        "remote:port", "remote:service", "remote:startup_poll_timeout",
    }


def test_scheduler_starts_without_a_saved_time(config, monkeypatch):
    import ai_frame_image_server as server

    added = {}

    class Scheduler:
        def add_job(self, fn, trigger, **kwargs):
            added.update(kwargs)

        def start(self):
            pass

    monkeypatch.setattr(server, "BackgroundScheduler", Scheduler)
    config["frame"]["auto_regen"] = "True"
    server.start_scheduler(config)
    assert (added["hour"], added["minute"]) == ("03", "00")

