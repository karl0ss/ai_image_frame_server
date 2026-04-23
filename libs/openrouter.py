import logging
import random
import time
from openai import OpenAI, RateLimitError
from libs.generic import load_config, build_user_content, extract_prompt, SYSTEM_PROMPT, get_bool

logger = logging.getLogger(__name__)

_FREE_MODELS_CACHE = None
_FREE_MODELS_CACHE_TIME = 0.0
_FREE_MODELS_CACHE_TTL = 300.0


def get_free_models():
    global _FREE_MODELS_CACHE, _FREE_MODELS_CACHE_TIME

    if _FREE_MODELS_CACHE is not None and (time.time() - _FREE_MODELS_CACHE_TIME) < _FREE_MODELS_CACHE_TTL:
        return _FREE_MODELS_CACHE

    config = load_config()
    if not get_bool(config, "openrouter", "enabled", False):
        return []
    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=config["openrouter"]["api_key"],
        )
        all_models_response = client.models.list()
        all_models = [m.id for m in all_models_response.data]
        free_models = sorted([m for m in all_models if "free" in m.lower()], key=str.lower)
        _FREE_MODELS_CACHE = free_models
        _FREE_MODELS_CACHE_TIME = time.time()
        return free_models
    except Exception as e:
        logger.warning("Failed to fetch free models from OpenRouter: %s", e)
        if _FREE_MODELS_CACHE is not None:
            return _FREE_MODELS_CACHE
        return []


def _create_completion_with_fallback(client, model, full_content):
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": full_content},
            ]
        )
        return completion
    except Exception as e:
        err_lower = str(e).lower()
        if "developer instruction" in err_lower or "system message" in err_lower:
            logger.info("Model %s doesn't support system messages, retrying with instructions in user message", model)
            return client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{full_content}"}]
            )
        raise


def create_prompt_on_openrouter(base_prompt: str, topic: str = "random", model: str = None) -> str:
    config = load_config()
    if not get_bool(config, "openrouter", "enabled", False):
        logger.warning("OpenRouter is not enabled in the configuration.")
        return ""

    user_content, _ = build_user_content(topic)
    full_content = f"{base_prompt}\n\n{user_content}" if base_prompt else user_content

    configured_models = [m.strip() for m in config["openrouter"]["models"].split(",") if m.strip()]
    if not configured_models:
        if get_bool(config, "openrouter", "list_all_free_models", False):
            configured_models = get_free_models()
        if not configured_models:
            logger.error("No OpenRouter models configured.")
            return ""

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config["openrouter"]["api_key"],
    )

    if model:
        original_model = model
        try:
            all_models_response = client.models.list()
            all_models = [m.id for m in all_models_response.data]
            if model not in all_models:
                free_models = [m for m in all_models if "free" in m.lower()]
                if free_models:
                    model = free_models[0]
                    logger.info("Specified model '%s' not found on OpenRouter, falling back to free model: %s", original_model, model)
                else:
                    model = random.choice(configured_models)
                    logger.warning("Specified model '%s' not found, no free models available on OpenRouter, using random configured model: %s", original_model, model)
        except Exception as e:
            logger.warning("Failed to fetch OpenRouter models for validation: %s. Falling back to configured models.", e)
            if model not in configured_models:
                free_models = [m for m in configured_models if "free" in m.lower()]
                if free_models:
                    model = free_models[0]
                    logger.info("Specified model '%s' not found, falling back to free configured model: %s", original_model, model)
                else:
                    model = random.choice(configured_models)
                    logger.warning("Specified model '%s' not found, no free configured models available, using random configured model: %s", original_model, model)
    else:
        model = random.choice(configured_models)

    try:
        completion = _create_completion_with_fallback(client, model, full_content)
        prompt = extract_prompt(completion.choices[0].message.content)
        logger.debug(prompt)
        return prompt
    except RateLimitError as e:
        logger.warning("OpenRouter rate limit exceeded (429): %s. Falling back to local OpenWebUI model.", e)
        if "openwebui" in config and "models" in config["openwebui"]:
            from libs.openwebui import create_prompt_on_openwebui
            openwebui_models = [m.strip() for m in config["openwebui"]["models"].split(",") if m.strip()]
            if openwebui_models:
                selected_model = random.choice(openwebui_models)
                try:
                    return create_prompt_on_openwebui(full_content, topic, selected_model)
                except Exception as e2:
                    logger.error("OpenWebUI fallback also failed: %s", e2)
                    return "A colorful abstract composition"
        logger.error("No OpenWebUI models configured for fallback.")
        return "A colorful abstract composition"
    except Exception as e:
        logger.warning("Primary model %s failed: %s. Trying fallback models.", model, e)

        fallback_configured = [m.strip() for m in config["openrouter"]["models"].split(",") if m.strip()]
        free_models = get_free_models()
        all_models = fallback_configured + free_models
        fallback_models = [m for m in all_models if m != model]

        if not fallback_models:
            logger.error("No fallback models available.")
            return ""

        for fallback_model in fallback_models[:3]:
            try:
                logger.info("Trying fallback model: %s", fallback_model)
                completion = client.chat.completions.create(
                    model=fallback_model,
                    messages=[{"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{full_content}"}]
                )
                prompt = extract_prompt(completion.choices[0].message.content)
                logger.info("Successfully generated prompt with fallback model: %s", fallback_model)
                return prompt
            except Exception as fallback_e:
                logger.warning("Fallback model %s also failed: %s", fallback_model, fallback_e)
                continue

        logger.error("All models failed, including fallbacks.")
        return ""