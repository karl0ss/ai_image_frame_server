import random
import logging
from openai import OpenAI, RateLimitError
import nest_asyncio
from libs.generic import load_recent_prompts, load_config
from libs.openwebui import create_prompt_on_openwebui
import re
nest_asyncio.apply()

logging.basicConfig(level=logging.INFO)

LOG_FILE = "./prompts_log.jsonl"

user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]

def get_free_models():
    """Fetch all free models from OpenRouter."""
    if user_config["openrouter"].get("enabled", "False").lower() != "true":
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
        logging.warning(f"Failed to fetch free models from OpenRouter: {e}")
        return []

def create_prompt_on_openrouter(prompt: str, topic: str = "random", model: str = None) -> str:
    """Sends prompt to OpenRouter and returns the generated response."""
    # Check if OpenRouter is enabled
    if user_config["openrouter"].get("enabled", "False").lower() != "true":
        logging.warning("OpenRouter is not enabled in the configuration.")
        return ""
    
    topic_instruction = ""
    selected_topic = ""
    # Unique list of recent prompts
    recent_prompts = list(set(load_recent_prompts()))
    if topic == "random":
        topics = [t.strip() for t in user_config["comfyui"]["topics"].split(",") if t.strip()]
        selected_topic = random.choice(topics) if topics else ""
    elif topic != "":
        selected_topic = topic
    else:
        # Decide on whether to include a topic (e.g., 30% chance to include)
        topics = [t.strip() for t in user_config["comfyui"]["topics"].split(",") if t.strip()]
        if random.random() < 0.3 and topics:
            selected_topic = random.choice(topics)
    if selected_topic != "":
        topic_instruction = f" Incorporate the theme of '{selected_topic}' into the new prompt."

    user_content = (
        "Can you generate me a really random image idea, Do not exceed 10 words. Use clear language, not poetic metaphors."
        + topic_instruction
        + "Avoid prompts similar to the following:"
        + "\n".join(f"{i+1}. {p}" for i, p in enumerate(recent_prompts))
    )

    # Load configured models
    configured_models = [m.strip() for m in user_config["openrouter"]["models"].split(",") if m.strip()]
    if not configured_models:
        logging.error("No OpenRouter models configured.")
        return ""

    # Create client early for model checking
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=user_config["openrouter"]["api_key"],
    )

    # Select model
    if model:
        original_model = model
        # Always check if model exists on OpenRouter
        try:
            all_models_response = client.models.list()
            all_models = [m.id for m in all_models_response.data]
            if model not in all_models:
                # Fallback to random free model from all OpenRouter models
                free_models = [m for m in all_models if "free" in m.lower()]
                if free_models:
                    model = random.choice(free_models)
                    logging.info(f"Specified model '{original_model}' not found on OpenRouter, falling back to free model: {model}")
                else:
                    # No free models, fallback to random configured model
                    model = random.choice(configured_models)
                    logging.warning(f"Specified model '{original_model}' not found, no free models available on OpenRouter, using random configured model: {model}")
            # else model exists, use it
        except Exception as e:
            logging.warning(f"Failed to fetch OpenRouter models for validation: {e}. Falling back to configured models.")
            if model not in configured_models:
                # Fallback to random free from configured
                free_models = [m for m in configured_models if "free" in m.lower()]
                if free_models:
                    model = random.choice(free_models)
                    logging.info(f"Specified model '{original_model}' not found, falling back to free configured model: {model}")
                else:
                    model = random.choice(configured_models)
                    logging.warning(f"Specified model '{original_model}' not found, no free configured models available, using random configured model: {model}")
            # else use the specified model
    else:
        model = random.choice(configured_models)
    
    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=user_config["openrouter"]["api_key"],
        )

        system_content = (
            "You are a prompt generator for Stable Diffusion. "
            "Generate a detailed and imaginative prompt with a strong visual theme. "
            "Focus on lighting, atmosphere, and artistic style. "
            "Keep the prompt concise, no extra commentary or formatting."
        )

        # Try the specified model first
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": system_content,
                    },
                    {
                        "role": "user",
                        "content": user_content,
                    },
                ]
            )
        except Exception as e:
            # If system message fails (e.g., model doesn't support developer instructions),
            # retry with instructions included in user message
            if "developer instruction" in str(e).lower() or "system message" in str(e).lower():
                logging.info(f"Model {model} doesn't support system messages, retrying with instructions in user message")
                combined_content = f"{system_content}\n\n{user_content}"
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
                # If it's another error, try fallback models
                logging.warning(f"Error with model {model}: {e}. Trying fallback models.")
                raise e

        # If we get here, the completion was successful

        prompt = completion.choices[0].message.content.strip('"')
        match = re.search(r'"([^"]+)"', prompt)
        if not match:
            match = re.search(r":\s*\n*\s*(.+)", prompt)
        if match:
            prompt = match.group(1)
        logging.debug(prompt)
        return prompt
    except RateLimitError as e:
        logging.warning(f"OpenRouter rate limit exceeded (429): {e}. Falling back to local OpenWebUI model.")
        # Try to use OpenWebUI as fallback
        openwebui_models = [m.strip() for m in user_config["openwebui"]["models"].split(",") if m.strip()] if "openwebui" in user_config and "models" in user_config["openwebui"] else []
        if openwebui_models:
            selected_model = random.choice(openwebui_models)
            try:
                return create_prompt_on_openwebui(user_content, topic, selected_model)
            except Exception as e2:
                logging.error(f"OpenWebUI fallback also failed: {e2}")
                return "A colorful abstract composition"  # Final fallback
        else:
            logging.error("No OpenWebUI models configured for fallback.")
            return "A colorful abstract composition"  # Final fallback
    except Exception as e:
        # If the specified model fails, try fallback models
        logging.warning(f"Primary model {model} failed: {e}. Trying fallback models.")

        # Get all available models for fallback
        configured_models = [m.strip() for m in user_config["openrouter"]["models"].split(",") if m.strip()]
        free_models = get_free_models()

        # Combine configured and free models, excluding the failed one
        all_models = configured_models + free_models
        fallback_models = [m for m in all_models if m != model]

        if not fallback_models:
            logging.error("No fallback models available.")
            return ""

        # Try up to 3 fallback models
        for fallback_model in fallback_models[:3]:
            try:
                logging.info(f"Trying fallback model: {fallback_model}")
                completion = client.chat.completions.create(
                    model=fallback_model,
                    messages=[
                        {
                            "role": "user",
                            "content": f"{system_content}\n\n{user_content}",
                        },
                    ]
                )
                prompt = completion.choices[0].message.content.strip('"')
                match = re.search(r'"([^"]+)"', prompt)
                if not match:
                    match = re.search(r":\s*\n*\s*(.+)", prompt)
                if match:
                    prompt = match.group(1)
                logging.info(f"Successfully generated prompt with fallback model: {fallback_model}")
                return prompt
            except Exception as fallback_e:
                logging.warning(f"Fallback model {fallback_model} also failed: {fallback_e}")
                continue

        logging.error("All models failed, including fallbacks.")
        return ""