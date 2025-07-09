import subprocess
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


def rename_image(new_filename: str) -> str | None:
    """Renames the latest image in the output folder to a timestamped filename."""
    output_dir = user_config["comfyui"]["output_dir"]
    image_png_path = os.path.join(output_dir, "image.png")
    
    # Check if image.png exists and is a favourite
    if os.path.exists(image_png_path):
        favourites = get_favourites()
        if "image.png" in favourites:
            # It's a favourite, so rename it to preserve it
            timestamped_filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
            timestamped_path = os.path.join(output_dir, timestamped_filename)
            os.rename(image_png_path, timestamped_path)
            
            # Update favourites list
            favourites.remove("image.png")
            favourites.append(timestamped_filename)
            save_favourites(favourites)
            print(f"Preserved favourite 'image.png' as '{timestamped_filename}'")

    # Find the latest generated image (which is the new_filename)
    latest_image_path = os.path.join(output_dir, new_filename)
    if not os.path.exists(latest_image_path):
        print(f"Error: Newly generated image '{new_filename}' not found.")
        return None

    # Rename the latest image to "image.png"
    if os.path.exists(image_png_path):
        os.remove(image_png_path) # remove if it wasn't a favourite
        
    os.rename(latest_image_path, image_png_path)
    generate_thumbnail(image_png_path)
    print(f"Renamed '{new_filename}' to 'image.png'")
    return "image.png"


def get_details_from_png(path):
    try:
        date = datetime.fromtimestamp(os.path.getctime(path)).strftime("%d-%m-%Y")
        with Image.open(path) as img:
            try:
                # Flux workflow
                data = json.loads(img.info["prompt"])
                prompt = data['44']['inputs']['text']
                model = data['35']['inputs']['unet_name'].split(".")[0]
            except KeyError:
                # SDXL workflow
                data = json.loads(img.info["prompt"])
                prompt = data['6']['inputs']['text']
                model = data['4']['inputs']['ckpt_name']
            return {"p":prompt,"m":model,"d":date} or {"p":"","m":"","c":""}
    except Exception as e:
        print(f"Error reading metadata from {path}: {e}")
        return ""

def get_current_version():
    try:
        # Run the command and capture the output
        result = subprocess.run(
            ['bump-my-version', 'show', 'current_version'], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,  # to get string output instead of bytes
            check=True  # raises exception if command fails
        )
        version = result.stdout.strip()
        return version
    except subprocess.CalledProcessError as e:
        print("Error running bump-my-version:", e)
        return None

def load_models_from_config():
    flux_models = load_config()["comfyui:flux"]["models"].split(",")
    sdxl_models = load_config()["comfyui"]["models"].split(",")
    sorted_flux_models = sorted(flux_models, key=str.lower)
    sorted_sdxl_models = sorted(sdxl_models, key=str.lower)
    return sorted_sdxl_models, sorted_flux_models


def load_topics_from_config():
    topics = load_config()["comfyui"]["topics"].split(",")
    sorted_topics = sorted(topics, key=str.lower)
    return sorted_topics


favourites_file = "./favourites.json"

def get_favourites():
    if not os.path.exists(favourites_file):
        return []
    with open(favourites_file, 'r') as f:
        return json.load(f)

def save_favourites(favourites):
    with open(favourites_file, 'w') as f:
        json.dump(favourites, f)

user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]