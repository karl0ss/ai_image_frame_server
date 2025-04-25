import random
import logging
import os
import requests
from typing import Optional
from comfy_api_simplified import ComfyApiWrapper, ComfyWorkflowWrapper
from tenacity import (
    retry,
    stop_after_attempt,
    wait_fixed,
    before_log,
    retry_if_exception_type,
)
import nest_asyncio
from libs.generic import rename_image, load_config, save_prompt
from libs.create_thumbnail import generate_thumbnail
from libs.ollama import create_prompt_on_openwebui
nest_asyncio.apply()

logging.basicConfig(level=logging.INFO)

LOG_FILE = "./prompts_log.jsonl"

user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]


def get_available_models() -> list:
    """Fetches available models from ComfyUI."""
    url = user_config["comfyui"]["comfyui_url"] + "/object_info"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return (
            data.get("CheckpointLoaderSimple", {})
            .get("input", {})
            .get("required", {})
            .get("ckpt_name", [])[0]
        )
    else:
        print(f"Failed to fetch models: {response.status_code}")
        return []


def cancel_current_job() -> list:
    """Fetches available models from ComfyUI."""
    url = user_config["comfyui"]["comfyui_url"] + "/interrupt"
    response = requests.post(url)
    if response.status_code == 200:
        return "Cancelled"
    else:
        return "Failed to cancel"


# Define the retry logic using Tenacity
@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(5),
    before=before_log(logging.getLogger(), logging.DEBUG),
    retry=retry_if_exception_type(Exception),
)
def generate_image(
    file_name: str,
    comfy_prompt: str,
    workflow_path: str = "./workflow_api.json",
    prompt_node: str = "CLIP Text Encode (Prompt)",
    seed_node: str = "KSampler",
    seed_param: str = "seed",
    save_node: str = "Save Image",
    save_param: str = "filename_prefix",
    model_node: Optional[str] = "Load Checkpoint",
    model_param: Optional[str] = "ckpt_name",
) -> None:
    """Generates an image using the Comfy API with configurable workflow settings."""
    try:
        api = ComfyApiWrapper(user_config["comfyui"]["comfyui_url"])
        wf = ComfyWorkflowWrapper(workflow_path)

        # Set workflow parameters
        wf.set_node_param(seed_node, seed_param, random.getrandbits(32))
        wf.set_node_param(prompt_node, "text", comfy_prompt)
        wf.set_node_param(save_node, save_param, file_name)
        wf.set_node_param(
            (
                "Empty Latent Image"
                if workflow_path.endswith("workflow_api.json")
                else "CR Aspect Ratio"
            ),
            "width",
            user_config["comfyui"]["width"],
        )
        wf.set_node_param(
            (
                "Empty Latent Image"
                if workflow_path.endswith("workflow_api.json")
                else "CR Aspect Ratio"
            ),
            "height",
            user_config["comfyui"]["height"],
        )

        # Conditionally set model if node and param are provided
        if model_node and model_param:
            if user_config["comfyui"].get("FLUX"):
                valid_models = user_config["comfyui:flux"]["models"].split(",")
            else:
                available_model_list = user_config["comfyui"]["models"].split(",")
                valid_models = list(
                    set(get_available_models()) & set(available_model_list)
                )

                if not valid_models:
                    raise Exception("No valid models available.")

            model = random.choice(valid_models)
            wf.set_node_param(model_node, model_param, model)

        # Generate image
        logging.debug(f"Generating image: {file_name}")
        results = api.queue_and_wait_images(wf, save_node)
        rename_image()

        for _, image_data in results.items():
            output_path = os.path.join(
                user_config["comfyui"]["output_dir"], f"{file_name}.png"
            )
            with open(output_path, "wb+") as f:
                f.write(image_data)
            generate_thumbnail(output_path)

        logging.debug(f"Image generated successfully for UID: {file_name}")

    except Exception as e:
        logging.error(f"Failed to generate image for UID: {file_name}. Error: {e}")
        raise
    
    
def create_image(prompt: str | None = None) -> None:
    """Main function for generating images."""
    if prompt is None:
        prompt = create_prompt_on_openwebui(user_config["comfyui"]["prompt"])
    if prompt:
        logging.info(f"Generated prompt: {prompt}")  # Log generated prompt
        save_prompt(prompt)
        if user_config["comfyui"]["FLUX"]:
            generate_image(
                file_name="image",
                comfy_prompt=prompt,
                workflow_path="./FLUX.json",
                prompt_node="Positive Prompt T5",
                seed_node="Seed",
                seed_param="seed",
                save_node="CivitAI Image Saver",
                save_param="filename",
                model_node="CivitAI Image Saver",
                model_param="modelname",
            )
        else:
            generate_image("image", prompt)
        print(f"Image generation started with prompt: {prompt}")
    else:
        logging.error("No prompt generated.")
    