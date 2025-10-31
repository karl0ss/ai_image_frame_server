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
    topic_instruction = ""
    selected_topic = ""
    secondary_topic_instruction = ""
    # Unique list of recent prompts
    recent_prompts = list(set(load_recent_prompts()))
    if topic == "random":
        topics = [t.strip() for t in config["comfyui"]["topics"].split(",") if t.strip()]
        selected_topic = random.choice(topics)
    elif topic != "":
        selected_topic = topic
    else:
        # Decide on whether to include a topic (e.g., 30% chance to include)
        topics = [t.strip() for t in config["comfyui"]["topics"].split(",") if t.strip()]
        if random.random() < 0.3 and topics:
            selected_topic = random.choice(topics)
    if selected_topic != "":
        topic_instruction = f" Incorporate the theme of '{selected_topic}' into the new prompt."

    # Add secondary topic if configured and not empty
    secondary_topic = config["comfyui"].get("secondary_topic", "").strip()
    if secondary_topic:
        secondary_topic_instruction = f" Additionally incorporate the theme of '{secondary_topic}' into the new prompt, in the style of."

    user_content = (
        "Can you generate me a really random image idea, Do not exceed 20 words. Use clear language, not poetic metaphors."
        + topic_instruction
        + secondary_topic_instruction
        + "Avoid prompts similar to the following:"
        + "\n".join(f"{i+1}. {p}" for i, p in enumerate(recent_prompts))
    )

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