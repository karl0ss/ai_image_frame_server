import configparser
import fcntl
import functools
import hashlib
import hmac
import importlib
import json
import logging
import os
import random
import re
import secrets
import shutil
import sys
import threading
import tomllib
import uuid
from collections import OrderedDict
from datetime import datetime

from PIL import Image
from werkzeug.security import check_password_hash, generate_password_hash

from libs import jobs
from libs.create_thumbnail import generate_thumbnail

logger = logging.getLogger(__name__)

LOG_FILE = "./prompts_log.jsonl"

SYSTEM_PROMPT = (
    "You are a prompt generator for Stable Diffusion. "
    "Generate a detailed and imaginative prompt with a strong visual theme. "
    "Focus on lighting, atmosphere, and artistic style. "
    "Keep the prompt concise, no extra commentary or formatting."
)

ME_PROMPT = (
    "Write one instruction for an image editing model that puts the man from the reference image in one new scene. "
    "Begin with 'Photorealistic photo of the man from the reference image'. If the theme is an art style, "
    "begin with that style instead, such as 'Pixel art of the man from the reference image'. "
    "Make him part of the scene, doing something active or funny, and vary the activity. "
    "Say what he is doing, what he is with and where he is. Never describe his face, hair, beard or age."
)

IDEA_REQUEST = (
    "Can you generate me a really random image idea, Do not exceed 20 words. Use clear language, not poetic metaphors."
)
ME_IDEA_REQUEST = "Write exactly one scene as one sentence, in no more than 25 words. Use clear language, not poetic metaphors."

PROMPT_SERVICES = {
    "openwebui": ("libs.openwebui", "create_prompt_on_openwebui"),
    "openrouter": ("libs.openrouter", "create_prompt_on_openrouter"),
    "ollama": ("libs.ollama", "create_prompt_on_ollama"),
    "freellmapi": ("libs.freellmapi", "create_prompt_on_freellmapi"),
}

_png_details_cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_png_cache_lock = threading.Lock()
_PNG_CACHE_MAX = 256
_PNG_CACHE_TTL = 30.0

_image_write_lock = threading.RLock()


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
                cfg = configparser.ConfigParser(interpolation=None)
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


def load_recent_prompts(count=20):
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
    return generate_password_hash(password)


def verify_password(password: str, stored: str) -> bool:
    """Checks a password against a salted hash, or the older SHA-256 and plain text values."""
    if stored.startswith(("scrypt:", "pbkdf2:")):
        return check_password_hash(stored, password)
    if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored.lower()):
        return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored.lower())
    return hmac.compare_digest(password.encode(), stored.encode())


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

    # This mutates shared state; serialize against concurrent jobs.
    with _image_write_lock:
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
                    _atomic_write(fav_path, json.dumps(favourites))

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


def _atomic_write(filepath: str, data: str) -> None:
    temp_path = filepath + ".tmp"
    with open(temp_path, 'w') as f:
        f.write(data)
    try:
        os.replace(temp_path, filepath)
    except OSError as e:
        if e.errno == 16:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            with open(filepath, 'w') as f:
                f.write(data)
        else:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            raise


def toggle_favourite(filename: str) -> bool:
    """Adds or removes filename under one lock, so concurrent toggles can't lose updates."""
    lock_fd = _acquire_lock(_file_lock_path(favourites_file))
    try:
        favourites = []
        if os.path.exists(favourites_file):
            with open(favourites_file, 'r') as f:
                favourites = json.load(f)
        is_favourited = filename not in favourites
        if is_favourited:
            favourites.append(filename)
        else:
            favourites.remove(filename)
        _atomic_write(favourites_file, json.dumps(favourites))
        return is_favourited
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


def _cache_png_details(path: str, mtime: float, details: dict) -> None:
    with _png_cache_lock:
        _png_details_cache[path] = (mtime, details)
        if len(_png_details_cache) > _PNG_CACHE_MAX:
            _png_details_cache.popitem(last=False)


def get_details_from_png(path):
    empty = {"p": "", "m": "", "d": ""}
    mtime = None
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
                text_val = inputs.get("text", inputs.get("prompt", ""))
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
                        inputs = data[key_node].get("inputs", {})
                        text_val = inputs.get("text", inputs.get("prompt", ""))
                        if isinstance(text_val, str) and text_val:
                            prompt = text_val
                            break
            model = _find_model_from_metadata(data)
            result = {"p": prompt, "m": model, "d": date}

        _cache_png_details(path, mtime, result)
        return result
    except FileNotFoundError:
        return empty
    except Exception as e:
        logger.warning("Error reading metadata from %s: %s", path, e)
        # Cached so a page polling an image without metadata doesn't log this every time.
        _cache_png_details(path, mtime, empty)
        return empty


