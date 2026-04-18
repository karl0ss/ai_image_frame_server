import random
import logging
import os
import time
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
from libs.generic import rename_image, load_config, save_prompt, get_bool
from libs.create_thumbnail import generate_thumbnail

logger = logging.getLogger(__name__)

user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]

AVAILABLE_MODELS_CACHE = None
AVAILABLE_MODELS_CACHE_TIME = 0
AVAILABLE_MODELS_CACHE_TTL = 300  # 5 minutes


def get_available_models() -> list:
    """Fetches available models from ComfyUI with caching."""
    global AVAILABLE_MODELS_CACHE, AVAILABLE_MODELS_CACHE_TIME
    
    if AVAILABLE_MODELS_CACHE is not None:
        if time.time() - AVAILABLE_MODELS_CACHE_TIME < AVAILABLE_MODELS_CACHE_TTL:
            return AVAILABLE_MODELS_CACHE
    
    url = user_config["comfyui"]["comfyui_url"] + "/object_info"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            general = data.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
            flux = data.get("UnetLoaderGGUF", {}).get("input", {}).get("required", {}).get("unet_name", [[]])[0]
            all_models = []
            if isinstance(general, list):
                all_models.extend(general)
            if isinstance(flux, list):
                all_models.extend(flux)
            AVAILABLE_MODELS_CACHE = all_models
            AVAILABLE_MODELS_CACHE_TIME = time.time()
            return all_models
        else:
            logger.warning("Failed to fetch models: %s", response.status_code)
            return []
    except Exception as e:
        logger.error("Error fetching models: %s", e)
        if AVAILABLE_MODELS_CACHE is not None:
            return AVAILABLE_MODELS_CACHE
        return []


def cancel_current_job() -> str:
    """Cancels the current running job on ComfyUI."""
    url = user_config["comfyui"]["comfyui_url"] + "/interrupt"
    response = requests.post(url)
    if response.status_code == 200:
        return "Cancelled"
    else:
        return "Failed to cancel"


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

        logger.debug("Generating image: %s", file_name)
        results = api.queue_and_wait_images(wf, save_node)
        rename_image()

        for _, image_data in results.items():
            output_path = os.path.join(
                user_config["comfyui"]["output_dir"], f"{file_name}.png"
            )
            with open(output_path, "wb+") as f:
                f.write(image_data)
            generate_thumbnail(output_path)

        logger.debug("Image generated successfully for UID: %s", file_name)

    except Exception as e:
        logger.error("Failed to generate image for UID: %s. Error: %s", file_name, e)
        raise

def select_model(model: str) -> tuple[str, str]:
    use_flux = get_bool(user_config, "comfyui", "flux", False)
    only_flux = get_bool(user_config, "comfyui", "only_flux", False)
    use_qwen = get_bool(user_config, "comfyui", "qwen", False)

    if model == "Random Image Model":
        available_workflows = []
        if not only_flux:
            available_workflows.append("SDXL")
        if use_flux:
            available_workflows.append("FLUX")
        if use_qwen:
            available_workflows.append("Qwen")
        
        if not available_workflows:
            available_workflows.append("SDXL")
        
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
        else:
            available_model_list = user_config["comfyui"]["models"].split(",")
            valid_models = list(set(get_available_models()) & set(available_model_list))
            if not valid_models:
                valid_models = available_model_list
        if not valid_models:
            fallback_models = user_config["comfyui"]["models"].split(",")
            valid_models = [fallback_models[0].strip()] if fallback_models else ["sd_xl_base_1.0.safetensors"]
        model = random.choice(valid_models)

    return selected_workflow, model


def create_image(prompt: str | None = None, model: str = "Random Image Model", topic: str = "") -> None:
    """Generate an image with a chosen workflow (Random, FLUX*, or SDXL*)."""

    if prompt is None:
        from libs.generic import create_prompt_with_random_model
        config = load_config()
        base_prompt = config["comfyui"].get("prompt", "Generate a random detailed prompt for stable diffusion.")
        prompt, _ = create_prompt_with_random_model(base_prompt)
        if not prompt:
            logger.error("Failed to generate a prompt.")
            return

    if not prompt:
        logger.error("No prompt generated.")
        return

    save_prompt(prompt, topic)
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
    else:
        generate_image("image", comfy_prompt=prompt, model=model)

    logger.info("%s generation started with prompt: %s", selected_workflow, prompt)

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
        logger.error("Error fetching queue count: %s", e)
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
                prompt_data = job[2]
                model = "Unknown"
                prompt = "No prompt"
                
                for node in prompt_data.values():
                    if node.get("class_type") in ["CheckpointLoaderSimple", "UnetLoaderGGUFAdvancedDisTorchMultiGPU"]:
                        model = node["inputs"].get("ckpt_name", "Unknown")
                        break
                
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
        logger.error("Error fetching queue details: %s", e)
        return []