import random
import logging
import nest_asyncio
from libs.generic import load_recent_prompts, load_config
import re
from openwebui_chat_client import OpenWebUIClient
from datetime import datetime

nest_asyncio.apply()

logging.basicConfig(level=logging.INFO)

LOG_FILE = "./prompts_log.jsonl"

user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]

def create_prompt_on_openwebui(prompt: str, topic: str = "random", model: str = None) -> str:
    """Sends prompt to OpenWebui and returns the generated response."""
    # Reload config to get latest values
    config = load_config()
    user_content = build_user_content(topic)

    if model:
        # Use the specified model
        model = model
    else:
        # Select a random model
        model = random.choice(user_config["openwebui"]["models"].split(",")).strip()

    # Create OpenWebUI client
    client = OpenWebUIClient(
        base_url=user_config["openwebui"]["base_url"],
        token=user_config["openwebui"]["api_key"],
        default_model_id=model
    )

    # Prepare messages for the chat
    messages = [
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

    # Send the chat request
    try:
        result = client.chat(
            question=user_content,
            chat_title=datetime.now().strftime("%Y-%m-%d %H:%M"),
            folder_name="ai-frame-image-server"
        )

        if result:
            prompt = result["response"].strip('"')
        else:
            # Return None if the request fails
            logging.warning(f"OpenWebUI request failed with model: {model}")
            return None
    except Exception as e:
        logging.error(f"Error in OpenWebUI request with model {model}: {e}")
        return None

    match = re.search(r'"([^"]+)"', prompt)
    if not match:
        match = re.search(r":\s*\n*\s*(.+)", prompt) 
    if match:
        prompt = match.group(1)
    logging.debug(prompt)
    return prompt