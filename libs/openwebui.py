import random
import logging
from libs.generic import load_config, build_user_content, extract_prompt
from openwebui_chat_client import OpenWebUIClient
from datetime import datetime

logger = logging.getLogger(__name__)

user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]

def create_prompt_on_openwebui(base_prompt: str, topic: str = "random", model: str = None) -> str:
    """Sends prompt to OpenWebUI and returns the generated response."""
    config = load_config()
    user_content, _ = build_user_content(topic)
    if base_prompt:
        full_content = f"{base_prompt}\n\n{user_content}"
    else:
        full_content = user_content

    model = model or random.choice(config["openwebui"]["models"].split(",")).strip()

    client = OpenWebUIClient(
        base_url=config["openwebui"]["base_url"],
        token=config["openwebui"]["api_key"],
        default_model_id=model
    )

    try:
        result = client.chat(
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