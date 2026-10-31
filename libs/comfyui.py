import logging
import os
import random
import time
import requests
from typing import Optional
from comfy_api_simplified import ComfyWorkflowWrapper
from tenacity import (
    retry,
    stop_after_attempt,
    wait_fixed,
    before_log,
    retry_if_not_exception_type,
)
from libs import jobs
from libs.generic import rename_image, load_config, load_me_photos, save_prompt, get_bool, ME_PROMPT
from libs.local_llm import unload_local_models
from libs.create_thumbnail import generate_thumbnail
from libs.remote import RemoteService

logger = logging.getLogger(__name__)

COMFY_TIMEOUT = 10
QUEUE_TIMEOUT = 60
IMAGE_FETCH_TIMEOUT = 60
POLL_INTERVAL = 2
MISSING_POLLS_LIMIT = 5
RENDER_TIMEOUT = 3600


class RenderTimeout(Exception):
    """ComfyUI may still be rendering, so queueing the prompt again would duplicate it."""


AVAILABLE_MODELS_CACHE = None
AVAILABLE_MODELS_CACHE_TIME = 0
AVAILABLE_MODELS_CACHE_TTL = 300

ME_MODEL = "Me"
ME_CHECKPOINT = "Qwen-Image-Edit-2509-Q3_K_M.gguf"
ME_LIKENESS = "Preserve the exact face, hair, beard and likeness of the man from the reference image."
DEFAULT_ME_CHANCE = 25


def get_available_models() -> list:
    global AVAILABLE_MODELS_CACHE, AVAILABLE_MODELS_CACHE_TIME

    if AVAILABLE_MODELS_CACHE is not None and (time.time() - AVAILABLE_MODELS_CACHE_TIME) < AVAILABLE_MODELS_CACHE_TTL:
        return AVAILABLE_MODELS_CACHE

    config = load_config()
    url = config["comfyui"]["comfyui_url"] + "/object_info"
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


def get_available_me_photos() -> list[str]:
    """The configured Me photos that are really in ComfyUI's input folder."""
    photos = load_me_photos()
    if not photos:
        return []
    try:
        response = requests.get(_comfy_url("/object_info/LoadImage"), timeout=COMFY_TIMEOUT)
        response.raise_for_status()
        available = response.json()["LoadImage"]["input"]["required"]["image"][0]
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        logger.error("Could not list ComfyUI's input photos: %s", e)
        return []
    return [photo for photo in photos if photo in available]


def picks_me_tonight() -> bool:
    chance = load_config().getint("comfyui:me", "nightly_chance", fallback=DEFAULT_ME_CHANCE)
    return random.random() * 100 < chance and bool(get_available_me_photos())


def _comfy_url(path: str) -> str:
    return load_config()["comfyui"]["comfyui_url"] + path


def _get_queue() -> dict:
    response = requests.get(_comfy_url("/queue"), timeout=COMFY_TIMEOUT)
    response.raise_for_status()
    return response.json()


def cancel_current_job() -> str:
    try:
        response = requests.post(_comfy_url("/interrupt"), timeout=COMFY_TIMEOUT)
    except requests.RequestException as e:
        logger.error("Failed to cancel: %s", e)
        return "Failed to cancel"
    if response.status_code == 200:
        return "Cancelled"
    else:
        return "Failed to cancel"


def free_comfy_memory() -> None:
    """Asks ComfyUI to evict loaded models from VRAM/RAM once a generation run is done."""
    try:
        response = requests.post(
            _comfy_url("/free"), json={"unload_models": True, "free_memory": True}, timeout=COMFY_TIMEOUT
        )
        if response.status_code == 200:
            logger.debug("Requested comfy memory free")
        else:
            logger.error("Comfy memory free failed: %s", response.status_code)
    except Exception as e:
        logger.error("Failed to request comfy memory free: %s", e)


