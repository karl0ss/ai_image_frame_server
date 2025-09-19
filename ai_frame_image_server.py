from flask import Flask
from libs.generic import load_config
import os

from routes import (
    auth_routes,
    favourites_routes,
    gallery_routes,
    image_routes,
    index_routes,
    job_routes,
    create_routes,
    settings_routes
)

user_config = load_config()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")

# Make version available to all templates
from libs.generic import get_current_version
@app.context_processor
def inject_version():
    version = get_current_version()
    return dict(version=version)

# Inject config into routes that need it
create_routes.init_app(user_config)
auth_routes.init_app(user_config)

# Register blueprints
app.register_blueprint(index_routes.bp)
app.register_blueprint(auth_routes.bp)
app.register_blueprint(favourites_routes.bp)
app.register_blueprint(gallery_routes.bp)
app.register_blueprint(image_routes.bp)
app.register_blueprint(job_routes.bp)
app.register_blueprint(create_routes.bp)
app.register_blueprint(settings_routes.bp)

# Optional: scheduler setup
from apscheduler.schedulers.background import BackgroundScheduler
import time
from libs.comfyui import create_image

def scheduled_task():
    print(f"Executing scheduled task at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    # Generate a random prompt using either OpenWebUI or OpenRouter
    from libs.generic import create_prompt_with_random_model
    prompt = create_prompt_with_random_model("Generate a random detailed prompt for stable diffusion.", "")
    if prompt:
        # Select a random model
        import random
        model = "Random Image Model"
        create_image(prompt, model)
    else:
        print("Failed to generate a prompt for the scheduled task.")

if user_config["frame"]["auto_regen"] == "True":
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        scheduler = BackgroundScheduler()
        h, m = user_config["frame"]["regen_time"].split(":")
        scheduler.add_job(scheduled_task, "cron", hour=h, minute=m, id="scheduled_task", max_instances=1, replace_existing=True)
        scheduler.start()

os.makedirs("./output", exist_ok=True)
app.run(host="0.0.0.0", port=user_config["frame"]["port"], debug=True)
