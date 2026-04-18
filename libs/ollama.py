import random
import logging
from ollama import Client
from libs.generic import load_recent_prompts, load_config, build_user_content
import re

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
    if user_config["ollama"].get("enabled", "False").lower() != "true":
        return []
    try:
        client = _get_client()
        response = client.list()
        all_models = [m.model for m in response.models]
        return sorted(all_models, key=str.lower)
    except Exception as e:
        logging.warning(f"Failed to fetch models from Ollama Cloud: {e}")
        return []

def create_prompt_on_ollama(prompt: str, topic: str = "random", model: str = None) -> str:
    """Sends prompt to Ollama Cloud and returns the generated response."""
    config = load_config()
    if config["ollama"].get("enabled", "False").lower() != "true":
        logging.warning("Ollama Cloud is not enabled in the configuration.")
        return ""

    user_content, _ = build_user_content(topic)

    configured_models = [m.strip() for m in user_config["ollama"]["models"].split(",") if m.strip()]
    if not configured_models:
        if user_config["ollama"].get("list_all_cloud_models", "False").lower() == "true":
            configured_models = get_cloud_models()
        if not configured_models:
            logging.error("No Ollama Cloud models configured.")
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
                    logging.info(f"Specified model '{original_model}' not found on Ollama Cloud, falling back to: {model}")
                else:
                    model = random.choice(configured_models)
                    logging.warning(f"Specified model '{original_model}' not found, no cloud models available, using random configured model: {model}")
        except Exception as e:
            logging.warning(f"Failed to fetch Ollama Cloud models for validation: {e}. Falling back to configured models.")
            if model not in configured_models:
                model = random.choice(configured_models)
                logging.warning(f"Specified model '{original_model}' not found, using random configured model: {model}")
    else:
        model = random.choice(configured_models)

    system_content = (
        "You are a prompt generator for Stable Diffusion. "
        "Generate a detailed and imaginative prompt with a strong visual theme. "
        "Focus on lighting, atmosphere, and artistic style. "
        "Keep the prompt concise, no extra commentary or formatting."
    )

    try:
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ]
        )
        result = response.message.content.strip('"')
    except Exception as e:
        if "system" in str(e).lower() and ("instruction" in str(e).lower() or "message" in str(e).lower()):
            logging.info(f"Model {model} doesn't support system messages, retrying with instructions in user message")
            combined_content = f"{system_content}\n\n{user_content}"
            try:
                response = client.chat(
                    model=model,
                    messages=[{"role": "user", "content": combined_content}]
                )
                result = response.message.content.strip('"')
            except Exception as e2:
                logging.warning(f"Error with model {model} on retry: {e2}. Trying fallback models.")
                return _try_fallback_models(client, configured_models, model, system_content, user_content)
        else:
            logging.warning(f"Error with model {model}: {e}. Trying fallback models.")
            return _try_fallback_models(client, configured_models, model, system_content, user_content)

    match = re.search(r'"([^"]+)"', result)
    if not match:
        match = re.search(r":\s*\n*\s*(.+)", result)
    if match:
        result = match.group(1)
    logging.debug(result)
    return result


def _try_fallback_models(client, configured_models, failed_model, system_content, user_content):
    """Try up to 3 fallback models when the primary model fails."""
    cloud_models = get_cloud_models()
    all_models = configured_models + cloud_models
    fallback_models = [m for m in all_models if m != failed_model]

    if not fallback_models:
        logging.error("No fallback models available.")
        return ""

    for fallback_model in fallback_models[:3]:
        try:
            logging.info(f"Trying fallback model: {fallback_model}")
            response = client.chat(
                model=fallback_model,
                messages=[{"role": "user", "content": f"{system_content}\n\n{user_content}"}]
            )
            result = response.message.content.strip('"')
            match = re.search(r'"([^"]+)"', result)
            if not match:
                match = re.search(r":\s*\n*\s*(.+)", result)
            if match:
                result = match.group(1)
            logging.info(f"Successfully generated prompt with fallback model: {fallback_model}")
            return result
        except Exception as fallback_e:
            logging.warning(f"Fallback model {fallback_model} also failed: {fallback_e}")
            continue

    logging.error("All models failed, including fallbacks.")
    return ""