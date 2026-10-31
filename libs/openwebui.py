import logging
import random
import time
import uuid
from datetime import datetime

import requests

from libs.generic import load_config, build_request_content, extract_prompt, SYSTEM_PROMPT, get_bool

logger = logging.getLogger(__name__)

LLM_TIMEOUT = 300
MODELS_TIMEOUT = 15
CHAT_FOLDER = "ai-frame-image-server"

_ALL_MODELS_CACHE = None
_ALL_MODELS_CACHE_TIME = 0.0
_ALL_MODELS_CACHE_TTL = 300.0


def _request(config, method: str, path: str, timeout: int, **kwargs) -> dict:
    response = requests.request(
        method,
        config["openwebui"]["base_url"].rstrip("/") + path,
        headers={"Authorization": f'Bearer {config["openwebui"]["api_key"]}'},
        timeout=timeout,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


def _can_chat(model_id: str) -> bool:
    return "embed" not in model_id.lower() and model_id != "arena-model"


def get_all_models():
    global _ALL_MODELS_CACHE, _ALL_MODELS_CACHE_TIME

    if _ALL_MODELS_CACHE is not None and (time.time() - _ALL_MODELS_CACHE_TIME) < _ALL_MODELS_CACHE_TTL:
        return _ALL_MODELS_CACHE

    config = load_config()
    if not get_bool(config, "openwebui", "list_all_models", False):
        return []
    try:
        models = _request(config, "GET", "/api/models", MODELS_TIMEOUT)["data"]
        result = sorted([m["id"] for m in models if _can_chat(m["id"])], key=str.lower)
        _ALL_MODELS_CACHE = result
        _ALL_MODELS_CACHE_TIME = time.time()
        return result
    except Exception as e:
        logger.warning("Failed to fetch models from OpenWebUI: %s", e)
        if _ALL_MODELS_CACHE is not None:
            return _ALL_MODELS_CACHE
        return []


def get_usable_models(config) -> list[str]:
    configured_models = [m.strip() for m in config["openwebui"].get("models", "").split(",") if m.strip()]
    if not configured_models and get_bool(config, "openwebui", "list_all_models", False):
        return get_all_models()
    return configured_models


def _folder_id(config) -> str:
    for folder in _request(config, "GET", "/api/v1/folders/", MODELS_TIMEOUT):
        if folder["name"] == CHAT_FOLDER:
            return folder["id"]
    return _request(config, "POST", "/api/v1/folders/", MODELS_TIMEOUT, json={"name": CHAT_FOLDER})["id"]


def _save_chat(config, model: str, question: str, answer: str) -> None:
    """Records the exchange in OpenWebUI. A failure here must not cost us the prompt."""
    try:
        title = datetime.now().strftime("%Y-%m-%d %H:%M")
        timestamp = int(time.time())
        user_id, reply_id = str(uuid.uuid4()), str(uuid.uuid4())
        user_message = {
            "id": user_id, "parentId": None, "childrenIds": [reply_id], "role": "user",
            "content": question, "models": [model], "timestamp": timestamp,
        }
        reply = {
            "id": reply_id, "parentId": user_id, "childrenIds": [], "role": "assistant",
            "content": answer, "model": model, "modelName": model, "done": True, "timestamp": timestamp,
        }
        _request(config, "POST", "/api/v1/chats/new", MODELS_TIMEOUT, json={
            "folder_id": _folder_id(config),
            "chat": {
                "title": title,
                "models": [model],
                "messages": [user_message, reply],
                "history": {"currentId": reply_id, "messages": {user_id: user_message, reply_id: reply}},
            },
        })
    except Exception as e:
        logger.warning("Could not save the prompt chat to OpenWebUI: %s", e)


def _chat(config, model: str, full_content: str) -> str | None:
    question = f"{SYSTEM_PROMPT}\n\n{full_content}"
    try:
        data = _request(config, "POST", "/api/chat/completions", LLM_TIMEOUT, json={
            "model": model,
            "stream": False,
            "messages": [{"role": "user", "content": question}],
        })
        answer = data["choices"][0]["message"]["content"]
        prompt = extract_prompt(answer) or None
    except Exception as e:
        logger.warning("OpenWebUI request failed with model %s: %s", model, e)
        return None
    if prompt:
        _save_chat(config, model, question, answer)
    return prompt


def _try_fallback_models(config, configured_models, failed_model, full_content):
    all_models = set(configured_models) | set(get_all_models())
    fallback_models = sorted(all_models - {failed_model})

    if not fallback_models:
        return None

    for fallback_model in random.sample(fallback_models, min(3, len(fallback_models))):
        logger.info("Trying fallback model: %s", fallback_model)
        prompt = _chat(config, fallback_model, full_content)
        if prompt:
            logger.info("Successfully generated prompt with fallback model: %s", fallback_model)
            return prompt

    logger.error("All OpenWebUI models failed, including fallbacks.")
    return None


def create_prompt_on_openwebui(base_prompt: str, topic: str | None = "random", model: str = None) -> str:
    config = load_config()
    full_content = build_request_content(base_prompt, topic)

    configured_models = get_usable_models(config)
    if not configured_models:
        logger.error("No OpenWebUI models configured.")
        return None

    model = model or random.choice(configured_models)

    return _chat(config, model, full_content) or _try_fallback_models(config, configured_models, model, full_content)
