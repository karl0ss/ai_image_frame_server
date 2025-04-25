import configparser
import logging
import sys
import time
import os
from PIL import Image
import nest_asyncio
import json
from datetime import datetime
from libs.create_thumbnail import generate_thumbnail
nest_asyncio.apply()

logging.basicConfig(level=logging.INFO)

LOG_FILE = "./prompts_log.jsonl"

def load_recent_prompts(count=7):
    recent_prompts = []

    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
            for line in lines[-count:]:
                data = json.loads(line.strip())
                recent_prompts.append(data["prompt"])
    except FileNotFoundError:
        pass  # No prompts yet

    return recent_prompts


def save_prompt(prompt):
    entry = {"date": datetime.now().strftime("%Y-%m-%d"), "prompt": prompt}
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def load_config() -> configparser.ConfigParser:
    """Loads user configuration from ./user_config.cfg."""
    user_config = configparser.ConfigParser()
    try:
        user_config.read("./user_config.cfg")
        logging.debug("Configuration loaded successfully.")
        return user_config
    except KeyError as e:
        logging.error(f"Missing configuration key: {e}")
        sys.exit(1)


def rename_image() -> str | None:
    """Renames 'image.png' in the output folder to a timestamped filename if it exists."""
    old_path = os.path.join(user_config["comfyui"]["output_dir"], "image.png")

    if os.path.exists(old_path):
        new_filename = f"{str(time.time())}.png"
        new_path = os.path.join(user_config["comfyui"]["output_dir"], new_filename)
        os.rename(old_path, new_path)
        generate_thumbnail(new_path)
        print(f"Renamed 'image.png' to '{new_filename}'")
        return new_filename
    else:
        print("No image.png found.")
        return None


def get_prompt_from_png(path):
    try:
        with Image.open(path) as img:
            try:
                # Flux workflow
                meta = json.loads(img.info["prompt"])['44']['inputs']['text']
            except KeyError:
                # SDXL workflow
                meta = json.loads(img.info["prompt"])['6']['inputs']['text']
            return meta or ""
    except Exception as e:
        print(f"Error reading metadata from {path}: {e}")
        return ""


user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]