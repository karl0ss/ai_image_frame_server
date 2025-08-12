from flask import Blueprint, request, render_template, redirect, url_for, session
import threading
from libs.comfyui import create_image, select_model, get_available_models
from libs.openwebui import create_prompt_on_openwebui
from libs.generic import load_models_from_config, load_topics_from_config, load_openrouter_models_from_config, load_openwebui_models_from_config, create_prompt_with_random_model
import os

bp = Blueprint("create_routes", __name__)
user_config = None  # will be set in init_app

@bp.route("/create", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        prompt = request.form.get("prompt")
        image_model = request.form.get("model") or "Random Image Model"
        selected_workflow, model = select_model(image_model)
        topic = request.form.get("topic")

        if not prompt:
            # Get the prompt model from the form data
            prompt_model = request.form.get("prompt_model") or ""
            if prompt_model and prompt_model != "Random Prompt Model":
                # Use the specified prompt model
                service, service_model = prompt_model.split(":", 1) if ":" in prompt_model else (prompt_model, "")
                if service == "openwebui":
                    from libs.openwebui import create_prompt_on_openwebui
                    prompt = create_prompt_on_openwebui(user_config["comfyui"]["prompt"], topic, service_model)
                elif service == "openrouter":
                    from libs.openrouter import create_prompt_on_openrouter
                    prompt = create_prompt_on_openrouter(user_config["comfyui"]["prompt"], topic, service_model)
            else:
                # Use a random prompt model
                prompt = create_prompt_with_random_model(user_config["comfyui"]["prompt"], topic)

        threading.Thread(target=lambda: create_image(prompt, model)).start()
        return redirect(url_for("create_routes.image_queued", prompt=prompt, model=model.split(".")[0]))

    # Load all models (SDXL, FLUX, and Qwen)
    sdxl_models, flux_models, qwen_models = load_models_from_config()
    openwebui_models = load_openwebui_models_from_config()
    openrouter_models = load_openrouter_models_from_config()
    
    return render_template("create_image.html",
                         sdxl_models=sdxl_models,
                         flux_models=flux_models,
                         qwen_models=qwen_models,
                         openwebui_models=openwebui_models,
                         openrouter_models=openrouter_models,
                         topics=load_topics_from_config())

@bp.route("/image_queued")
def image_queued():
    prompt = request.args.get("prompt", "No prompt provided.")
    model = request.args.get("model", "No model selected.")
    if model == "Random Image Model":
        model = "Random"
    else:
        model = model.split(".")[0]
    return render_template("image_queued.html", prompt=prompt, model=model)

@bp.route("/create_image", methods=["GET"])
def create_image_page():
    if user_config["frame"]["create_requires_auth"] == "True" and not session.get("authenticated"):
        return redirect(url_for("auth_routes.login", next=request.path))
    
    # Load all models (SDXL, FLUX, and Qwen)
    sdxl_models, flux_models, qwen_models = load_models_from_config()
    openwebui_models = load_openwebui_models_from_config()
    openrouter_models = load_openrouter_models_from_config()
    
    return render_template("create_image.html",
                         sdxl_models=sdxl_models,
                         flux_models=flux_models,
                         qwen_models=qwen_models,
                         openwebui_models=openwebui_models,
                         openrouter_models=openrouter_models,
                         topics=load_topics_from_config())


def init_app(config):
    global user_config
    user_config = config
