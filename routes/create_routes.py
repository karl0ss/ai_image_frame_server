import re
from flask import Blueprint, render_template, redirect, url_for, request, flash
from libs import jobs
from libs.comfyui import create_image, get_queue_count, ME_MODEL
from libs.generic import (
    load_models_from_config, load_topics_from_config, load_prompt_model_groups,
    load_prompt_models_from_config, load_me_photos, create_prompt_with_random_model, try_prompt_service,
    load_config, ME_PROMPT
)
from routes.auth_routes import requires_create_auth

bp = Blueprint("create_routes", __name__)

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
    sdxl_models, flux_models, qwen_models, zimage_models, krea_models, flux3_models, qwen21_models, klein_models = (
        load_models_from_config()
    )
    queue_count = get_queue_count()
    topics = load_topics_from_config()
    return {
        "sdxl_models": sdxl_models,
        "flux_models": flux_models,
        "qwen_models": qwen_models,
        "zimage_models": zimage_models,
        "krea_models": krea_models,
        "flux3_models": flux3_models,
        "qwen21_models": qwen21_models,
        "klein_models": klein_models,
        "me_enabled": bool(load_me_photos()),
        "prompt_model_groups": load_prompt_model_groups(),
        "topics": topics,
        "queue_count": queue_count
    }


def _generate(prompt: str | None, prompt_model: str, image_model: str, topic: str) -> None:
    """Runs on a job worker because prompt generation can take minutes."""
    config = load_config()
    selected_topic = topic if topic and topic != "random" else ""
    base_prompt = config["comfyui"]["prompt"]
    if image_model == ME_MODEL:
        base_prompt = ME_PROMPT
        topic = topic or "random"
    if not prompt:
        jobs.update_current(status="prompt")
        if prompt_model and prompt_model != "Random Prompt Model":
            service, _, service_model = prompt_model.partition(":")
            prompt = try_prompt_service(service, service_model, base_prompt, topic)
        else:
            prompt, selected_topic = create_prompt_with_random_model(base_prompt, topic)
    create_image(prompt, image_model, selected_topic)


@bp.route("/create", methods=["GET", "POST"])
@requires_create_auth
def create():
    if request.method == "POST":
        prompt = _validate_prompt(request.form.get("prompt", ""))
        image_model = _validate_model(request.form.get("model") or "Random Image Model")
        topic = _validate_topic(request.form.get("topic", ""))
        prompt_model = request.form.get("prompt_model") or ""

        if not prompt and prompt_model and prompt_model != "Random Prompt Model":
            # Model ids contain ":" and "/", so check against the known list, not a pattern.
            service, _, service_model = prompt_model.partition(":")
            if (service, service_model) not in load_prompt_models_from_config():
                flash("Invalid prompt model specified.", "error")
                return redirect(url_for("create_routes.create_image_page"))

        job_id = jobs.submit(
            _generate, prompt, prompt_model, image_model, topic, prompt=prompt or "", model=image_model
        )
        return redirect(url_for("create_routes.image_queued", job=job_id))

    models_and_topics = _load_models_and_topics()
    return render_template("create_image.html", **models_and_topics)


@bp.route("/image_queued")
def image_queued():
    job = jobs.get_job(request.args.get("job", ""))
    if job is None:
        return render_template("image_queued.html", job=None), 404
    return render_template("image_queued.html", job=job)


@bp.route("/create_image", methods=["GET"])
@requires_create_auth
def create_image_page():
    models_and_topics = _load_models_and_topics()
    return render_template("create_image.html", **models_and_topics)
