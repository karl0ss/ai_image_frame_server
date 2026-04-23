import logging
import random
import time
from libs.generic import load_config, build_user_content, extract_prompt, SYSTEM_PROMPT, get_bool

logger = logging.getLogger(__name__)

_CLOUD_MODELS_CACHE = None
_CLOUD_MODELS_CACHE_TIME = 0.0
_CLOUD_MODELS_CACHE_TTL = 300.0


def _get_client(config=None):
    from ollama import Client
    cfg = config or load_config()
    return Client(
        host='https://ollama.com',
        headers={'Authorization': f'Bearer {cfg["ollama"]["api_key"]}'}
    )


def get_cloud_models():
    global _CLOUD_MODELS_CACHE, _CLOUD_MODELS_CACHE_TIME

    if _CLOUD_MODELS_CACHE is not None and (time.time() - _CLOUD_MODELS_CACHE_TIME) < _CLOUD_MODELS_CACHE_TTL:
        return _CLOUD_MODELS_CACHE

    config = load_config()
    if not get_bool(config, "ollama", "enabled", False):
        return []
    try:
        client = _get_client(config)
        response = client.list()
        all_models = [m.model for m in response.models]
        result = sorted(all_models, key=str.lower)
        _CLOUD_MODELS_CACHE = result
        _CLOUD_MODELS_CACHE_TIME = time.time()
        return result
    except Exception as e:
        logger.warning("Failed to fetch models from Ollama Cloud: %s", e)
        if _CLOUD_MODELS_CACHE is not None:
            return _CLOUD_MODELS_CACHE
        return []


def _compute_effective_model(model, configured_models, client=None):
    if model:
        original_model = model
        try:
            if client:
                response = client.list()
                all_models = [m.model for m in response.models]
            else:
                all_models = None

            if all_models and model not in all_models:
                if all_models:
                    model = random.choice(all_models)
                    logger.info("Specified model '%s' not found on Ollama Cloud, falling back to: %s", original_model, model)
                else:
                    model = random.choice(configured_models)
                    logger.warning("Specified model '%s' not found, no cloud models available, using random configured model: %s", original_model, model)
        except Exception as e:
            logger.warning("Failed to fetch Ollama Cloud models for validation: %s. Falling back to configured models.", e)
            if model not in configured_models:
                model = random.choice(configured_models)
                logger.warning("Specified model '%s' not found, using random configured model: %s", original_model, model)
    else:
        model = random.choice(configured_models)
    return model


def _chat_with_fallback(client, model, full_content, configured_models):
    try:
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": full_content},
            ]
        )
        return extract_prompt(response.message.content)
    except Exception as e:
        if "system" in str(e).lower() and ("instruction" in str(e).lower() or "message" in str(e).lower()):
            logger.info("Model %s doesn't support system messages, retrying with instructions in user message", model)
            try:
                response = client.chat(
                    model=model,
                    messages=[{"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{full_content}"}]
                )
                return extract_prompt(response.message.content)
            except Exception as e2:
                logger.warning("Error with model %s on retry: %s. Trying fallback models.", model, e2)
                return _try_fallback_models(client, configured_models, model, full_content)
        else:
            logger.warning("Error with model %s: %s. Trying fallback models.", model, e)
            return _try_fallback_models(client, configured_models, model, full_content)


def create_prompt_on_ollama(base_prompt: str, topic: str = "random", model: str = None) -> str:
    config = load_config()
    if not get_bool(config, "ollama", "enabled", False):
        logger.warning("Ollama Cloud is not enabled in the configuration.")
        return ""

    user_content, _ = build_user_content(topic)
    full_content = f"{base_prompt}\n\n{user_content}" if base_prompt else user_content

    configured_models = [m.strip() for m in config["ollama"]["models"].split(",") if m.strip()]
    if not configured_models:
        if get_bool(config, "ollama", "list_all_cloud_models", False):
            configured_models = get_cloud_models()
        if not configured_models:
            logger.error("No Ollama Cloud models configured.")
            return ""

    client = _get_client(config)
    model = _compute_effective_model(model, configured_models, client)

    return _chat_with_fallback(client, model, full_content, configured_models)


def _try_fallback_models(client, configured_models, failed_model, full_content):
    cloud_models = get_cloud_models()
    all_models = configured_models + cloud_models
    fallback_models = [m for m in all_models if m != failed_model]

    if not fallback_models:
        logger.error("No fallback models available.")
        return ""

    for fallback_model in fallback_models[:3]:
        try:
            logger.info("Trying fallback model: %s", fallback_model)
            response = client.chat(
                model=fallback_model,
                messages=[{"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{full_content}"}]
            )
            result = extract_prompt(response.message.content)
            logger.info("Successfully generated prompt with fallback model: %s", fallback_model)
            return result
        except Exception as fallback_e:
            logger.warning("Fallback model %s also failed: %s", fallback_model, fallback_e)
            continue

    logger.error("All models failed, including fallbacks.")
    return ""