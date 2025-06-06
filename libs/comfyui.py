import random
import logging
import os
import json
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
    workflow_path: str = "./workflow_sdxl.json",
    prompt_node: str = "Positive",
    seed_node: str = "KSampler",
    seed_param: str = "seed",
    save_node: str = "Save Image",
    save_param: str = "filename_prefix",
    model_node: Optional[str] = "Load Checkpoint",
    model_param: Optional[str] = "ckpt_name",
    model: Optional[str] = "None",
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
                if workflow_path.endswith("workflow_sdxl.json")
                else "CR Aspect Ratio"
            ),
            "width",
            user_config["comfyui"]["width"],
        )
        wf.set_node_param(
            (
                "Empty Latent Image"
                if workflow_path.endswith("workflow_sdxl.json")
                else "CR Aspect Ratio"
            ),
            "height",
            user_config["comfyui"]["height"],
        )

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
    
    
def create_image(prompt: str | None = None, model: str = "Random") -> None:
    """Generate an image with a chosen workflow (Random, FLUX*, or SDXL*)."""

    if prompt is None:
        prompt = create_prompt_on_openwebui(user_config["comfyui"]["prompt"])

    if not prompt:
        logging.error("No prompt generated.")
        return

    save_prompt(prompt)
    use_flux  = json.loads(user_config["comfyui"].get("FLUX", "false").lower())
    only_flux = json.loads(user_config["comfyui"].get("ONLY_FLUX", "false").lower())
    if model == "Random":
        selected_workflow = "FLUX" if (use_flux and (only_flux or random.choice([True, False]))) else "SDXL"
    elif "flux" in model.lower(): 
        selected_workflow = "FLUX"
    else:                                   
        selected_workflow = "SDXL"
    if selected_workflow == "FLUX":
        if model == "Random":
            valid_models = user_config["comfyui:flux"]["models"].split(",")
            model = random.choice(valid_models)
        generate_image(
            file_name="image",
            comfy_prompt=prompt,
            workflow_path="./workflow_flux.json",
            prompt_node="Positive Prompt T5",
            seed_node="Seed",
            seed_param="seed",
            save_node="CivitAI Image Saver",
            save_param="filename",
            model_node="Unet Loader (GGUF)",
            model_param="unet_name",
            model=model
        )
    else:  # SDXL
        if model == "Random":
            available_model_list = user_config["comfyui"]["models"].split(",")
            valid_models = list(set(get_available_models()) & set(available_model_list))
            model = random.choice(valid_models)
        generate_image("image", comfy_prompt=prompt, model=model)

    logging.info(f"{selected_workflow} generation started with prompt: {prompt}")

    