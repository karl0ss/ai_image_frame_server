import random
import configparser
import logging
import sys
import litellm
import time
import os
import requests
from comfy_api_simplified import ComfyApiWrapper, ComfyWorkflowWrapper
from tenacity import (
    retry,
    stop_after_attempt,
    wait_fixed,
    before_log,
    retry_if_exception_type,
)
import nest_asyncio
import json
from datetime import datetime, timedelta

nest_asyncio.apply()

logging.basicConfig(level=logging.INFO)

LOG_FILE = "./prompts_log.jsonl"


def load_recent_prompts(days=7):
    recent_prompts = []
    cutoff_date = datetime.now().date() - timedelta(days=days)

    try:
        with open(LOG_FILE, "r") as f:
            for line in f:
                data = json.loads(line.strip())
                prompt_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
                if prompt_date >= cutoff_date:
                    recent_prompts.append(data["prompt"])
    except FileNotFoundError:
        pass  # No prompts yet

    return recent_prompts


def save_prompt(prompt):
    entry = {"date": datetime.now().strftime("%Y-%m-%d"), "prompt": prompt}
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


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


def load_config() -> configparser.ConfigParser:
    """Loads user configuration from ./user_config.cfg."""
    user_config = configparser.ConfigParser()
    try:
        user_config.read("./user_config.cfg")
        logging.debug("Configuration loaded successfully.")
        return user_config
    except KeyError as e:
        logging.error(f"Missing configuration key: {e}")
        sys.exit(1)


def rename_image() -> str | None:
    """Renames 'image.png' in the output folder to a timestamped filename if it exists."""
    old_path = os.path.join(user_config["comfyui"]["output_dir"], "image.png")

    if os.path.exists(old_path):
        new_filename = f"{str(time.time())}.png"
        new_path = os.path.join(user_config["comfyui"]["output_dir"], new_filename)
        os.rename(old_path, new_path)
        print(f"Renamed 'image.png' to '{new_filename}'")
        return new_filename
    else:
        print("No image.png found.")
        return None


def create_prompt_on_openwebui(prompt: str) -> str:
    """Sends prompt to OpenWebui and returns the generated response."""
    recent_prompts = load_recent_prompts()
    user_content = (
        "Here are the prompts from the last 7 days:\n\n"
        + "\n".join(f"{i+1}. {p}" for i, p in enumerate(recent_prompts))
        + "\n\nDo not repeat ideas, themes, or settings from the above. Now generate a new, completely original Stable Diffusion prompt that hasn't been done yet."
    )

    model = random.choice(user_config["openwebui"]["models"].split(","))
    response = litellm.completion(
        api_base=user_config["openwebui"]["base_url"],
        model="openai/" + model,
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
        ],
        api_key=user_config["openwebui"]["api_key"],
    )

    prompt = response["choices"][0]["message"]["content"].strip('"')
    # response = litellm.completion(
    #     api_base=user_config["openwebui"]["base_url"],
    #     model="openai/brxce/stable-diffusion-prompt-generator:latest",
    #     messages=[
    #         {
    #             "role": "user",
    #             "content": prompt,
    #         },
    #     ],
    #     api_key=user_config["openwebui"]["api_key"],
    # )
    # prompt = response["choices"][0]["message"]["content"].strip('"')
    logging.debug(prompt)
    return prompt