@functools.lru_cache(maxsize=1)
def get_current_version() -> str:
    try:
        with open(".bumpversion.toml", "rb") as f:
            return tomllib.load(f)["tool"]["bumpversion"]["current_version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as e:
        logger.error("Could not read version: %s", e)
        return "unknown"


def _split_csv(value: str) -> list[str]:
    return sorted([item.strip() for item in value.split(",") if item.strip()], key=str.lower)


def _config_models(config: configparser.ConfigParser, section: str, requires_enabled: bool = True) -> list[str]:
    if section not in config or "models" not in config[section]:
        return []
    if requires_enabled and not get_bool(config, section, "enabled", False):
        return []
    return _split_csv(config[section]["models"])


def load_models_from_config():
    config = load_config()
    sdxl_models = _split_csv(config["comfyui"]["models"])
    optional = [
        _config_models(config, f"comfyui:{key}", requires_enabled=False)
        if get_bool(config, "comfyui", key, False) else []
        for key in ("flux", "qwen", "zimage", "krea", "flux3", "qwen21", "klein")
    ]
    return (sdxl_models, *optional)


def load_me_photos() -> list[str]:
    config = load_config()
    if not get_bool(config, "comfyui:me", "enabled", False):
        return []
    return _split_csv(config.get("comfyui:me", "photos", fallback=""))


def load_topics_from_config():
    return _split_csv(load_config()["comfyui"]["topics"])


def load_prompt_model_groups() -> list[tuple[str, str, list[str]]]:
    """Returns (label, service, models) for every prompt model group that has models."""
    config = load_config()
    groups = [("OpenWebUI", "openwebui", _config_models(config, "openwebui", requires_enabled=False))]
    if get_bool(config, "openwebui", "list_all_models", False):
        from libs.openwebui import get_all_models
        groups.append(("OpenWebUI (All)", "openwebui", get_all_models()))
    groups.append(("OpenRouter", "openrouter", _config_models(config, "openrouter")))
    if get_bool(config, "openrouter", "enabled", False) and get_bool(config, "openrouter", "list_all_free_models", False):
        from libs.openrouter import get_free_models
        groups.append(("OpenRouter Free", "openrouter", get_free_models()))
    groups.append(("Ollama Cloud", "ollama", _config_models(config, "ollama")))
    if get_bool(config, "ollama", "enabled", False) and get_bool(config, "ollama", "list_all_cloud_models", False):
        from libs.ollama import get_cloud_models
        groups.append(("Ollama Cloud (All)", "ollama", get_cloud_models()))
    groups.append(("FreeLLMAPI", "freellmapi", _config_models(config, "freellmapi")))
    return [group for group in groups if group[2]]


def load_prompt_models_from_config() -> list[tuple[str, str]]:
    return [(service, model) for _, service, models in load_prompt_model_groups() for model in models]


def _idea_request(base_prompt: str) -> str:
    return ME_IDEA_REQUEST if base_prompt == ME_PROMPT else IDEA_REQUEST


def build_user_content(
    topic: str = "random", recent_prompts: list[str] | None = None, idea_request: str = IDEA_REQUEST
) -> tuple[str, str]:
    config = load_config()
    topic_instruction = ""
    selected_topic = ""
    secondary_topic_instruction = ""
    if recent_prompts is None:
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
        idea_request
        + topic_instruction
        + secondary_topic_instruction
        + "Avoid prompts similar to the following:"
        + "\n".join(f"{i+1}. {p}" for i, p in enumerate(recent_prompts))
    )

    return user_content, selected_topic


def build_request_content(base_prompt: str, topic: str | None) -> str:
    """Builds the user message for a provider. topic=None means base_prompt is already complete."""
    if topic is None:
        return base_prompt
    user_content, _ = build_user_content(topic, idea_request=_idea_request(base_prompt))
    return f"{base_prompt}\n\n{user_content}" if base_prompt else user_content


def _call_prompt_service(service: str, model: str, prompt: str, topic: str | None = None):
    if service not in PROMPT_SERVICES:
        return None
    module, function = PROMPT_SERVICES[service]
    return getattr(importlib.import_module(module), function)(prompt, topic, model)


