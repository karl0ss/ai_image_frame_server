import random
import logging
from openai import OpenAI, RateLimitError
from libs.generic import load_config, build_user_content, extract_prompt, SYSTEM_PROMPT, get_bool
from libs.openwebui import create_prompt_on_openwebui

logger = logging.getLogger(__name__)

user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]

def get_free_models():
    """Fetch all free models from OpenRouter."""
    if not get_bool(user_config, "openrouter", "enabled", False):
        return []
    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=user_config["openrouter"]["api_key"],
        )
        all_models_response = client.models.list()
        all_models = [m.id for m in all_models_response.data]
        free_models = [m for m in all_models if "free" in m.lower()]
        return sorted(free_models, key=str.lower)
    except Exception as e:
        logger.warning("Failed to fetch free models from OpenRouter: %s", e)
        return []

def create_prompt_on_openrouter(base_prompt: str, topic: str = "random", model: str = None) -> str:
    """Sends prompt to OpenRouter and returns the generated response."""
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
                    model = random.choice(free_models)
                    logger.info("Specified model '%s' not found on OpenRouter, falling back to free model: %s", original_model, model)
                else:
                    model = random.choice(configured_models)
                    logger.warning("Specified model '%s' not found, no free models available on OpenRouter, using random configured model: %s", original_model, model)
        except Exception as e:
            logger.warning("Failed to fetch OpenRouter models for validation: %s. Falling back to configured models.", e)
            if model not in configured_models:
                free_models = [m for m in configured_models if "free" in m.lower()]
                if free_models:
                    model = random.choice(free_models)
                    logger.info("Specified model '%s' not found, falling back to free configured model: %s", original_model, model)
                else:
                    model = random.choice(configured_models)
                    logger.warning("Specified model '%s' not found, no free configured models available, using random configured model: %s", original_model, model)
    else:
        model = random.choice(configured_models)
    
    try:
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": full_content,
                    },
                ]
            )
        except Exception as e:
            if "developer instruction" in str(e).lower() or "system message" in str(e).lower():
                logger.info("Model %s doesn't support system messages, retrying with instructions in user message", model)
                combined_content = f"{SYSTEM_PROMPT}\n\n{full_content}"
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": combined_content,
                        },
                    ]
                )
            else:
                logger.warning("Error with model %s: %s. Trying fallback models.", model, e)
                raise e

        prompt = extract_prompt(completion.choices[0].message.content)
        logger.debug(prompt)
        return prompt
    except RateLimitError as e:
        logger.warning("OpenRouter rate limit exceeded (429): %s. Falling back to local OpenWebUI model.", e)
        openwebui_models = [m.strip() for m in config["openwebui"]["models"].split(",") if m.strip()] if "openwebui" in config and "models" in config["openwebui"] else []
        if openwebui_models:
            selected_model = random.choice(openwebui_models)
            try:
                return create_prompt_on_openwebui(full_content, topic, selected_model)
            except Exception as e2:
                logger.error("OpenWebUI fallback also failed: %s", e2)
                return "A colorful abstract composition"
        else:
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
                    messages=[
                        {
                            "role": "user",
                            "content": f"{SYSTEM_PROMPT}\n\n{full_content}",
                        },
                    ]
                )
                prompt = extract_prompt(completion.choices[0].message.content)
                logger.info("Successfully generated prompt with fallback model: %s", fallback_model)
                return prompt
            except Exception as fallback_e:
                logger.warning("Fallback model %s also failed: %s", fallback_model, fallback_e)
                continue

        logger.error("All models failed, including fallbacks.")
        return ""