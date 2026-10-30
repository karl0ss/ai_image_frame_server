import logging
import os
import time

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask

from libs import jobs
from libs.comfyui import create_image
from libs.generic import create_prompt_with_random_model, get_bool, get_current_version, load_config
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


def create_app() -> Flask:
    app = Flask(__name__)
    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        import secrets
        secret_key = secrets.token_hex(32)
    app.secret_key = secret_key

    @app.context_processor
    def inject_version():
        return dict(version=get_current_version())

    app.register_blueprint(index_routes.bp)
    app.register_blueprint(auth_routes.bp)
    app.register_blueprint(favourites_routes.bp)
    app.register_blueprint(gallery_routes.bp)
    app.register_blueprint(image_routes.bp)
    app.register_blueprint(job_routes.bp)
    app.register_blueprint(create_routes.bp)
    app.register_blueprint(settings_routes.bp)
    return app


def scheduled_task():
    logger.info("Executing scheduled task at %s", time.strftime('%Y-%m-%d %H:%M:%S'))
    base_prompt = load_config()["comfyui"].get("prompt", "Generate a random detailed prompt for stable diffusion.")
    prompt, topic = create_prompt_with_random_model(base_prompt, "")
    if prompt:
        model = "Random Image Model"
        jobs.run(create_image, prompt, model, topic, prompt=prompt, model=model)
    else:
        logger.warning("Failed to generate a prompt for the scheduled task.")


def start_scheduler(config) -> None:
    should_schedule = get_bool(config, "frame", "auto_regen", False)
    logger.info("auto_regen config check: %s", should_schedule)
    if should_schedule:
        logger.info("Initializing scheduled image generation at %s", config["frame"]["regen_time"])
        scheduler = BackgroundScheduler()
        h, m = config["frame"]["regen_time"].split(":")
        scheduler.add_job(scheduled_task, "cron", hour=h, minute=m, id="scheduled_task", max_instances=1, replace_existing=True)
        scheduler.start()
        logger.info("Scheduled image generation active - will run daily at %s", config["frame"]["regen_time"])


def main() -> None:
    config = load_config()
    app = create_app()
    start_scheduler(config)

    output_dir = config["comfyui"]["output_dir"].rstrip("/")
    os.makedirs(output_dir, exist_ok=True)

    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    if debug:
        logger.info("Running in debug mode with Flask dev server")
        app.run(host="0.0.0.0", port=config["frame"]["port"], debug=True)
    else:
        try:
            from waitress import serve
            logger.info("Starting production server on port %s", config["frame"]["port"])
            serve(app, host="0.0.0.0", port=config["frame"]["port"])
        except ImportError:
            logger.warning("waitress not installed, falling back to Flask dev server")
            app.run(host="0.0.0.0", port=config["frame"]["port"], debug=False)


if __name__ == "__main__":
    main()
