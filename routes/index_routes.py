from flask import Blueprint, render_template
import os
from libs.generic import get_details_from_png, get_current_version, load_config

bp = Blueprint("index_routes", __name__)
image_folder = "./output"
user_config = load_config()

@bp.route("/", methods=["GET"])
def index():
    image_filename = "./image.png"
    image_path = os.path.join(image_folder, image_filename)
    prompt = get_details_from_png(image_path)["p"]
    version = get_current_version()

    return render_template(
        "index.html",
        image=image_filename,
        prompt=prompt,
        reload_interval=user_config["frame"]["reload_interval"],
        version=version,
    )
