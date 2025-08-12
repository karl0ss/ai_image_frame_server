import subprocess
import configparser
import logging
import sys
import time
import os
import random
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
    favourites_file = "./favourites.json"

    if os.path.exists(old_path):
        new_filename = f"{str(time.time())}.png"
        new_path = os.path.join(user_config["comfyui"]["output_dir"], new_filename)

        # Check if image.png is a favourite
        if os.path.exists(favourites_file):
            with open(favourites_file, 'r') as f:
                favourites = json.load(f)
            if "image.png" in favourites:
                favourites.remove("image.png")
                favourites.append(new_filename)
                with open(favourites_file, 'w') as f:
                    json.dump(favourites, f)

        os.rename(old_path, new_path)
        generate_thumbnail(new_path)
        print(f"Renamed 'image.png' to '{new_filename}'")
        return new_filename
    else:
        print("No image.png found.")
        return None


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
        return "unknown"

def load_models_from_config():
    flux_models = load_config()["comfyui:flux"]["models"].split(",")
    sdxl_models = load_config()["comfyui"]["models"].split(",")
    qwen_models = load_config()["comfyui:qwen"]["models"].split(",")
    sorted_flux_models = sorted(flux_models, key=str.lower)
    sorted_sdxl_models = sorted(sdxl_models, key=str.lower)
    sorted_qwen_models = sorted(qwen_models, key=str.lower)
    return sorted_sdxl_models, sorted_flux_models, sorted_qwen_models


def load_topics_from_config():
    topics = load_config()["comfyui"]["topics"].split(",")
    sorted_topics = sorted(topics, key=str.lower)
    return sorted_topics

def load_openrouter_models_from_config():
    config = load_config()
    if config["openrouter"].get("enabled", "False").lower() == "true":
        models = config["openrouter"]["models"].split(",")
        return sorted([model.strip() for model in models if model.strip()], key=str.lower)
    return []

def load_openwebui_models_from_config():
    config = load_config()
    if "openwebui" in config and "models" in config["openwebui"]:
        models = config["openwebui"]["models"].split(",")
        return sorted([model.strip() for model in models if model.strip()], key=str.lower)
    return []

def load_prompt_models_from_config():
    """Load and return a list of available prompt generation models (both OpenWebUI and OpenRouter)."""
    config = load_config()
    prompt_models = []
    
    # Add OpenWebUI models if configured
    if "openwebui" in config and "models" in config["openwebui"]:
        openwebui_models = config["openwebui"]["models"].split(",")
        prompt_models.extend([("openwebui", model.strip()) for model in openwebui_models if model.strip()])
    
    # Add OpenRouter models if enabled and configured
    if config["openrouter"].get("enabled", "False").lower() == "true" and "models" in config["openrouter"]:
        openrouter_models = config["openrouter"]["models"].split(",")
        prompt_models.extend([("openrouter", model.strip()) for model in openrouter_models if model.strip()])
    
    return prompt_models


def create_prompt_with_random_model(base_prompt: str, topic: str = "random"):
    """Create a prompt using a randomly selected model from OpenWebUI or OpenRouter.
    
    If OpenWebUI fails, it will retry once. If it fails again, it will fallback to OpenRouter.
    """
    prompt_models = load_prompt_models_from_config()
    
    if not prompt_models:
        logging.warning("No prompt generation models configured.")
        return None
    
    # Randomly select a model
    service, model = random.choice(prompt_models)
    
    # Import here to avoid circular imports
    from libs.openwebui import create_prompt_on_openwebui
    from libs.openrouter import create_prompt_on_openrouter
    
    if service == "openwebui":
        try:
            # First attempt with OpenWebUI
            logging.info(f"Attempting to generate prompt with OpenWebUI using model: {model}")
            result = create_prompt_on_openwebui(base_prompt, topic, model)
            if result:
                return result
            
            # If first attempt returns None, try again
            logging.warning("First OpenWebUI attempt failed. Retrying...")
            result = create_prompt_on_openwebui(base_prompt, topic, model)
            if result:
                return result
            
            # If second attempt fails, fallback to OpenRouter
            logging.warning("Second OpenWebUI attempt failed. Falling back to OpenRouter...")
            openrouter_models = [m for m in prompt_models if m[0] == "openrouter"]
            if openrouter_models:
                _, openrouter_model = random.choice(openrouter_models)
                return create_prompt_on_openrouter(base_prompt, topic, openrouter_model)
            else:
                logging.error("No OpenRouter models configured for fallback.")
                return "A colorful abstract composition"  # Default fallback prompt
                
        except Exception as e:
            logging.error(f"Error with OpenWebUI: {e}")
            # Fallback to OpenRouter on exception
            logging.warning("OpenWebUI exception. Falling back to OpenRouter...")
            openrouter_models = [m for m in prompt_models if m[0] == "openrouter"]
            if openrouter_models:
                _, openrouter_model = random.choice(openrouter_models)
                try:
                    return create_prompt_on_openrouter(base_prompt, topic, openrouter_model)
                except Exception as e2:
                    logging.error(f"Error with OpenRouter fallback: {e2}")
                    return "A colorful abstract composition"  # Default fallback prompt
            else:
                logging.error("No OpenRouter models configured for fallback.")
                return "A colorful abstract composition"  # Default fallback prompt
    
    elif service == "openrouter":
        try:
            # Use OpenRouter
            return create_prompt_on_openrouter(base_prompt, topic, model)
        except Exception as e:
            logging.error(f"Error with OpenRouter: {e}")
            return "A colorful abstract composition"  # Default fallback prompt
    
    return "A colorful abstract composition"  # Default fallback prompt

user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]