def _queue_prompt(workflow: dict) -> str:
    # Generous because ComfyUI's API stalls while its web UI loads, and timing out here
    # after ComfyUI accepted the prompt would make the retry queue a duplicate.
    response = requests.post(_comfy_url("/prompt"), json={"prompt": workflow}, timeout=QUEUE_TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(f"ComfyUI rejected the workflow ({response.status_code}): {response.text[:300]}")
    return response.json()["prompt_id"]


def _wait_for_render(prompt_id: str) -> dict:
    """Polls until ComfyUI has finished prompt_id and returns its history entry.

    A prompt in neither the queue nor the history is gone, usually because ComfyUI
    restarted. The check is repeated because a prompt moves between the two.
    """
    deadline = time.monotonic() + RENDER_TIMEOUT
    missing = 0
    started = False
    ahead = None
    while time.monotonic() < deadline:
        try:
            response = requests.get(_comfy_url(f"/history/{prompt_id}"), timeout=COMFY_TIMEOUT)
            response.raise_for_status()
            entry = response.json().get(prompt_id)
            if entry:
                return entry

            queue = _get_queue()
            pending = [item[1] for item in queue.get("queue_pending", [])]
            if any(item[1] == prompt_id for item in queue.get("queue_running", [])):
                jobs.update_current(status="rendering")
                if not started:
                    jobs.log_step("ComfyUI started rendering")
                    started = True
                missing = 0
            elif prompt_id in pending:
                position = pending.index(prompt_id) + len(queue.get("queue_running", []))
                if position != ahead:
                    jobs.log_step(f"In the ComfyUI queue, {position} ahead")
                    ahead = position
                missing = 0
            else:
                missing += 1
        except requests.RequestException as e:
            logger.warning("Could not reach ComfyUI while waiting for a render: %s", e)

        if missing >= MISSING_POLLS_LIMIT:
            raise RuntimeError("ComfyUI lost the job, it may have restarted.")
        time.sleep(POLL_INTERVAL)

    raise RenderTimeout(f"Render did not finish within {RENDER_TIMEOUT} seconds.")


def _first_output_image(entry: dict, node_id: str) -> dict:
    status = entry.get("status") or {}
    messages = status.get("messages") or []
    if any(message[0] == "execution_interrupted" for message in messages):
        raise jobs.JobCancelled()
    if status.get("status_str") == "error":
        errors = [m[1].get("exception_message", "") for m in messages if m[0] == "execution_error"]
        raise RuntimeError(f"ComfyUI failed: {errors[0].strip() if errors else 'unknown error'}")

    images = entry.get("outputs", {}).get(node_id, {}).get("images")
    if not images:
        raise RuntimeError("ComfyUI finished without producing an image.")
    return images[0]


def _fetch_image(image: dict) -> bytes:
    response = requests.get(
        _comfy_url("/view"),
        params={"filename": image["filename"], "subfolder": image["subfolder"], "type": image["type"]},
        timeout=IMAGE_FETCH_TIMEOUT,
    )
    response.raise_for_status()
    return response.content


def _write_image_atomically(path: str, image_data: bytes) -> None:
    temp_path = path + ".tmp"
    with open(temp_path, "wb") as f:
        f.write(image_data)
    os.replace(temp_path, path)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(5),
    before=before_log(logging.getLogger(), logging.DEBUG),
    retry=retry_if_not_exception_type((RenderTimeout, jobs.JobCancelled)),
    reraise=True,
)
def generate_image(
    file_name: str,
    comfy_prompt: str,
    workflow_path: str = "./workflow_sdxl.json",
    prompt_node: str = "Positive",
    prompt_param: str = "text",
    seed_node: str = "KSampler",
    seed_param: str = "seed",
    save_node: str = "Save Image",
    save_param: str = "filename_prefix",
    model_node: Optional[str] = "Load Checkpoint",
    model_param: Optional[str] = "ckpt_name",
    model: Optional[str] = "None",
    node_params: Optional[dict[str, dict]] = None,
) -> None:
    config = load_config()
    try:
        wf = ComfyWorkflowWrapper(workflow_path)

        wf.set_node_param(seed_node, seed_param, random.getrandbits(32))
        wf.set_node_param(prompt_node, prompt_param, comfy_prompt)
        wf.set_node_param(save_node, save_param, file_name)
        wf.set_node_param(
            (
                "Empty Latent Image"
                if workflow_path.endswith("workflow_sdxl.json")
                else "CR Aspect Ratio"
            ),
            "width",
            config["comfyui"]["width"],
        )
        wf.set_node_param(
            (
                "Empty Latent Image"
                if workflow_path.endswith("workflow_sdxl.json")
                else "CR Aspect Ratio"
            ),
            "height",
            config["comfyui"]["height"],
        )

        wf.set_node_param(model_node, model_param, model)
        for node, params in (node_params or {}).items():
            for param, value in params.items():
                wf.set_node_param(node, param, value)

        # Only one render at a time writes the shared image.png. It is archived
        # after the render, not before, so the frame keeps showing the current
        # image while rendering and is left untouched if the render fails.
        from libs.generic import _image_write_lock

        logger.debug("Generating image: %s", file_name)
        jobs.update_current(status="waiting")
        with _image_write_lock:
            # Inside the lock so a second job's prompt model cannot load between this and the render.
            unload_local_models()
            jobs.log_step("Sending the job to ComfyUI")
            entry = _wait_for_render(_queue_prompt(wf))
            jobs.log_step("Render finished, saving the image")
            image_data = _fetch_image(_first_output_image(entry, wf.get_node_id(save_node)))

            rename_image()
            output_path = os.path.join(config["comfyui"]["output_dir"], f"{file_name}.png")
            _write_image_atomically(output_path, image_data)
            generate_thumbnail(output_path)

        logger.debug("Image generated successfully for UID: %s", file_name)

    except jobs.JobCancelled:
        logger.info("Generation of %s was cancelled.", file_name)
        raise
    except Exception as e:
        logger.error("Failed to generate image for UID: %s. Error: %s", file_name, e)
        jobs.log_step(f"Render failed: {e}")
        raise


