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
from libs.openwebui import create_prompt_on_openwebui
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
        # Get SDXL models from CheckpointLoaderSimple
        general = data.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
        # Get FLUX models from UnetLoaderGGUF
        flux = data.get("UnetLoaderGGUF", {}).get("input", {}).get("required", {}).get("unet_name", [[]])[0]
        # Combine both lists, handling cases where one might be missing
        all_models = []
        if isinstance(general, list):
            all_models.extend(general)
        if isinstance(flux, list):
            all_models.extend(flux)
        return all_models
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

def select_model(model: str) -> tuple[str, str]:
    use_flux = json.loads(user_config["comfyui"].get("FLUX", "false").lower())
    only_flux = json.loads(user_config["comfyui"].get("ONLY_FLUX", "false").lower())
    use_qwen = json.loads(user_config["comfyui"].get("Qwen", "false").lower())

    if model == "Random Image Model":
        # Create a list of available workflows based on configuration
        available_workflows = []
        if not only_flux:
            available_workflows.append("SDXL")
        if use_flux:
            available_workflows.append("FLUX")
        if use_qwen:
            available_workflows.append("Qwen")
        
        # If no workflows are available, default to SDXL
        if not available_workflows:
            available_workflows.append("SDXL")
        
        # Randomly select a workflow
        selected_workflow = random.choice(available_workflows)
    elif "flux" in model.lower():
        selected_workflow = "FLUX"
    elif "qwen" in model.lower():
        selected_workflow = "Qwen"
    else:
        selected_workflow = "SDXL"

    if model == "Random Image Model":
        if selected_workflow == "FLUX":
            valid_models = user_config["comfyui:flux"]["models"].split(",")
        elif selected_workflow == "Qwen":
            valid_models = user_config["comfyui:qwen"]["models"].split(",")
        else:  # SDXL
            available_model_list = user_config["comfyui"]["models"].split(",")
            valid_models = list(set(get_available_models()) & set(available_model_list))
            # If no valid models found, fall back to configured models
            if not valid_models:
                valid_models = available_model_list
        # Ensure we have at least one model to choose from
        if not valid_models:
            # Fallback to a default model
            valid_models = ["zavychromaxl_v100.safetensors"]
        model = random.choice(valid_models)

    return selected_workflow, model


def create_image(prompt: str | None = None, model: str = "Random Image Model") -> None:
    """Generate an image with a chosen workflow (Random, FLUX*, or SDXL*)."""

    if prompt is None:
        # Generate a random prompt using either OpenWebUI or OpenRouter
        from libs.generic import create_prompt_with_random_model
        prompt = create_prompt_with_random_model("Generate a random detailed prompt for stable diffusion.")
        if not prompt:
            logging.error("Failed to generate a prompt.")
            return

    if not prompt:
        logging.error("No prompt generated.")
        return

    save_prompt(prompt)
    selected_workflow, model = select_model(model)
    
    if selected_workflow == "FLUX":
        generate_image(
            file_name="image",
            comfy_prompt=prompt,
            workflow_path="./workflow_flux.json",
            prompt_node="CLIP Text Encode (Positive Prompt)",
            seed_node="RandomNoise",
            seed_param="noise_seed",
            save_node="Save Image",
            save_param="filename_prefix",
            model_node="UnetLoaderGGUFDisTorchMultiGPU",
            model_param="unet_name",
            model=model
        )
    elif selected_workflow == "Qwen":
        generate_image(
            file_name="image",
            comfy_prompt=prompt,
            workflow_path="./workflow_qwen.json",
            prompt_node="Positive",
            seed_node="KSampler",
            seed_param="seed",
            save_node="Save Image",
            save_param="filename_prefix",
            model_node="Load Checkpoint",
            model_param="ckpt_name",
            model=model
        )
    else:  # SDXL
        generate_image("image", comfy_prompt=prompt, model=model)

    logging.info(f"{selected_workflow} generation started with prompt: {prompt}")

def get_queue_count() -> int:
    """Fetches the current queue count from ComfyUI (pending + running jobs)."""
    url = user_config["comfyui"]["comfyui_url"] + "/queue"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        pending = len(data.get("queue_pending", []))
        running = len(data.get("queue_running", []))
        return pending + running
    except Exception as e:
        logging.error(f"Error fetching queue count: {e}")
        return 0

def get_queue_details() -> list:
    """Fetches detailed queue information including model names and prompts."""
    url = user_config["comfyui"]["comfyui_url"] + "/queue"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        jobs = []
        for job_list in [data.get("queue_running", []), data.get("queue_pending", [])]:
            for job in job_list:
                # Extract prompt data (format: [priority, time, prompt])
                prompt_data = job[2]
                model = "Unknown"
                prompt = "No prompt"
                
                # Find model loader node (works for SDXL/FLUX/Qwen workflows)
                for node in prompt_data.values():
                    if node.get("class_type") in ["CheckpointLoaderSimple", "UnetLoaderGGUFAdvancedDisTorchMultiGPU"]:
                        model = node["inputs"].get("ckpt_name", "Unknown")
                        break
                
                # Find prompt node using class_type pattern and title matching
                for node in prompt_data.values():
                    class_type = node.get("class_type", "")
                    if "CLIPTextEncode" in class_type and "text" in node["inputs"]:
                        meta = node.get('_meta', {})
                        title = meta.get('title', '').lower()
                        if 'positive' in title or 'prompt' in title:
                            prompt = node["inputs"]["text"]
                            break
                
                jobs.append({
                    "id": job[0],
                    "model": model.split(".")[0] if model != "Unknown" else model,
                    "prompt": prompt
                })
        return jobs
    except Exception as e:
        logging.error(f"Error fetching queue details: {e}")
        return []
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        pending = len(data.get("queue_pending", []))
        running = len(data.get("queue_running", []))
        return pending + running
    except Exception as e:
        logging.error(f"Error fetching queue count: {e}")
        return 0
