from flask import (
    Flask,
    render_template,
    send_from_directory,
    redirect,
    url_for,
    request,
    jsonify,
)
import os
import time
from apscheduler.schedulers.background import BackgroundScheduler
from lib import create_image, load_config

user_config = load_config()
app = Flask(__name__)

image_folder = "./output"

@app.route("/", methods=["GET"])
def index() -> str:
    """
    Renders the main HTML template.
    Args:
        None
    Returns:
        str: The rendered HTML template.
    """
    return render_template(
        "index.html",
        image="./image.png",
        reload_interval=user_config["frame"]["reload_interval"],
    )
    
@app.route("/images", methods=["GET"])
def gallery() -> str:
    """
    Renders the gallery HTML template.
    Args:
        None
    Returns:
        str: The rendered HTML template.
    """
    images = [f for f in os.listdir(image_folder) if f.lower().endswith(('png', 'jpg', 'jpeg', 'gif'))]
    return render_template("gallery.html", images=images)


@app.route("/images/<filename>", methods=["GET"])
def images(filename: str) -> None:
    """
    Serves the requested image file.
    Args:
        filename (str): The name of the image file.
    Returns:
        None: Sends the image file.
    """
    return send_from_directory(image_folder, filename)


@app.route("/create", methods=["GET", "POST"])
def create() -> str:
    """Handles image creation requests.
    Args:
        None
    Returns:
        str: Redirect to the main page or a JSON response.
    """
    prompt = request.form.get("prompt") if request.method == "POST" else None
    create_image(prompt)
    if request.method == "POST":
        return jsonify({"message": "Image created", "prompt": prompt}), 200
    return redirect(url_for("index"))


def scheduled_task() -> None:
    """Executes the scheduled image generation task."""
    print(f"Executing scheduled task at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    create_image(None)


if user_config["frame"]["auto_regen"] == "True":
    scheduler = BackgroundScheduler()
    regen_time = user_config["frame"]["regen_time"].split(":")
    scheduler.add_job(scheduled_task, "cron", hour=regen_time[0], minute=regen_time[1])
    scheduler.start()

    os.makedirs(image_folder, exist_ok=True)
    app.run(host="0.0.0.0", port=user_config["frame"]["port"], debug=True)

