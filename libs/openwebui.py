import logging
from libs.generic import load_config, build_request_content, extract_prompt
from openwebui_chat_client import OpenWebUIClient
from datetime import datetime

logger = logging.getLogger(__name__)


def create_prompt_on_openwebui(base_prompt: str, topic: str | None = "random", model: str = None) -> str:
    config = load_config()
    full_content = build_request_content(base_prompt, topic)

    model = model or config["openwebui"]["models"].split(",")[0].strip()

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