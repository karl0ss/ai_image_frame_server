import logging
import os

import nest_asyncio
from flask import Flask

from libs.generic import load_config, get_bool
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

logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger(__name__)

user_config = load_config()

nest_asyncio.apply()

app = Flask(__name__)
secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    import secrets
    secret_key = secrets.token_hex(32)
app.secret_key = secret_key

from libs.generic import get_current_version
@app.context_processor
def inject_version():
    version = get_current_version()
    return dict(version=version)

create_routes.init_app(user_config)
auth_routes.init_app(user_config)

app.register_blueprint(index_routes.bp)
app.register_blueprint(auth_routes.bp)
app.register_blueprint(favourites_routes.bp)
app.register_blueprint(gallery_routes.bp)
app.register_blueprint(image_routes.bp)
app.register_blueprint(job_routes.bp)
app.register_blueprint(create_routes.bp)
app.register_blueprint(settings_routes.bp)

from apscheduler.schedulers.background import BackgroundScheduler
import time
from libs.comfyui import create_image

def scheduled_task():
    logger.info("Executing scheduled task at %s", time.strftime('%Y-%m-%d %H:%M:%S'))
    from libs.generic import create_prompt_with_random_model
    base_prompt = user_config["comfyui"].get("prompt", "Generate a random detailed prompt for stable diffusion.")
    prompt, topic = create_prompt_with_random_model(base_prompt, "")
    if prompt:
        model = "Random Image Model"
        create_image(prompt, model, topic)
    else:
        logger.warning("Failed to generate a prompt for the scheduled task.")

should_schedule = get_bool(user_config, "frame", "auto_regen", False)
logger.info("auto_regen config check: %s", should_schedule)
if should_schedule:
    logger.info("Initializing scheduled image generation at %s", user_config["frame"]["regen_time"])
    scheduler = BackgroundScheduler()
    h, m = user_config["frame"]["regen_time"].split(":")
    scheduler.add_job(scheduled_task, "cron", hour=h, minute=m, id="scheduled_task", max_instances=1, replace_existing=True)
    scheduler.start()
    logger.info("Scheduled image generation active - will run daily at %s", user_config["frame"]["regen_time"])

output_dir = user_config["comfyui"]["output_dir"].rstrip("/")
os.makedirs(output_dir, exist_ok=True)
debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
app.run(host="0.0.0.0", port=user_config["frame"]["port"], debug=debug)