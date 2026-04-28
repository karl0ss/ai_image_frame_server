import os
from flask import Blueprint, render_template, request, jsonify
from libs.generic import get_favourites, save_favourites, load_config

bp = Blueprint("gallery_routes", __name__)

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif")


@bp.route("/images", methods=["GET"])
def gallery():
    config = load_config()
    image_folder = config["comfyui"]["output_dir"].rstrip("/")
    favourites = get_favourites()
    try:
        entries = os.listdir(image_folder)
    except FileNotFoundError:
        entries = []
    images = [
        {"filename": f, "favourited": f in favourites}
        for f in entries
        if f.lower().endswith(_IMAGE_EXTENSIONS)
    ]
    images.sort(key=lambda x: os.path.getmtime(os.path.join(image_folder, x["filename"])), reverse=True)
    return render_template("gallery.html", images=images)

@bp.route("/favourites", methods=["GET"])
def get_favourites_route():
    return jsonify(get_favourites())

@bp.route("/favourites/toggle", methods=["POST"])
def toggle_favourite():
    data = request.get_json()
    if data is None:
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400
    
    filename = data.get("filename")
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"status": "error", "message": "Invalid filename"}), 400

    favourites = get_favourites()
    is_favourited = False
    if filename in favourites:
        favourites.remove(filename)
    else:
        favourites.append(filename)
        is_favourited = True

    save_favourites(favourites)
    return jsonify({"status": "success", "favourited": is_favourited})