import re
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, render_template, redirect, url_for, session, request, flash
from libs.comfyui import create_image, select_model, get_available_models, get_queue_count
from libs.generic import (
    load_models_from_config, load_topics_from_config, load_openrouter_models_from_config,
    load_openwebui_models_from_config, load_ollama_models_from_config,
    create_prompt_with_random_model, get_bool, load_config
)

bp = Blueprint("create_routes", __name__)
user_config = None
_executor = ThreadPoolExecutor(max_workers=2)

_SAFE_FILENAME_RE = re.compile(r'^[\w\-. ]+$', re.UNICODE)
_MAX_PROMPT_LENGTH = 2000


def _validate_prompt(prompt: str) -> str | None:
    if not prompt:
        return None
    prompt = prompt.strip()
    if len(prompt) > _MAX_PROMPT_LENGTH:
        prompt = prompt[:_MAX_PROMPT_LENGTH]
    return prompt


def _validate_model(model: str) -> str:
    if not model or not _SAFE_FILENAME_RE.match(model):
        return "Random Image Model"
    return model


def _validate_topic(topic: str) -> str:
    if not topic:
        return ""
    topic = topic.strip()
    if len(topic) > 200:
        topic = topic[:200]
    return topic


def _load_models_and_topics():
    sdxl_models, flux_models, qwen_models = load_models_from_config()
    openwebui_models = load_openwebui_models_from_config()
    openrouter_models, openrouter_free_models = load_openrouter_models_from_config()
    ollama_models, ollama_cloud_models = load_ollama_models_from_config()
    queue_count = get_queue_count()
    topics = load_topics_from_config()
    return {
        "sdxl_models": sdxl_models,
        "flux_models": flux_models,
        "qwen_models": qwen_models,
        "openwebui_models": openwebui_models,
        "openrouter_models": openrouter_models,
        "openrouter_free_models": openrouter_free_models,
        "ollama_models": ollama_models,
        "ollama_cloud_models": ollama_cloud_models,
        "topics": topics,
        "queue_count": queue_count
    }


@bp.route("/create", methods=["GET", "POST"])
def create():
    config = load_config()
    if request.method == "POST":
        prompt = _validate_prompt(request.form.get("prompt", ""))
        image_model = _validate_model(request.form.get("model") or "Random Image Model")
        topic = _validate_topic(request.form.get("topic", ""))
        selected_workflow, model = select_model(image_model)

        selected_topic = ""
        if not prompt:
            prompt_model = request.form.get("prompt_model") or ""
            if prompt_model and prompt_model != "Random Prompt Model":
                if ":" in prompt_model:
                    service, service_model = prompt_model.split(":", 1)
                    if not _SAFE_FILENAME_RE.match(service_model):
                        flash("Invalid prompt model specified.", "error")
                        return redirect(url_for("create_routes.create_image_page"))
                else:
                    service, service_model = prompt_model, ""
                if service == "openwebui":
                    from libs.openwebui import create_prompt_on_openwebui
                    prompt = create_prompt_on_openwebui(config["comfyui"]["prompt"], topic, service_model)
                elif service == "openrouter":
                    from libs.openrouter import create_prompt_on_openrouter
                    prompt = create_prompt_on_openrouter(config["comfyui"]["prompt"], topic, service_model)
                elif service == "ollama":
                    from libs.ollama import create_prompt_on_ollama
                    prompt = create_prompt_on_ollama(config["comfyui"]["prompt"], topic, service_model)
                selected_topic = topic if topic and topic != "random" else ""
            else:
                prompt, selected_topic = create_prompt_with_random_model(config["comfyui"]["prompt"], topic)
        else:
            selected_topic = topic if topic and topic != "random" else ""

        _executor.submit(create_image, prompt, model, selected_topic)
        return redirect(url_for("create_routes.image_queued", prompt=prompt, model=model.split(".")[0]))

    models_and_topics = _load_models_and_topics()
    return render_template("create_image.html", **models_and_topics)


@bp.route("/image_queued")
def image_queued():
    prompt = request.args.get("prompt", "No prompt provided.")[:_MAX_PROMPT_LENGTH]
    model = request.args.get("model", "No model selected.")
    if model == "Random Image Model":
        model = "Random"
    else:
        model = model.split(".")[0]
    return render_template("image_queued.html", prompt=prompt, model=model)


@bp.route("/create_image", methods=["GET"])
def create_image_page():
    config = load_config()
    if get_bool(config, "frame", "create_requires_auth", False) and not session.get("authenticated"):
        return redirect(url_for("auth_routes.login", next=request.path))

    models_and_topics = _load_models_and_topics()
    return render_template("create_image.html", **models_and_topics)


def init_app(config):
    global user_config
    user_config = config