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

    # Use the specified model or select a random model from the configured OpenRouter models
    if model:
        # Use the specified model
        model = model
    else:
        # Select a random model from the configured OpenRouter models
        models = [m.strip() for m in user_config["openrouter"]["models"].split(",") if m.strip()]
        if not models:
            logging.error("No OpenRouter models configured.")
            return ""
        
        model = random.choice(models)
    
    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=user_config["openrouter"]["api_key"],
        )

        completion = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a prompt generator for Stable Diffusion. "
                        "Generate a detailed and imaginative prompt with a strong visual theme. "
                        "Focus on lighting, atmosphere, and artistic style. "
                        "Keep the prompt concise, no extra commentary or formatting."
                    ),
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ]
        )

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
        logging.error(f"Error generating prompt with OpenRouter: {e}")
        return ""