def select_model(model: str) -> tuple[str, str]:
    config = load_config()
    use_flux = get_bool(config, "comfyui", "flux", False)
    only_flux = get_bool(config, "comfyui", "only_flux", False)
    use_qwen = get_bool(config, "comfyui", "qwen", False)
    use_zimage = get_bool(config, "comfyui", "zimage", False)

    if model == "Random Image Model":
        available_workflows = []
        if not only_flux:
            available_workflows.append("SDXL")
        if use_flux:
            available_workflows.append("FLUX")
        if use_qwen:
            available_workflows.append("Qwen")
        if use_zimage:
            available_workflows.append("ZImage")

        if not available_workflows:
            available_workflows.append("SDXL")

        selected_workflow = random.choice(available_workflows)
    elif "flux" in model.lower():
        selected_workflow = "FLUX"
    elif "qwen" in model.lower():
        selected_workflow = "Qwen"
    elif "z_image" in model.lower() or "z-image" in model.lower():
        selected_workflow = "ZImage"
    else:
        selected_workflow = "SDXL"

    if model == "Random Image Model":
        if selected_workflow == "FLUX":
            valid_models = [m.strip() for m in config["comfyui:flux"]["models"].split(",") if m.strip()]
        elif selected_workflow == "Qwen":
            valid_models = [m.strip() for m in config["comfyui:qwen"]["models"].split(",") if m.strip()]
        elif selected_workflow == "ZImage":
            valid_models = [m.strip() for m in config["comfyui:zimage"]["models"].split(",") if m.strip()]
        else:
            available_model_list = [m.strip() for m in config["comfyui"]["models"].split(",") if m.strip()]
            valid_models = list(set(get_available_models()) & set(available_model_list))
            if not valid_models:
                valid_models = available_model_list
        if not valid_models:
            fallback_models = [m.strip() for m in config["comfyui"]["models"].split(",") if m.strip()]
            valid_models = fallback_models[:1] if fallback_models else ["sd_xl_base_1.0.safetensors"]
        model = random.choice(valid_models)

    return selected_workflow, model


def _use_freellmapi_backend() -> bool:
    """True when images should come from the FreeLLMAPI router instead of ComfyUI."""
    return get_bool(load_config(), "freellmapi", "image_backend", False)


def _render_me(scene: str) -> None:
    photos = get_available_me_photos()
    if not photos:
        raise RuntimeError("None of the Me photos are in ComfyUI's input folder.")
    photo = random.choice(photos)
    jobs.update_current(model=f"{ME_MODEL} ({photo})")
    jobs.log_step(f"Image model selected: {ME_CHECKPOINT} with photo {photo}")
    generate_image(
        file_name="image",
        comfy_prompt=f"{scene.strip().rstrip('.')}. {ME_LIKENESS}",
        workflow_path="./workflow_me.json",
        prompt_node="Positive",
        prompt_param="prompt",
        model_node="Load Checkpoint",
        model_param="unet_name",
        model=ME_CHECKPOINT,
        node_params={"Your photo": {"image": photo}},
    )
    logger.info("Me generation started with prompt: %s", scene)


