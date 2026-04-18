import configparser
import hashlib
import hmac
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

from PIL import Image

from libs.create_thumbnail import generate_thumbnail

logger = logging.getLogger(__name__)

LOG_FILE = "./prompts_log.jsonl"

SYSTEM_PROMPT = (
    "You are a prompt generator for Stable Diffusion. "
    "Generate a detailed and imaginative prompt with a strong visual theme. "
    "Focus on lighting, atmosphere, and artistic style. "
    "Keep the prompt concise, no extra commentary or formatting."
)


def extract_prompt(text: str) -> str:
    """Extract a prompt from LLM response text by stripping quotes and extracting content."""
    text = text.strip('"')
    match = re.search(r'"([^"]+)"', text)
    if not match:
        match = re.search(r":\s*\n*\s*(.+)", text)
    if match:
        text = match.group(1)
    return text.strip()

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


def load_recent_topics(count=5):
    recent_topics = []

    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
            for line in lines[-count:]:
                data = json.loads(line.strip())
                topic = data.get("topic", "")
                if topic:
                    recent_topics.append(topic)
    except FileNotFoundError:
        pass  # No prompts yet

    return recent_topics


def save_prompt(prompt, topic=""):
    entry = {"date": datetime.now().strftime("%Y-%m-%d"), "prompt": prompt, "topic": topic}
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_bool(config: configparser.ConfigParser, section: str, key: str, default: bool = False) -> bool:
    """Parse a boolean value from ConfigParser (which stores everything as strings).
    
    Handles both 'True'/'False' (Python-style) and 'true'/'false' (lowercase) formats.
    """
    value = config.get(section, key, fallback=str(default)).lower()
    return value == "true"


def hash_password(password: str) -> str:
    """Hash a password using SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash using constant-time comparison."""
    input_hash = hash_password(password)
    return hmac.compare_digest(input_hash, stored_hash)


def load_config() -> configparser.ConfigParser:
    """Loads user configuration from ./user_config.cfg. If it doesn't exist, copies from user_config.cfg.sample."""
    user_config = configparser.ConfigParser()
    config_path = "./user_config.cfg"
    sample_path = "./user_config.cfg.sample"

    if not os.path.exists(config_path):
        if os.path.exists(sample_path):
            shutil.copy(sample_path, config_path)
            logging.info("Configuration file copied from sample.")
        else:
            logging.error("Neither user_config.cfg nor user_config.cfg.sample found.")
            sys.exit(1)

    try:
        user_config.read(config_path)
        logging.debug("Configuration loaded successfully.")
        return user_config
    except KeyError as e:
        logging.error(f"Missing configuration key: {e}")
        sys.exit(1)


def rename_image(config=None, fav_file=None) -> str | None:
    """Renames 'image.png' in the output folder to a timestamped filename if it exists."""
    cfg = config or user_config
    fav_path = fav_file or favourites_file
    output_dir = cfg["comfyui"]["output_dir"]
    old_path = os.path.join(output_dir, "image.png")

    if os.path.exists(old_path):
        new_filename = f"{str(time.time())}.png"
        new_path = os.path.join(output_dir, new_filename)

        temp_favourites_path = fav_path + ".tmp"
        if os.path.exists(fav_path):
            with open(fav_path, 'r') as f:
                favourites = json.load(f)
            if "image.png" in favourites:
                favourites.remove("image.png")
                favourites.append(new_filename)
                with open(temp_favourites_path, 'w') as f:
                    json.dump(favourites, f)
                os.replace(temp_favourites_path, fav_path)

        os.rename(old_path, new_path)
        generate_thumbnail(new_path)
        logger.info(f"Renamed 'image.png' to '{new_filename}'")
        return new_filename
    else:
        logger.info("No image.png found.")
        return None


def get_favourites() -> list[str]:
    """Loads and returns the list of favourited images."""
    if not os.path.exists(favourites_file):
        return []
    with open(favourites_file, 'r') as f:
        return json.load(f)


def save_favourites(favourites: list[str]) -> None:
    """Saves the list of favourited images atomically using os.replace()."""
    temp_path = favourites_file + ".tmp"
    with open(temp_path, 'w') as f:
        json.dump(favourites, f)
    os.replace(temp_path, favourites_file)


