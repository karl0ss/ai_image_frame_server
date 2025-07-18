# AI Image Frame Server

This project is a Flask-based web server designed to generate and display images from various AI models, primarily interacting with ComfyUI. It can be configured to automatically generate new images at scheduled times and provides a gallery to view the generated images.

## Features

*   **Web Interface:** A simple web interface to view generated images.
*   **Image Generation:** Integrates with ComfyUI to generate images based on given prompts and models.
*   **Scheduled Generation:** Automatically generates new images at a configurable time.
*   **Docker Support:** Comes with a `Dockerfile` and `docker-compose.yml` for easy setup and deployment.
*   **Configurable:** Most options can be configured through a `user_config.cfg` file.
*   **Authentication:** Optional password protection for image creation.

## Prerequisites

*   Python 3.11
*   Docker (for containerized deployment)
*   An instance of ComfyUI running and accessible from the server.

## Installation and Setup

### Manual Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd ai_image_frame_server
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure the application:**
    *   Copy the `user_config.cfg.sample` to `user_config.cfg`.
    *   Edit `user_config.cfg` with your settings. See the [Configuration](#configuration) section for more details.

4.  **Run the application:**
    ```bash
    export SECRET_KEY='a_very_secret_key'
    python ai_frame_image_server.py
    ```

### Docker Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd ai_image_frame_server
    ```

2.  **Configure the application:**
    *   Copy the `user_config.cfg.sample` to `user_config.cfg`.
    *   Edit `user_config.cfg` with your settings. The `comfyui_url` should be the address of your ComfyUI instance, accessible from within the Docker network (e.g., `http://host.docker.internal:8188` or your server's IP).

3.  **Build and run with Docker Compose:**
    ```bash
    docker-compose up --build
    ```
    The application will be available at `http://localhost:8088`.

## Configuration

The application is configured via the `user_config.cfg` file.

| Section   | Key                  | Description                                                                 | Default (from sample) |
| :-------- | :------------------- | :-------------------------------------------------------------------------- | :-------------------- |
| `[frame]` | `reload_interval`    | How often the gallery page reloads in milliseconds.                         | `30000`               |
| `[frame]` | `auto_regen`         | Enable or disable automatic image generation (`True`/`False`).              | `True`                |
| `[frame]` | `regen_time`         | The time to automatically generate a new image (HH:MM).                     | `03:00`               |
| `[frame]` | `port`               | The port the Flask application will run on.                                 | `5000`                |
| `[frame]` | `create_requires_auth` | Require a password to create images (`True`/`False`).                       | `False`               |
| `[frame]` | `password_for_auth`  | The password to use for image creation if authentication is enabled.        | `create`              |
| `[comfyui]` | `comfyui_url`        | The URL of your ComfyUI instance.                                           | `http://comfyui`      |
| `[comfyui]` | `models`             | A comma-separated list of models to use for generation.                     | `zavychromaxl_v100.safetensors,ponyDiffusionV6XL_v6StartWithThisOne.safetensors` |
| `[comfyui]` | `output_dir`         | The directory to save generated images to.                                  | `./output/`           |
| `[comfyui]` | `prompt`             | The prompt to use for generating a random prompt for stable diffusion.      | `"Generate a random detailed prompt for stable diffusion."` |
| `[comfyui]` | `width`              | The width of the generated image.                                           | `1568`                |
| `[comfyui]` | `height`             | The height of the generated image.                                          | `672`                 |
| `[comfyui]` | `topics`             | A comma-separated list of topics to generate prompts from.                  |                       |
| `[comfyui]` | `FLUX`               | Enable FLUX models (`True`/`False`).                                        | `False`               |
| `[comfyui]` | `ONLY_FLUX`          | Only use FLUX models (`True`/`False`).                                      | `False`               |
| `[comfyui:flux]` | `models`       | A comma-separated list of FLUX models.                                      | `flux1-dev-Q4_0.gguf,flux1-schnell-Q4_0.gguf` |
| `[openwebui]` | `base_url`         | The base URL for OpenWebUI.                                                 | `https://openwebui`   |
| `[openwebui]` | `api_key`          | The API key for OpenWebUI.                                                  | `sk-`                 |
| `[openwebui]` | `models`           | A comma-separated list of models for OpenWebUI.                             | `llama3:latest,cogito:14b,gemma3:12b` |

## Usage

*   **Gallery:** Open your browser to `http://<server_ip>:<port>` to see the gallery of generated images.
*   **Create Image:** Navigate to `/create` to manually trigger image generation.

## Dependencies

*   Flask
*   comfy_api_simplified
*   APScheduler
*   Pillow
*   And others, see `requirements.txt`.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

This project is unlicensed.