import random
import configparser
import logging
import sys
import litellm
import time

from datetime import datetime

from comfy_api_simplified import ComfyApiWrapper, ComfyWorkflowWrapper

user_config = configparser.ConfigParser()
try:
    user_config.read("./user_config.cfg")
    output_folder = user_config["comfyui"]["output_dir"]
    logging.debug("Configuration loaded successfully.")
except KeyError as e:
    logging.error(f"Missing configuration key: {e}")
    sys.exit(1)


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
        wf.set_node_param(
            "Load Checkpoint", "ckpt_name", user_config["comfyui"]["model"]
        )
        # Queue your workflow for completion
        logging.debug(f"Generating image: {file_name}")
        results = api.queue_and_wait_images(wf, "Save Image")
        for filename, image_data in results.items():
            with open(
                user_config["comfyui"]["output_dir"] + file_name + ".png", "wb+"
            ) as f:
                f.write(image_data)
        logging.debug(f"Image generated successfully for UID: {file_name}")
    except Exception as e:
        logging.error(f"Failed to generate image for UID: {file_name}. Error: {e}")


def create_image():
    """Main function for generating images."""
    prompt = send_prompt_to_openwebui(user_config["comfyui"]["prompt"])
    print(f"Generated prompt: {prompt}")
    generate_image(str(time.time()), prompt)


# if __name__ == "__main__":
#     main()
