from flask import Blueprint, render_template
import os

bp = Blueprint("gallery_routes", __name__)
image_folder = "./output"

@bp.route("/images", methods=["GET"])
def gallery():
    images = [
        {"filename": f}
        for f in os.listdir(image_folder)
        if f.lower().endswith(("png", "jpg", "jpeg", "gif"))
    ]
    images = sorted(images, key=lambda x: os.path.getmtime(os.path.join(image_folder, x["filename"])), reverse=True)
    return render_template("gallery.html", images=images)
