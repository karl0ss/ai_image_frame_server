import os
from flask import Blueprint, render_template
from libs.generic import get_details_from_png, load_config, get_selected_image

bp = Blueprint("index_routes", __name__)


@bp.route("/", methods=["GET"])
def index():
    config = load_config()
    output_folder = config["comfyui"]["output_dir"]
    selected = get_selected_image()
    image_filename = selected if selected else "image.png"
    image_path = os.path.join(output_folder, image_filename)
    details = get_details_from_png(image_path)
    prompt = details.get("p", "") if details else ""

    return render_template(
        "index.html",
        image=image_filename,
        prompt=prompt if prompt else "No prompt available",
        reload_interval=config["frame"]["reload_interval"],
        selected=selected,
    )