def create_image(prompt: str | None = None, model: str = "Random Image Model", topic: str = "") -> None:
    if prompt is None:
        from libs.generic import create_prompt_with_random_model
        config = load_config()
        base_prompt = config["comfyui"].get("prompt", "Generate a random detailed prompt for stable diffusion.")
        if model == ME_MODEL:
            base_prompt = ME_PROMPT
        prompt, _ = create_prompt_with_random_model(base_prompt)

    if not prompt:
        raise RuntimeError("No prompt could be generated.")

    jobs.update_current(prompt=prompt)
    save_prompt(prompt, topic)

    if model != ME_MODEL and _use_freellmapi_backend():
        from libs.freellmapi import generate_image_on_freellmapi

        # freellmapi only accepts "auto" (router picks the best model), so
        # any user-selected model is ignored here.
        jobs.update_current(status="rendering", model="freellmapi auto")
        generate_image_on_freellmapi(prompt, model="auto")
        logger.info("freellmapi image generation started with prompt: %s", prompt)
        return

    # If a remote ComfyUI service is configured, bring it up for this
    # generation and shut it down afterwards. Reference counted so concurrent
    # jobs keep it alive until the last one finishes.
    with RemoteService():
        try:
            if model == ME_MODEL:
                _render_me(prompt)
                return

            selected_workflow, model = select_model(model)
            jobs.update_current(model=model)
            jobs.log_step(f"Image model selected: {model} ({selected_workflow})")
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
                    model_node="Load Checkpoint",
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
            elif selected_workflow == "ZImage":
                generate_image(
                    file_name="image",
                    comfy_prompt=prompt,
                    workflow_path="./workflow_zimage.json",
                    prompt_node="Positive",
                    seed_node="KSampler",
                    seed_param="seed",
                    save_node="Save Image",
                    save_param="filename_prefix",
                    model_node="Load Checkpoint",
                    model_param="unet_name",
                    model=model
                )
            else:
                generate_image("image", comfy_prompt=prompt, model=model)

            logger.info("%s generation started with prompt: %s", selected_workflow, prompt)
        finally:
            # Hand VRAM/RAM back after every run, including failed and cancelled ones.
            jobs.log_step("Freeing ComfyUI memory")
            free_comfy_memory()


_MODEL_LOADER_NODES = (
    "CheckpointLoaderSimple",
    "UnetLoaderGGUF",
    "UnetLoaderGGUFDisTorchMultiGPU",
    "UnetLoaderGGUFAdvancedDisTorchMultiGPU",
)


def get_queue_count() -> int:
    try:
        data = _get_queue()
        pending = len(data.get("queue_pending", []))
        running = len(data.get("queue_running", []))
        return pending + running
    except Exception as e:
        logger.error("Error fetching queue count: %s", e)
        return 0


def get_queue_details() -> list:
    try:
        data = _get_queue()
        queue_jobs = []
        for job_list in [data.get("queue_running", []), data.get("queue_pending", [])]:
            for job in job_list:
                prompt_data = job[2]
                model = "Unknown"
                prompt = "No prompt"

                for node in prompt_data.values():
                    if node.get("class_type") in _MODEL_LOADER_NODES:
                        model = node["inputs"].get("ckpt_name", node["inputs"].get("unet_name", "Unknown"))
                        break

                for node in prompt_data.values():
                    class_type = node.get("class_type", "")
                    text = node["inputs"].get("text", node["inputs"].get("prompt"))
                    if "TextEncode" in class_type and text is not None:
                        meta = node.get('_meta', {})
                        title = meta.get('title', '').lower()
                        if 'positive' in title or 'prompt' in title:
                            prompt = text
                            break

                model_display = model.split(".")[0] if model != "Unknown" else model
                queue_jobs.append({
                    "id": job[0],
                    "model": model_display,
                    "prompt": prompt
                })
        return queue_jobs
    except Exception as e:
        logger.error("Error fetching queue details: %s", e)
        return []