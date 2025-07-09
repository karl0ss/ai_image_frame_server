from flask import Blueprint, render_template, jsonify, request
import os
import json

bp = Blueprint("gallery_routes", __name__)
image_folder = "./output"
from libs.generic import get_favourites, save_favourites

@bp.route("/images", methods=["GET"])
def gallery():
    favourites = get_favourites()
    images = [
        {"filename": f, "favourited": f in favourites}
        for f in os.listdir(image_folder)
        if f.lower().endswith(("png", "jpg", "jpeg", "gif"))
    ]
    images = sorted(images, key=lambda x: os.path.getmtime(os.path.join(image_folder, x["filename"])), reverse=True)
    return render_template("gallery.html", images=images)

@bp.route("/favourites", methods=["GET"])
def get_favourites_route():
    return jsonify(get_favourites())

@bp.route("/favourites/toggle", methods=["POST"])
def toggle_favourite():
    data = request.get_json()
    filename = data.get("filename")
    if not filename:
        return jsonify({"status": "error", "message": "Filename missing"}), 400
        
    favourites = get_favourites()
    is_favourited = False
    if filename in favourites:
        favourites.remove(filename)
    else:
        favourites.append(filename)
        is_favourited = True
        
    save_favourites(favourites)
    return jsonify({"status": "success", "favourited": is_favourited})
