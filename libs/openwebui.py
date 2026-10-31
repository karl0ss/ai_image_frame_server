import logging
import random
import time
from libs.generic import load_config, build_request_content, extract_prompt, get_bool
from openwebui_chat_client import OpenWebUIClient
from datetime import datetime

logger = logging.getLogger(__name__)

_ALL_MODELS_CACHE = None
_ALL_MODELS_CACHE_TIME = 0.0
_ALL_MODELS_CACHE_TTL = 300.0


def _get_client(config, model: str) -> OpenWebUIClient:
    return OpenWebUIClient(
        base_url=config["openwebui"]["base_url"].rstrip("/"),
        token=config["openwebui"]["api_key"],
        default_model_id=model
    )


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
        models = _get_client(config, "").list_models()
        if models is None:
            raise RuntimeError("no model list returned")
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


def _chat(config, model: str, full_content: str) -> str | None:
    try:
        result = _get_client(config, model).chat(
            question=full_content,
            chat_title=datetime.now().strftime("%Y-%m-%d %H:%M"),
            folder_name="ai-frame-image-server"
        )

        if result:
            prompt = extract_prompt(result["response"])
            return prompt
        else:
            logger.warning("OpenWebUI request failed with model: %s", model)
            return None
    except Exception as e:
        logger.error("Error in OpenWebUI request with model %s: %s", model, e)
        return None


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
