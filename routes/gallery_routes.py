from flask import Blueprint, render_template, jsonify, request
import os
import json

bp = Blueprint("gallery_routes", __name__)
image_folder = "./output"
favourites_file = "./favourites.json"

def get_favourites():
    if not os.path.exists(favourites_file):
        return []
    with open(favourites_file, 'r') as f:
        return json.load(f)

def save_favourites(favourites):
    with open(favourites_file, 'w') as f:
        json.dump(favourites, f)

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

@bp.route("/favourites/add", methods=["POST"])
def add_favourite():
    data = request.get_json()
    filename = data.get("filename")
    if not filename:
        return jsonify({"status": "error", "message": "Filename missing"}), 400
    
    favourites = get_favourites()
    if filename not in favourites:
        favourites.append(filename)
        save_favourites(favourites)
    return jsonify({"status": "success"})

@bp.route("/favourites/remove", methods=["POST"])
def remove_favourite():
    data = request.get_json()
    filename = data.get("filename")
    if not filename:
        return jsonify({"status": "error", "message": "Filename missing"}), 400
        
    favourites = get_favourites()
    if filename in favourites:
        favourites.remove(filename)
        save_favourites(favourites)
    return jsonify({"status": "success"})
