import os
from flask import Blueprint, render_template, request, jsonify
from libs.generic import get_favourites, toggle_favourite as toggle_favourite_file, load_config, get_selected_image, set_selected_image

bp = Blueprint("gallery_routes", __name__)

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif")


@bp.route("/images", methods=["GET"])
def gallery():
    config = load_config()
    image_folder = config["comfyui"]["output_dir"].rstrip("/")
    favourites = get_favourites()
    selected = get_selected_image()
    favourite_names = set(favourites)
    entries = []
    try:
        with os.scandir(image_folder) as scan:
            for entry in scan:
                if not entry.name.lower().endswith(_IMAGE_EXTENSIONS):
                    continue
                try:
                    entries.append((entry.stat().st_mtime, entry.name))
                except FileNotFoundError:
                    continue  # Archived by a render between listing and stat.
    except FileNotFoundError:
        pass
    entries.sort(reverse=True)
    # Cloudflare gives these a 4 hour browser cache, and image.png keeps its URL between renders.
    images = [
        {"filename": name, "favourited": name in favourite_names, "version": int(mtime)}
        for mtime, name in entries
    ]
    return render_template("gallery.html", images=images, selected=selected)

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

    return jsonify({"status": "success", "favourited": toggle_favourite_file(filename)})


@bp.route("/select-image", methods=["POST"])
def select_image():
    data = request.get_json()
    if data is None:
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400

    filename = data.get("filename")
    if filename is None:
        set_selected_image(None)
        return jsonify({"status": "success", "selected": None})

    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"status": "error", "message": "Invalid filename"}), 400

    image_folder = load_config()["comfyui"]["output_dir"].rstrip("/")
    image_path = os.path.join(image_folder, filename)
    if not os.path.exists(image_path):
        return jsonify({"status": "error", "message": "File not found"}), 404

    set_selected_image(filename)
    return jsonify({"status": "success", "selected": filename})