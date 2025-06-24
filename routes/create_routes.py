from flask import Blueprint, request, render_template, redirect, url_for, session
import threading
from libs.comfyui import create_image, select_model, get_available_models
from libs.ollama import create_prompt_on_openwebui
from libs.generic import load_models_from_config, load_topics_from_config
import os

bp = Blueprint("create_routes", __name__)
user_config = None  # will be set in init_app

@bp.route("/create", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        prompt = request.form.get("prompt")
        selected_workflow, model = select_model(request.form.get("model") or "Random")
        topic = request.form.get("topic")

        if not prompt:
            prompt = create_prompt_on_openwebui(user_config["comfyui"]["prompt"], topic)

        threading.Thread(target=lambda: create_image(prompt, model)).start()
        return redirect(url_for("create_routes.image_queued", prompt=prompt, model=model.split(".")[0]))

    return render_template("create_image.html", models=load_models_from_config()[0]+load_models_from_config()[1], topics=load_topics_from_config())

@bp.route("/image_queued")
def image_queued():
    prompt = request.args.get("prompt", "No prompt provided.")
    model = request.args.get("model", "No model selected.").split(".")[0]
    return render_template("image_queued.html", prompt=prompt, model=model)

@bp.route("/create_image", methods=["GET"])
def create_image_page():
    if user_config["frame"]["create_requires_auth"] == "True" and not session.get("authenticated"):
        return redirect(url_for("auth_routes.login", next=request.path))
    return render_template("create_image.html", models=load_models_from_config()[0]+load_models_from_config()[1], topics=load_topics_from_config())


def init_app(config):
    global user_config
    user_config = config
