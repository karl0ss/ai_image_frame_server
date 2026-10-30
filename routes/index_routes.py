import os
from flask import Blueprint, jsonify, make_response, render_template, url_for
from libs.generic import get_details_from_png, load_config, get_selected_image

bp = Blueprint("index_routes", __name__)


def _frame_state() -> dict:
    config = load_config()
    selected = get_selected_image()
    image_filename = selected if selected else "image.png"
    image_path = os.path.join(config["comfyui"]["output_dir"], image_filename)
    details = get_details_from_png(image_path)
    try:
        version = int(os.path.getmtime(image_path))
    except OSError:
        version = 0
    return {
        "image": image_filename,
        # The version changes the URL, so no browser or proxy can reuse the previous image.
        "url": url_for("image_routes.serve_image", filename=image_filename, v=version),
        "version": version,
        "prompt": details.get("p", "") or "No prompt available",
        "selected": selected,
    }


@bp.route("/", methods=["GET"])
def index():
    response = make_response(render_template(
        "index.html",
        reload_interval=load_config()["frame"]["reload_interval"],
        **_frame_state(),
    ))
    response.headers["Cache-Control"] = "no-cache"
    return response


@bp.route("/api/frame", methods=["GET"])
def frame_state():
    response = jsonify(_frame_state())
    response.headers["Cache-Control"] = "no-store"
    return response