def _is_duplicate_prompt(prompt: str, recent_prompts: list[str]) -> bool:
    normalized = prompt.strip().lower().rstrip("\n")
    for rp in recent_prompts:
        if normalized == rp.strip().lower().rstrip("\n"):
            return True
    return False


def try_prompt_service(
    service: str, model: str, prompt: str, topic: str | None = None, attempts: int = 1
) -> str | None:
    for attempt in range(attempts):
        try:
            logging.info("Generating prompt with %s using model: %s", service, model)
            jobs.log_step(f"Prompt model selected: {model} ({service})")
            result = _call_prompt_service(service, model, prompt, topic)
            if result:
                jobs.log_step("Prompt written")
                return result
            logging.warning("%s returned no prompt (attempt %d/%d).", service, attempt + 1, attempts)
            jobs.log_step(f"{service} returned no prompt")
        except Exception as e:
            logging.error("Error with %s: %s", service, e)
            jobs.log_step(f"{service} failed: {e}")
    return None


def _generate_prompt(prompt_models: list, base_prompt: str, topic: str, recent_prompts: list[str]):
    service, model = random.choice(prompt_models)
    user_content, selected_topic = build_user_content(topic, recent_prompts, _idea_request(base_prompt))
    full_prompt = base_prompt + "\n\n" + user_content

    result = try_prompt_service(service, model, full_prompt, attempts=2 if service == "openwebui" else 1)
    if result:
        return result, selected_topic

    other_models = [m for m in prompt_models if m[0] != service]
    if other_models:
        fb_service, fb_model = random.choice(other_models)
        logging.warning("Falling back from %s to %s.", service, fb_service)
        result = try_prompt_service(fb_service, fb_model, full_prompt)
        if result:
            return result, selected_topic

    logging.error("No prompt service produced a result (first tried: %s).", service)
    jobs.log_step("No prompt service worked, using the stock prompt")
    return "A colorful abstract composition", ""


def create_prompt_with_random_model(base_prompt: str, topic: str = "random"):
    jobs.log_step("Fetching the available prompt models")
    prompt_models = load_prompt_models_from_config()

    if not prompt_models:
        logging.warning("No prompt generation models configured.")
        return None, ""

    recent_prompts = list(set(load_recent_prompts()))
    max_attempts = 3

    for attempt in range(max_attempts):
        result, selected_topic = _generate_prompt(prompt_models, base_prompt, topic, recent_prompts)
        if result and not _is_duplicate_prompt(result, recent_prompts):
            return result, selected_topic
        if attempt < max_attempts - 1:
            logging.warning("Generated duplicate prompt (attempt %d/%d), retrying...", attempt + 1, max_attempts)
            jobs.log_step("That prompt was a repeat, trying again")

    logging.warning("All %d attempts produced duplicate prompts.", max_attempts)
    return None, ""


user_config = load_config()
favourites_file = "./favourites.json"


def load_secret_key() -> str:
    """Returns SECRET_KEY, or a key kept on the output volume so logins survive a restart."""
    secret_key = os.environ.get("SECRET_KEY")
    if secret_key:
        return secret_key
    path = os.path.join(load_config()["comfyui"]["output_dir"], ".secret_key")
    try:
        with open(path) as f:
            secret_key = f.read().strip()
    except FileNotFoundError:
        secret_key = ""
    if not secret_key:
        secret_key = secrets.token_hex(32)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(secret_key)
    return secret_key


def _selected_image_path() -> str:
    # Kept beside the images because output/ is the volume that survives a container recreate.
    return os.path.join(load_config()["comfyui"]["output_dir"], "selected_image.json")


def get_selected_image() -> str | None:
    selected_image_file = _selected_image_path()
    if not os.path.exists(selected_image_file):
        return None
    try:
        with open(selected_image_file, "r") as f:
            data = json.load(f)
            return data.get("filename") or None
    except (json.JSONDecodeError, OSError):
        return None


def set_selected_image(filename: str | None) -> None:
    selected_image_file = _selected_image_path()
    if filename is None:
        if os.path.exists(selected_image_file):
            os.remove(selected_image_file)
        return
    _atomic_write(selected_image_file, json.dumps({"filename": filename}))


def _get_output_folder():
    return load_config()["comfyui"]["output_dir"]