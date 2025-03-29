from flask import Flask, render_template, send_from_directory, redirect, url_for
import os
from lib import create_image

app = Flask(__name__)

image_folder = "./output"

@app.route('/')
def index():
    # latest_image = get_latest_image()
    return render_template("index.html", image="./image.png")

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
    app.run(host="0.0.0.0", port=5000, debug=True)

