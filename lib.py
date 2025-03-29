import random
import configparser
import logging
import sys
import litellm
import time
import os
import requests
from comfy_api_simplified import ComfyApiWrapper, ComfyWorkflowWrapper

def get_available_models():
    url = user_config["comfyui"]["comfyui_url"] + "/object_info"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [])[0]
    else:
        print(f"Failed to fetch models: {response.status_code}")
        return []

def load_config():
    user_config = configparser.ConfigParser()
    try:
        user_config.read("./user_config.cfg")
        logging.debug("Configuration loaded successfully.")
        return user_config
    except KeyError as e:
        logging.error(f"Missing configuration key: {e}")
        sys.exit(1)


def rename_image():
    """Rename 'image.png' to a timestamped filename if it exists in the output folder."""
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


def send_prompt_to_openwebui(prompt):
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


def generate_image(file_name, comfy_prompt):
    """Generate an image using the Comfy API."""
    try:
        # Initialize API and workflow
        api = ComfyApiWrapper(user_config["comfyui"]["comfyui_url"])
        wf = ComfyWorkflowWrapper("./workflow_api.json")

        # Set workflow parameters
        wf.set_node_param("KSampler", "seed", random.getrandbits(32))
        # wf.set_node_param("KSampler", "steps", steps)
        wf.set_node_param("CLIP Text Encode (Prompt)", "text", comfy_prompt)
        wf.set_node_param("Save Image", "filename_prefix", file_name)
        wf.set_node_param("Empty Latent Image", "width", user_config["comfyui"]["width"])
        wf.set_node_param("Empty Latent Image", "height", user_config["comfyui"]["height"])
        valid_models = list(set(get_available_models()) & set(user_config["comfyui"]["models"].split(",")))
        if not valid_models:
            raise Exception("No valid options available.")
        model = random.choice(valid_models)
        wf.set_node_param(
            "Load Checkpoint", "ckpt_name", model
        )
        # Queue your workflow for completion
        logging.debug(f"Generating image: {file_name}")
        results = api.queue_and_wait_images(wf, "Save Image")
        rename_image()
        for filename, image_data in results.items():
            with open(
                user_config["comfyui"]["output_dir"] + file_name + ".png", "wb+"
            ) as f:
                f.write(image_data)
        logging.debug(f"Image generated successfully for UID: {file_name}")
    except Exception as e:
        logging.error(f"Failed to generate image for UID: {file_name}. Error: {e}")


def create_image(prompt):
    """Main function for generating images."""
    if prompt is None:
        prompt = send_prompt_to_openwebui(user_config["comfyui"]["prompt"])
    print(f"Generated prompt: {prompt}")
    generate_image("image", prompt)


user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]