# Define the retry logic using Tenacity
# @retry(
#     stop=stop_after_attempt(3),
#     wait=wait_fixed(5),
#     before=before_log(logging.getLogger(), logging.DEBUG),
#     retry=retry_if_exception_type(Exception)
# )
def generate_image(file_name: str, comfy_prompt: str) -> None:
    """Generates an image using the Comfy API with retry logic."""
    try:
        # Initialize ComfyUI API and workflow
        api = ComfyApiWrapper(user_config["comfyui"]["comfyui_url"])
        wf = ComfyWorkflowWrapper("./workflow_api.json")

        # Set workflow parameters
        wf.set_node_param(
            "KSampler", "seed", random.getrandbits(32)
        )  # Set a random seed for the sampler
        wf.set_node_param(
            "CLIP Text Encode (Prompt)", "text", comfy_prompt
        )  # Set the prompt to be used for image generation
        wf.set_node_param(
            "Save Image", "filename_prefix", file_name
        )  # Set the filename prefix for the generated image
        wf.set_node_param(  # Set image dimensions
            "Empty Latent Image", "width", user_config["comfyui"]["width"]
        )
        wf.set_node_param(
            "Empty Latent Image", "height", user_config["comfyui"]["height"]
        )

        # Validate available models and choose a random one
        valid_models = list(
            set(get_available_models())  # Get all available models from ComfyUI
            & set(user_config["comfyui"]["models"].split(","))
        )
        if not valid_models:
            raise Exception("No valid options available.")
        model = random.choice(valid_models)
        wf.set_node_param(
            "Load Checkpoint", "ckpt_name", model
        )  # Set the model to be used for image generation

        # Generate the image using the workflow and wait for completion
        logging.debug(f"Generating image: {file_name}")
        results = api.queue_and_wait_images(
            wf, "Save Image"
        )  # Queue the workflow and wait for image generation to complete
        rename_image()  # Rename the generated image file if it exists

        # Save the generated image to disk
        for filename, image_data in results.items():
            with open(
                user_config["comfyui"]["output_dir"] + file_name + ".png", "wb+"
            ) as f:
                f.write(image_data)
        logging.debug(f"Image generated successfully for UID: {file_name}")

    except Exception as e:
        logging.error(f"Failed to generate image for UID: {file_name}. Error: {e}")
        raise  # Re-raise the exception for Tenacity to handle retries


def generate_image_flux(file_name: str, comfy_prompt: str) -> None:
    """Generates an image using the Comfy API with retry logic."""
    try:
        # Initialize ComfyUI API and workflow
        api = ComfyApiWrapper(user_config["comfyui"]["comfyui_url"])
        wf = ComfyWorkflowWrapper("./FLUX.json")

        # Set workflow parameters
        wf.set_node_param(
            "Seed", "seed", random.getrandbits(32)
        )  # Set a random seed for the sampler
        wf.set_node_param(
            "Positive Prompt T5", "text", comfy_prompt
        )  # Set the prompt to be used for image generation
        wf.set_node_param(
            "CivitAI Image Saver", "filename", file_name
        )  # Set the filename prefix for the generated image
        wf.set_node_param(  # Set image dimensions
            "CR Aspect Ratio", "width", user_config["comfyui"]["width"]
        )
        wf.set_node_param(
            "CR Aspect Ratio", "height", user_config["comfyui"]["height"]
        )

        # # Validate available models and choose a random one
        # valid_models = list(
        #     set(get_available_models())  # Get all available models from ComfyUI
        #     & set(user_config["comfyui"]["models"].split(","))
        # )
        # if not valid_models:
        #     raise Exception("No valid options available.")
        # model = random.choice(valid_models)
        # wf.set_node_param(
        #     "Load Checkpoint", "ckpt_name", model
        # )  # Set the model to be used for image generation

        # Generate the image using the workflow and wait for completion
        logging.debug(f"Generating image: {file_name}")
        results = api.queue_and_wait_images(
            # wf, "Save Image"
            wf,
            "CivitAI Image Saver",
        )  # Queue the workflow and wait for image generation to complete
        rename_image()  # Rename the generated image file if it exists

        # Save the generated image to disk
        for filename, image_data in results.items():
            with open(
                user_config["comfyui"]["output_dir"] + file_name + ".png", "wb+"
            ) as f:
                f.write(image_data)
        logging.debug(f"Image generated successfully for UID: {file_name}")

    except Exception as e:
        logging.error(f"Failed to generate image for UID: {file_name}. Error: {e}")
        raise  # Re-raise the exception for Tenacity to handle retries


def create_image(prompt: str | None = None) -> None:
    """Main function for generating images."""
    if prompt is None:
        prompt = create_prompt_on_openwebui(user_config["comfyui"]["prompt"])
    if prompt:
        logging.info(f"Generated prompt: {prompt}")  # Log generated prompt
        save_prompt(prompt)
        if user_config["comfyui"]["FLUX"]:
            generate_image_flux("image", prompt)
        else:
            generate_image("image", prompt)
        print(f"Image generation started with prompt: {prompt}")
    else:
        logging.error("No prompt generated.")


user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]