def get_details_from_png(path):
    try:
        date = datetime.fromtimestamp(os.path.getctime(path)).strftime("%d-%m-%Y")
        with Image.open(path) as img:
            data = json.loads(img.info["prompt"])
            prompt = data['6']['inputs']['text']
            if '38' in data and 'unet_name' in data['38']['inputs']:
                model = data['38']['inputs']['unet_name'].split(".")[0]
            elif '4' in data and 'ckpt_name' in data['4']['inputs']:
                model = data['4']['inputs']['ckpt_name']
            elif '80' in data and 'unet_name' in data['80']['inputs']:
                model = data['80']['inputs']['unet_name'].split(".")[0]
            else:
                model = "unknown"
            return {"p": prompt, "m": model, "d": date}
    except Exception as e:
        logger.warning(f"Error reading metadata from {path}: {e}")
        return {"p": "", "m": "", "d": ""}

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
        logger.error("Error running bump-my-version: %s", e)
        return "unknown"

def load_models_from_config():
    config = load_config()
    
    use_flux = get_bool(config, "comfyui", "flux", False)
    if use_flux and "comfyui:flux" in config and "models" in config["comfyui:flux"]:
        flux_models = config["comfyui:flux"]["models"].split(",")
    else:
        flux_models = []
    
    sdxl_models = config["comfyui"]["models"].split(",")
    
    use_qwen = get_bool(config, "comfyui", "qwen", False)
    if use_qwen and "comfyui:qwen" in config and "models" in config["comfyui:qwen"]:
        qwen_models = config["comfyui:qwen"]["models"].split(",")
    else:
        qwen_models = []
    
    sorted_flux_models = sorted(flux_models, key=str.lower)
    sorted_sdxl_models = sorted(sdxl_models, key=str.lower)
    sorted_qwen_models = sorted(qwen_models, key=str.lower)
    return sorted_sdxl_models, sorted_flux_models, sorted_qwen_models


def load_topics_from_config():
    config = load_config()
    topics = config["comfyui"]["topics"].split(",")
    sorted_topics = sorted(topics, key=str.lower)
    return sorted_topics

def load_openrouter_models_from_config():
    config = load_config()
    if get_bool(config, "openrouter", "enabled", False):
        models = config["openrouter"]["models"].split(",")
        configured_models = sorted([model.strip() for model in models if model.strip()], key=str.lower)
        free_models = []
        if get_bool(config, "openrouter", "list_all_free_models", False):
            from libs.openrouter import get_free_models
            free_models = get_free_models()
        return configured_models, free_models
    return [], []

def load_openwebui_models_from_config():
    config = load_config()
    if "openwebui" in config and "models" in config["openwebui"]:
        models = config["openwebui"]["models"].split(",")
        return sorted([model.strip() for model in models if model.strip()], key=str.lower)
    return []

def load_ollama_models_from_config():
    config = load_config()
    if get_bool(config, "ollama", "enabled", False) and "models" in config["ollama"]:
        models = config["ollama"]["models"].split(",")
        configured_models = sorted([model.strip() for model in models if model.strip()], key=str.lower)
        cloud_models = []
        if get_bool(config, "ollama", "list_all_cloud_models", False):
            from libs.ollama import get_cloud_models
            cloud_models = get_cloud_models()
        return configured_models, cloud_models
    return [], []

def load_prompt_models_from_config():
    """Load and return a list of available prompt generation models (OpenWebUI, OpenRouter, and Ollama)."""
    config = load_config()
    prompt_models = []

    # Add OpenWebUI models if configured
    if "openwebui" in config and "models" in config["openwebui"]:
        openwebui_models = config["openwebui"]["models"].split(",")
        prompt_models.extend([("openwebui", model.strip()) for model in openwebui_models if model.strip()])

    # Add OpenRouter models if enabled and configured
    if get_bool(config, "openrouter", "enabled", False) and "models" in config["openrouter"]:
        openrouter_models = config["openrouter"]["models"].split(",")
        prompt_models.extend([("openrouter", model.strip()) for model in openrouter_models if model.strip()])
        if get_bool(config, "openrouter", "list_all_free_models", False):
            from libs.openrouter import get_free_models
            free_models = get_free_models()
            prompt_models.extend([("openrouter", model) for model in free_models])

    if get_bool(config, "ollama", "enabled", False) and "models" in config["ollama"]:
        ollama_models = config["ollama"]["models"].split(",")
        prompt_models.extend([("ollama", model.strip()) for model in ollama_models if model.strip()])
        if get_bool(config, "ollama", "list_all_cloud_models", False):
            from libs.ollama import get_cloud_models
            cloud_models = get_cloud_models()
            prompt_models.extend([("ollama", model) for model in cloud_models])

    return prompt_models


