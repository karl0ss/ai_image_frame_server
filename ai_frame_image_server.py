from flask import Flask, render_template, send_from_directory, redirect, url_for
import os
from lib import create_image

app = Flask(__name__)

image_folder = "./output"

def get_latest_image():
    """Get the latest image file from the directory."""
    files = [f for f in os.listdir(image_folder) if f.endswith(('.png', '.jpg', '.jpeg'))]
    if not files:
        return None
    latest_file = max(files, key=lambda f: os.path.getmtime(os.path.join(image_folder, f)))
    return latest_file


@app.route('/')
def index():
    latest_image = get_latest_image()
    return render_template("index.html", image=latest_image)

@app.route('/images/<filename>')
def images(filename):
    return send_from_directory(image_folder, filename)

@app.route('/create')
def create():
    """Endpoint to create a new image."""
    create_image()
    return redirect(url_for("index"))

if __name__ == '__main__':
    os.makedirs(image_folder, exist_ok=True)  # Ensure the folder exists
    app.run(debug=True)
