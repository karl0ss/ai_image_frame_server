import random
import logging
import litellm
import nest_asyncio
from libs.generic import load_recent_prompts, load_config
nest_asyncio.apply()

logging.basicConfig(level=logging.INFO)

LOG_FILE = "./prompts_log.jsonl"

user_config = load_config()
output_folder = user_config["comfyui"]["output_dir"]

def create_prompt_on_openwebui(prompt: str, topic: str = "random") -> str:
    """Sends prompt to OpenWebui and returns the generated response."""
    topic_instruction = ""
    selected_topic = ""
    # Unique list of recent prompts
    recent_prompts = list(set(load_recent_prompts()))
    if topic == "random":
        topics = [t.strip() for t in user_config["comfyui"]["topics"].split(",") if t.strip()]
        selected_topic = random.choice(topics)
    elif topic != "":
        selected_topic = topic
    else:
        # Decide on whether to include a topic (e.g., 30% chance to include)
        topics = [t.strip() for t in user_config["comfyui"]["topics"].split(",") if t.strip()]
        if random.random() < 0.3 and topics:
            selected_topic = random.choice(topics)
    if selected_topic != "":
        topic_instruction = f" Incorporate the theme of '{selected_topic}' into the new prompt."

    user_content = (
        "Can you generate me a really random image idea, Do not exceed 10 words. Use clear language, not poetic metaphors.”"
        + topic_instruction
        + "Avoid prompts similar to the following:"
        + "\n".join(f"{i+1}. {p}" for i, p in enumerate(recent_prompts))
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
    return prompt.split(": ")[-1]