def build_user_content(topic: str = "random") -> tuple[str, str]:
    """Build the user content string for prompt generation, including topic instructions and recent prompts avoidance."""
    config = load_config()
    topic_instruction = ""
    selected_topic = ""
    secondary_topic_instruction = ""
    # Unique list of recent prompts
    recent_prompts = list(set(load_recent_prompts()))
    recent_topics = load_recent_topics()

    if topic == "random":
        topics = [t.strip() for t in config["comfyui"]["topics"].split(",") if t.strip()]
        available_topics = [t for t in topics if t not in recent_topics]
        if available_topics:
            selected_topic = random.choice(available_topics)
        elif topics:
            selected_topic = random.choice(topics)  # Fallback if all recent
    elif topic != "":
        selected_topic = topic
    else:
        # Decide on whether to include a topic (e.g., 30% chance to include)
        topics = [t.strip() for t in config["comfyui"]["topics"].split(",") if t.strip()]
        available_topics = [t for t in topics if t not in recent_topics]
        if random.random() < 0.3 and available_topics:
            selected_topic = random.choice(available_topics)
        elif random.random() < 0.3 and topics:
            selected_topic = random.choice(topics)  # Fallback

    if selected_topic != "":
        topic_instruction = f" Incorporate the theme of '{selected_topic}' into the new prompt."

    # Add secondary topic if configured and not empty
    secondary_topic = config["comfyui"].get("secondary_topic", "").strip()
    if secondary_topic:
        secondary_topic_instruction = f" Additionally incorporate the theme of '{secondary_topic}' into the new prompt."

    user_content = (
        "Can you generate me a really random image idea, Do not exceed 20 words. Use clear language, not poetic metaphors."
        + topic_instruction
        + secondary_topic_instruction
        + "Avoid prompts similar to the following:"
        + "\n".join(f"{i+1}. {p}" for i, p in enumerate(recent_prompts))
    )

    return user_content, selected_topic


def create_prompt_with_random_model(base_prompt: str, topic: str = "random"):
    """Create a prompt using a randomly selected model from OpenWebUI, OpenRouter, or Ollama.

    If OpenWebUI fails, it will retry once. If it fails again, it will fallback to another service.
    """
    prompt_models = load_prompt_models_from_config()

    if not prompt_models:
        logging.warning("No prompt generation models configured.")
        return None, ""

    # Randomly select a model
    service, model = random.choice(prompt_models)

    # Import here to avoid circular imports
    from libs.openwebui import create_prompt_on_openwebui
    from libs.openrouter import create_prompt_on_openrouter
    from libs.ollama import create_prompt_on_ollama

    def _fallback_to_other_services(excluded_service, topic, base_prompt):
        """Try fallback to any available service other than the excluded one."""
        other_models = [m for m in prompt_models if m[0] != excluded_service]
        if other_models:
            fb_service, fb_model = random.choice(other_models)
            user_content, selected_topic = build_user_content(topic)
            full_prompt = base_prompt + "\n\n" + user_content
            if fb_service == "openrouter":
                return create_prompt_on_openrouter(full_prompt, "", fb_model), selected_topic
            elif fb_service == "ollama":
                return create_prompt_on_ollama(full_prompt, "", fb_model), selected_topic
            elif fb_service == "openwebui":
                return create_prompt_on_openwebui(full_prompt, "", fb_model), selected_topic
        logging.error(f"No fallback models available (excluded: {excluded_service}).")
        return "A colorful abstract composition", ""

    if service == "openwebui":
        try:
            logging.info(f"Attempting to generate prompt with OpenWebUI using model: {model}")
            user_content, selected_topic = build_user_content(topic)
            full_prompt = base_prompt + "\n\n" + user_content
            result = create_prompt_on_openwebui(full_prompt, "", model)
            if result:
                return result, selected_topic

            logging.warning("First OpenWebUI attempt failed. Retrying...")
            result = create_prompt_on_openwebui(full_prompt, "", model)
            if result:
                return result, selected_topic

            logging.warning("Second OpenWebUI attempt failed. Falling back to other services...")
            return _fallback_to_other_services("openwebui", topic, base_prompt)

        except Exception as e:
            logging.error(f"Error with OpenWebUI: {e}")
            logging.warning("OpenWebUI exception. Falling back to other services...")
            return _fallback_to_other_services("openwebui", topic, base_prompt)

    elif service == "openrouter":
        try:
            user_content, selected_topic = build_user_content(topic)
            full_prompt = base_prompt + "\n\n" + user_content
            return create_prompt_on_openrouter(full_prompt, "", model), selected_topic
        except Exception as e:
            logging.error(f"Error with OpenRouter: {e}")
            return _fallback_to_other_services("openrouter", topic, base_prompt)

    elif service == "ollama":
        try:
            user_content, selected_topic = build_user_content(topic)
            full_prompt = base_prompt + "\n\n" + user_content
            return create_prompt_on_ollama(full_prompt, "", model), selected_topic
        except Exception as e:
            logging.error(f"Error with Ollama: {e}")
            return _fallback_to_other_services("ollama", topic, base_prompt)


user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]
favourites_file = "./favourites.json"