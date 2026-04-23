import configparser
import fcntl
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
import threading
import time
import uuid
from collections import OrderedDict
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

_png_details_cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_png_cache_lock = threading.Lock()
_PNG_CACHE_MAX = 256
_PNG_CACHE_TTL = 30.0


class ConfigSingleton:
    _config = None
    _mtime = 0.0
    _path = "./user_config.cfg"
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> configparser.ConfigParser:
        with cls._lock:
            config_path = cls._path
            try:
                current_mtime = os.path.getmtime(config_path)
            except OSError:
                current_mtime = 0

            if cls._config is None or current_mtime > cls._mtime:
                cfg = configparser.ConfigParser()
                read_files = cfg.read(config_path)
                if read_files:
                    cls._config = cfg
                    cls._mtime = current_mtime
                    logger.debug("Configuration loaded/reloaded from %s", config_path)
                elif cls._config is None:
                    cls._config = cfg
                    cls._mtime = current_mtime
                    logger.warning("Configuration file %s could not be read", config_path)
            return cls._config

    @classmethod
    def reset(cls):
        cls._config = None
        cls._mtime = 0.0


def load_config() -> configparser.ConfigParser:
    sample_path = "./user_config.cfg.sample"

    if not os.path.exists(ConfigSingleton._path):
        if os.path.exists(sample_path):
            shutil.copy(sample_path, ConfigSingleton._path)
            logging.info("Configuration file copied from sample.")
        else:
            logging.error("Neither user_config.cfg nor user_config.cfg.sample found.")
            sys.exit(1)

    return ConfigSingleton.get()


def get_bool(config: configparser.ConfigParser, section: str, key: str, default: bool = False) -> bool:
    value = config.get(section, key, fallback=str(default)).lower()
    return value in ("true", "1", "yes", "on")


def extract_prompt(text: str) -> str:
    text = text.strip('"')
    match = re.search(r'"([^"]+)"', text)
    if not match:
        match = re.search(r":\s*\n*\s*(.+)", text)
    if match:
        text = match.group(1)
    return text.strip()


