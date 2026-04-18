import random
import logging
from ollama import Client
from libs.generic import load_config, build_user_content, extract_prompt, SYSTEM_PROMPT, get_bool

logger = logging.getLogger(__name__)

user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]

def _get_client(config=None):
    cfg = config or user_config
    return Client(
        host='https://ollama.com',
        headers={'Authorization': f'Bearer {cfg["ollama"]["api_key"]}'}
    )

def get_cloud_models():
    """Fetch all available models from Ollama Cloud."""
    if not get_bool(user_config, "ollama", "enabled", False):
        return []
    try:
        client = _get_client()
        response = client.list()
        all_models = [m.model for m in response.models]
        return sorted(all_models, key=str.lower)
    except Exception as e:
        logger.warning("Failed to fetch models from Ollama Cloud: %s", e)
        return []

def create_prompt_on_ollama(base_prompt: str, topic: str = "random", model: str = None) -> str:
    """Sends prompt to Ollama Cloud and returns the generated response."""
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

    if model:
        original_model = model
        try:
            response = client.list()
            all_models = [m.model for m in response.models]
            if model not in all_models:
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

    try:
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": full_content},
            ]
        )
        result = response.message.content.strip('"')
    except Exception as e:
        if "system" in str(e).lower() and ("instruction" in str(e).lower() or "message" in str(e).lower()):
            logger.info("Model %s doesn't support system messages, retrying with instructions in user message", model)
            combined_content = f"{SYSTEM_PROMPT}\n\n{full_content}"
            try:
                response = client.chat(
                    model=model,
                    messages=[{"role": "user", "content": combined_content}]
                )
                result = response.message.content.strip('"')
            except Exception as e2:
                logger.warning("Error with model %s on retry: %s. Trying fallback models.", model, e2)
                return _try_fallback_models(client, configured_models, model, full_content)
        else:
            logger.warning("Error with model %s: %s. Trying fallback models.", model, e)
            return _try_fallback_models(client, configured_models, model, full_content)

    return extract_prompt(result)


def _try_fallback_models(client, configured_models, failed_model, full_content):
    """Try up to 3 fallback models when the primary model fails."""
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