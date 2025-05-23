from flask import (
    Flask,
    render_template,
    send_from_directory,
    request,
    jsonify,
)
import os
import time
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from libs.generic import load_config, load_recent_prompts, get_details_from_png, get_current_version, load_models_from_config
from libs.comfyui import cancel_current_job, create_image
from libs.ollama import create_prompt_on_openwebui

#workflow test commit

user_config = load_config()
app = Flask(__name__)

image_folder = "./output"

@app.route("/", methods=["GET"])
def index() -> str:
    """
    Renders the main HTML template with image and prompt.
    """
    image_filename = "./image.png"
    image_path = os.path.join(image_folder, image_filename)

    prompt = get_details_from_png(image_path)["p"]

    version = get_current_version()

    return render_template(
        "index.html",
        image=image_filename,
        prompt=prompt,
        reload_interval=user_config["frame"]["reload_interval"],
        version=version
    )

@app.route("/images", methods=["GET"])
def gallery() -> str:
    images = []
    for f in os.listdir(image_folder):
        if f.lower().endswith(('png', 'jpg', 'jpeg', 'gif')):
            images.append({'filename': f})
    images = sorted(images, key=lambda x: os.path.getmtime(os.path.join(image_folder, x['filename'])), reverse=True)
    return render_template("gallery.html", images=images)
    

@app.route("/image-details/<filename>", methods=["GET"])
def image_details(filename):
    path = os.path.join(image_folder, filename)
    if not os.path.exists(path):
        return {"error": "File not found"}, 404
    details = get_details_from_png(path)
    return {
        "prompt": details["p"],
        "model": details["m"]
    }
    

@app.route('/images/thumbnails/<path:filename>')
def serve_thumbnail(filename):
    return send_from_directory('output/thumbnails', filename)


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


@app.route("/cancel", methods=["GET"])
def cancel_job() -> None:
    """
    Serves the requested image file.
    Args:
        filename (str): The name of the image file.
    Returns:
        None: Sends the image file.
    """
    return cancel_current_job()


@app.route("/create", methods=["GET", "POST"])
def create() -> str:
    """Handles image creation requests.
    Args:
        None
    Returns:
        str: Redirect to the main page or a JSON response.
    """
    prompt = request.form.get("prompt") if request.method == "POST" else None
    model = request.form.get("model") if request.method == "POST" else "Random"


    if prompt is None:
        prompt = create_prompt_on_openwebui(user_config["comfyui"]["prompt"])
        
    def create_image_in_background():
        create_image(prompt, model)

    threading.Thread(target=create_image_in_background).start()
    return render_template('image_queued.html', prompt=prompt)


def scheduled_task() -> None:
    """Executes the scheduled image generation task."""
    print(f"Executing scheduled task at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    create_image(None)

@app.route("/create_image", methods=["GET"])
def create_image_endpoint() -> str:
    """
    Renders the create image template with image and prompt.
    """

    models = load_models_from_config()
    models.insert(0, "Random")	

    return render_template(
        "create_image.html", models=models
    )
    


if user_config["frame"]["auto_regen"] == "True":
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        scheduler = BackgroundScheduler()
        regen_time = user_config["frame"]["regen_time"].split(":")
        scheduler.add_job(
            scheduled_task,
            "cron",
            hour=regen_time[0],
            minute=regen_time[1],
            id="scheduled_task",
            max_instances=1,  # prevent overlapping
            replace_existing=True  # don't double-schedule
        )
        scheduler.start()

    os.makedirs(image_folder, exist_ok=True)
    app.run(host="0.0.0.0", port=user_config["frame"]["port"], debug=True)

