from flask import Blueprint, send_from_directory, jsonify
import os
from libs.generic import get_details_from_png, load_config

bp = Blueprint("image_routes", __name__)


def _get_output_dir():
    config = load_config()
    return config["comfyui"]["output_dir"].rstrip("/")


@bp.route("/images/<filename>", methods=["GET"])
def serve_image(filename):
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    return send_from_directory(_get_output_dir(), filename)


@bp.route("/images/thumbnails/<filename>", methods=["GET"])
def serve_thumbnail(filename):
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    output_dir = _get_output_dir()
    return send_from_directory(os.path.join(output_dir, "thumbnails"), filename)

@bp.route("/image-details/<filename>", methods=["GET"])
def image_details(filename):
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    output_dir = _get_output_dir()
    path = os.path.join(output_dir, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    details = get_details_from_png(path)
    return jsonify({"prompt": details["p"], "model": details["m"], "date": details["d"]})