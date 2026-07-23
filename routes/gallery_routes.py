import os
from flask import Blueprint, render_template, request, jsonify
from libs.generic import get_favourites, save_favourites, load_config, get_selected_image, set_selected_image

bp = Blueprint("gallery_routes", __name__)

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif")


@bp.route("/images", methods=["GET"])
def gallery():
    config = load_config()
    image_folder = config["comfyui"]["output_dir"].rstrip("/")
    favourites = get_favourites()
    selected = get_selected_image()
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

    favourites = get_favourites()
    is_favourited = False
    if filename in favourites:
        favourites.remove(filename)
    else:
        favourites.append(filename)
        is_favourited = True

    save_favourites(favourites)
    return jsonify({"status": "success", "favourited": is_favourited})


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