def _read_last_lines(filepath: str, count: int) -> list[str]:
    lines: list[str] = []
    try:
        with open(filepath, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            if file_size == 0:
                return lines
            pos = file_size
            found = 0
            while pos > 0 and found < count:
                read_size = min(4096, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                found += chunk.count(b"\n")
            f.seek(max(0, pos))
            all_lines = f.read().decode("utf-8", errors="replace").splitlines()
            lines = all_lines[-count:]
    except FileNotFoundError:
        pass
    return lines


def load_recent_prompts(count=7):
    recent_prompts = []
    lines = _read_last_lines(LOG_FILE, count)
    for line in lines:
        try:
            data = json.loads(line.strip())
            recent_prompts.append(data["prompt"])
        except (json.JSONDecodeError, KeyError):
            continue
    return recent_prompts


def load_recent_topics(count=5):
    recent_topics = []
    lines = _read_last_lines(LOG_FILE, count)
    for line in lines:
        try:
            data = json.loads(line.strip())
            topic = data.get("topic", "")
            if topic:
                recent_topics.append(topic)
        except (json.JSONDecodeError, KeyError):
            continue
    return recent_topics


def save_prompt(prompt, topic=""):
    entry = {"date": datetime.now().strftime("%Y-%m-%d"), "prompt": prompt, "topic": topic}
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    input_hash = hash_password(password)
    return hmac.compare_digest(input_hash, stored_hash)


def _file_lock_path(filepath: str) -> str:
    return filepath + ".lock"


def _acquire_lock(lock_path: str):
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    except Exception:
        lock_fd.close()
        raise
    return lock_fd


def _release_lock(lock_fd):
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        lock_fd.close()


def rename_image(config=None, fav_file=None) -> str | None:
    cfg = load_config() if config is None else config
    fav_path = fav_file or favourites_file
    output_dir = cfg["comfyui"]["output_dir"]
    old_path = os.path.join(output_dir, "image.png")

    if not os.path.exists(old_path):
        logger.info("No image.png found.")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    new_filename = f"{timestamp}_{short_uuid}.png"
    new_path = os.path.join(output_dir, new_filename)

    lock_fd = None
    try:
        lock_fd = _acquire_lock(_file_lock_path(fav_path))
        if os.path.exists(fav_path):
            with open(fav_path, 'r') as f:
                favourites = json.load(f)
            if "image.png" in favourites:
                favourites.remove("image.png")
                favourites.append(new_filename)
                temp_favourites_path = fav_path + ".tmp"
                with open(temp_favourites_path, 'w') as f:
                    json.dump(favourites, f)
                os.replace(temp_favourites_path, fav_path)

        os.rename(old_path, new_path)
        generate_thumbnail(new_path)
        logger.info("Renamed 'image.png' to '%s'", new_filename)
        return new_filename
    finally:
        if lock_fd is not None:
            _release_lock(lock_fd)


def get_favourites() -> list[str]:
    if not os.path.exists(favourites_file):
        return []
    lock_fd = _acquire_lock(_file_lock_path(favourites_file))
    try:
        with open(favourites_file, 'r') as f:
            return json.load(f)
    finally:
        _release_lock(lock_fd)


def save_favourites(favourites: list[str]) -> None:
    lock_fd = _acquire_lock(_file_lock_path(favourites_file))
    try:
        temp_path = favourites_file + ".tmp"
        with open(temp_path, 'w') as f:
            json.dump(favourites, f)
        os.replace(temp_path, favourites_file)
    finally:
        _release_lock(lock_fd)


def _find_model_from_metadata(data: dict) -> str:
    for node in data.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if "unet_name" in inputs:
            return inputs["unet_name"].split(".")[0]
        if "ckpt_name" in inputs:
            return inputs["ckpt_name"]
    return "unknown"


def get_details_from_png(path):
    try:
        mtime = os.path.getmtime(path)
        with _png_cache_lock:
            if path in _png_details_cache:
                cached_mtime, cached_data = _png_details_cache[path]
                if mtime <= cached_mtime:
                    return cached_data

        date = datetime.fromtimestamp(os.path.getctime(path)).strftime("%d-%m-%Y")
        with Image.open(path) as img:
            data = json.loads(img.info["prompt"])
            prompt = ""
            for node in data.values():
                if not isinstance(node, dict):
                    continue
                class_type = node.get("class_type", "")
                inputs = node.get("inputs", {})
                text_val = inputs.get("text", "")
                if isinstance(text_val, list):
                    continue
                if class_type in ("ttN text",) or "text" in class_type.lower():
                    meta = node.get("_meta", {})
                    title = meta.get("title", "").lower()
                    if "positive" in title or "prompt" in title:
                        prompt = text_val
                        break
                if "CLIPTextEncode" in class_type:
                    meta = node.get("_meta", {})
                    title = meta.get("title", "").lower()
                    if "positive" in title or "prompt" in title:
                        if isinstance(text_val, str):
                            prompt = text_val
                            break
            if not prompt:
                for key_node in data:
                    if isinstance(data[key_node], dict):
                        text_val = data[key_node].get("inputs", {}).get("text", "")
                        if isinstance(text_val, str) and text_val:
                            prompt = text_val
                            break
            model = _find_model_from_metadata(data)
            result = {"p": prompt, "m": model, "d": date}

        with _png_cache_lock:
            _png_details_cache[path] = (mtime, result)
            if len(_png_details_cache) > _PNG_CACHE_MAX:
                _png_details_cache.popitem(last=False)
        return result
    except Exception as e:
        logger.warning("Error reading metadata from %s: %s", path, e)
        return {"p": "", "m": "", "d": ""}


def get_current_version():
    try:
        result = subprocess.run(
            ['bump-my-version', 'show', 'current_version'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
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
        flux_models = [m.strip() for m in config["comfyui:flux"]["models"].split(",") if m.strip()]
    else:
        flux_models = []

    sdxl_models = [m.strip() for m in config["comfyui"]["models"].split(",") if m.strip()]

    use_qwen = get_bool(config, "comfyui", "qwen", False)
    if use_qwen and "comfyui:qwen" in config and "models" in config["comfyui:qwen"]:
        qwen_models = [m.strip() for m in config["comfyui:qwen"]["models"].split(",") if m.strip()]
    else:
        qwen_models = []

    return (
        sorted(sdxl_models, key=str.lower),
        sorted(flux_models, key=str.lower),
        sorted(qwen_models, key=str.lower),
    )


def load_topics_from_config():
    config = load_config()
    topics = [t.strip() for t in config["comfyui"]["topics"].split(",") if t.strip()]
    return sorted(topics, key=str.lower)


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
    config = load_config()
    prompt_models = []

    if "openwebui" in config and "models" in config["openwebui"]:
        openwebui_models = config["openwebui"]["models"].split(",")
        prompt_models.extend([("openwebui", model.strip()) for model in openwebui_models if model.strip()])

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
    config = load_config()
    topic_instruction = ""
    selected_topic = ""
    secondary_topic_instruction = ""
    recent_prompts = list(set(load_recent_prompts()))
    recent_topics = load_recent_topics()

    if topic == "random":
        topics = [t.strip() for t in config["comfyui"]["topics"].split(",") if t.strip()]
        available_topics = [t for t in topics if t not in recent_topics]
        if available_topics:
            selected_topic = random.choice(available_topics)
        elif topics:
            selected_topic = random.choice(topics)
    elif topic != "":
        selected_topic = topic
    else:
        topics = [t.strip() for t in config["comfyui"]["topics"].split(",") if t.strip()]
        available_topics = [t for t in topics if t not in recent_topics]
        if random.random() < 0.3 and available_topics:
            selected_topic = random.choice(available_topics)
        elif random.random() < 0.3 and topics:
            selected_topic = random.choice(topics)

    if selected_topic != "":
        topic_instruction = f" Incorporate the theme of '{selected_topic}' into the new prompt."

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


def _call_prompt_service(service: str, model: str, full_prompt: str):
    if service == "openwebui":
        from libs.openwebui import create_prompt_on_openwebui
        return create_prompt_on_openwebui(full_prompt, "", model)
    elif service == "openrouter":
        from libs.openrouter import create_prompt_on_openrouter
        return create_prompt_on_openrouter(full_prompt, "", model)
    elif service == "ollama":
        from libs.ollama import create_prompt_on_ollama
        return create_prompt_on_ollama(full_prompt, "", model)
    return None


def create_prompt_with_random_model(base_prompt: str, topic: str = "random"):
    prompt_models = load_prompt_models_from_config()

    if not prompt_models:
        logging.warning("No prompt generation models configured.")
        return None, ""

    service, model = random.choice(prompt_models)

    def _fallback_to_other_services(excluded_service, topic, base_prompt):
        other_models = [m for m in prompt_models if m[0] != excluded_service]
        if other_models:
            fb_service, fb_model = random.choice(other_models)
            user_content, selected_topic = build_user_content(topic)
            full_prompt = base_prompt + "\n\n" + user_content
            result = _call_prompt_service(fb_service, fb_model, full_prompt)
            if result is not None:
                return result, selected_topic
        logging.error("No fallback models available (excluded: %s).", excluded_service)
        return "A colorful abstract composition", ""

    if service == "openwebui":
        try:
            logging.info("Attempting to generate prompt with OpenWebUI using model: %s", model)
            user_content, selected_topic = build_user_content(topic)
            full_prompt = base_prompt + "\n\n" + user_content
            result = _call_prompt_service("openwebui", model, full_prompt)
            if result:
                return result, selected_topic

            logging.warning("First OpenWebUI attempt failed. Retrying...")
            result = _call_prompt_service("openwebui", model, full_prompt)
            if result:
                return result, selected_topic

            logging.warning("Second OpenWebUI attempt failed. Falling back to other services...")
            return _fallback_to_other_services("openwebui", topic, base_prompt)

        except Exception as e:
            logging.error("Error with OpenWebUI: %s", e)
            logging.warning("OpenWebUI exception. Falling back to other services...")
            return _fallback_to_other_services("openwebui", topic, base_prompt)

    elif service == "openrouter":
        try:
            user_content, selected_topic = build_user_content(topic)
            full_prompt = base_prompt + "\n\n" + user_content
            return create_prompt_on_openrouter(full_prompt, "", model), selected_topic
        except Exception as e:
            logging.error("Error with OpenRouter: %s", e)
            return _fallback_to_other_services("openrouter", topic, base_prompt)

    elif service == "ollama":
        try:
            user_content, selected_topic = build_user_content(topic)
            full_prompt = base_prompt + "\n\n" + user_content
            return create_prompt_on_ollama(full_prompt, "", model), selected_topic
        except Exception as e:
            logging.error("Error with Ollama: %s", e)
            return _fallback_to_other_services("ollama", topic, base_prompt)


user_config = load_config()
favourites_file = "./favourites.json"


def _get_output_folder():
    return load_config()["comfyui"]["output_dir"]