import random
import configparser
import logging
import sys
import litellm
import time
import os
import requests
from comfy_api_simplified import ComfyApiWrapper, ComfyWorkflowWrapper


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


def send_prompt_to_openwebui(prompt: str) -> str:
    """Sends prompt to OpenWebui and returns the generated response."""
    response = litellm.completion(
        api_base=user_config["openwebui"]["base_url"],
        model="openai/" + user_config["openwebui"]["model"],
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        api_key=user_config["openwebui"]["api_key"],
    )

    return response["choices"][0]["message"]["content"].strip('"')


def generate_image(file_name: str, comfy_prompt: str) -> None:
    """Generates an image using the Comfy API."""
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


def create_image(prompt: str | None = None) -> None:
    """Main function for generating images."""
    if prompt is None:
        prompt = send_prompt_to_openwebui(user_config["comfyui"]["prompt"])
    print(f"Generated prompt: {prompt}")
    generate_image("image", prompt)


user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]
