import base64
import io
import logging
import os

import requests
from PIL import Image

from libs.generic import (
    SYSTEM_PROMPT,
    build_request_content,
    extract_prompt,
    _image_write_lock,
    get_bool,
    load_config,
    rename_image,
)

logger = logging.getLogger(__name__)

IMAGE_ENDPOINT = "/v1/images/generations"
CHAT_ENDPOINT = "/v1/chat/completions"


def _extract_final_prompt(content: str) -> str:
    """Pull the actual image prompt out of a FreeLLMAPI chat response.

    FreeLLMAPI models often emit reasoning text before the final prompt, so
    plain extract_prompt (which grabs the first quoted string) is too naive.
    Strategy: prefer the last quoted string, fall back to the last non-empty
    line, then fall back to extract_prompt.
    """
    if not content:
        return ""

    # 1) Last quoted string in the response is most likely the final prompt.
    import re

    quotes = re.findall(r'"([^"]+)"', content)
    if quotes:
        candidate = quotes[-1].strip()
        if len(candidate) >= 10:
            return candidate

    # 2) Last non-empty, non-numeric line.
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if lines:
        candidate = lines[-1]
        if len(candidate) >= 10 and not candidate.isdigit():
            return candidate

    # 3) Fallback to the generic extractor.
    return extract_prompt(content)


def _client_config() -> tuple[str, str]:
    config = load_config()
    base_url = config.get("freellmapi", "base_url", fallback="").strip().rstrip("/")
    api_key = config.get("freellmapi", "api_key", fallback="").strip()
    return base_url, api_key


def is_enabled() -> bool:
    config = load_config()
    return get_bool(config, "freellmapi", "enabled", False)


def _headers() -> dict:
    _, api_key = _client_config()
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def create_prompt_on_freellmapi(base_prompt: str, topic: str | None = "random", model: str = None) -> str:
    """Generate an image prompt via the FreeLLMAPI chat router."""
    base_url, api_key = _client_config()
    if not base_url or not api_key:
        logger.error("freellmapi base_url or api_key not configured.")
        return ""

    full_content = build_request_content(base_prompt, topic)

    config = load_config()
    configured_models = [
        m.strip() for m in config.get("freellmapi", "models", fallback="").split(",") if m.strip()
    ]
    if model is None:
        if not configured_models:
            logger.error("No freellmapi chat models configured.")
            return ""
        model = configured_models[0]

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": full_content},
        ],
        "max_tokens": 512,
    }

    try:
        resp = requests.post(
            base_url + CHAT_ENDPOINT, headers=_headers(), json=payload, timeout=120
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        prompt = _extract_final_prompt(content)
        logger.debug("freellmapi prompt (%s): %s", model, prompt)
        return prompt
    except Exception as e:
        logger.error("freellmapi chat failed with model %s: %s", model, e)
        return ""


def _save_image_bytes(image_bytes: bytes, output_dir: str) -> str:
    """Decode the base64 image and save it as image.png, normalizing to RGB."""
    output_path = os.path.join(output_dir, "image.png")
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(img, mask=img.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.save(output_path, "PNG")
    except Exception:
        logger.warning("Could not normalize freellmapi image, writing raw bytes.")
        with open(output_path, "wb") as f:
            f.write(image_bytes)

    from libs.create_thumbnail import generate_thumbnail

    generate_thumbnail(output_path)
    return output_path


def generate_image_on_freellmapi(
    prompt: str, output_dir: str = None, model: str = "auto"
) -> str:
    """Generate an image via FreeLLMAPI and save it to output_dir/image.png."""
    base_url, api_key = _client_config()
    if not base_url or not api_key:
        raise RuntimeError("freellmapi base_url or api_key not configured.")

    config = load_config()
    if output_dir is None:
        output_dir = config["comfyui"]["output_dir"]

    payload = {"model": model, "prompt": prompt}
    resp = requests.post(
        base_url + IMAGE_ENDPOINT, headers=_headers(), json=payload, timeout=300
    )
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise RuntimeError(
            f"freellmapi image generation error: {data['error'].get('message')}"
        )

    items = data.get("data", [])
    if not items:
        raise RuntimeError("freellmapi image response contained no data.")

    b64 = items[0].get("b64_json") or items[0].get("image") or ""
    if not b64:
        raise RuntimeError("freellmapi image response missing image data.")

    image_bytes = base64.b64decode(b64)
    with _image_write_lock:
        rename_image()
        path = _save_image_bytes(image_bytes, output_dir)
    logger.info(
        "freellmapi image generated (model=%s, provider=%s) saved to %s",
        data.get("model"),
        data.get("provider"),
        path,
    )
    return path