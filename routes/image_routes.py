from flask import Blueprint, send_from_directory, jsonify
import os
from libs.generic import get_details_from_png

bp = Blueprint("image_routes", __name__)
image_folder = "./output"

@bp.route("/images/<filename>", methods=["GET"])
def serve_image(filename):
    return send_from_directory(image_folder, filename)

@bp.route("/images/thumbnails/<path:filename>")
def serve_thumbnail(filename):
    return send_from_directory("output/thumbnails", filename)

@bp.route("/image-details/<filename>", methods=["GET"])
def image_details(filename):
    path = os.path.join(image_folder, filename)
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    details = get_details_from_png(path)
    return jsonify({"prompt": details["p"], "model": details["m"], "date": details["d"]})
