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

def create_prompt_on_openwebui(prompt: str) -> str:
    """Sends prompt to OpenWebui and returns the generated response."""
    # Unique list of recent prompts
    recent_prompts = list(set(load_recent_prompts()))
    # Decide on whether to include a topic (e.g., 30% chance to include)
    topics = [t.strip() for t in user_config["comfyui"]["topics"].split(",") if t.strip()]
    topic_instruction = ""
    if random.random() < 0.3 and topics:
        selected_topic = random.choice(topics)
        topic_instruction = f" Incorporate the theme of '{selected_topic}' into the new prompt."

    user_content = (
        "Here are the prompts from the last 7 days:\n\n"
        + "\n".join(f"{i+1}. {p}" for i, p in enumerate(recent_prompts))
        + "\n\nDo not repeat ideas, themes, or settings from the above. "
        "Now generate a new, completely original Stable Diffusion prompt that hasn't been done yet."
        + topic_instruction
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