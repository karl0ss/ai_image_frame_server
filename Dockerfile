# Use an official Python image as a base
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app
# Set version label
ARG VERSION="0.7.8"
LABEL version=$VERSION

# Copy project files into the container
COPY . /app
 

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Patch comfy_api_simplified: disable the 20s ws self-ping so long 20B (qwen) model
# loads don't stall Comfy past the keepalive window and kill the handshake mid-render
# (which made generate_image auto-retry and duplicate prompts)
RUN python3 -c "import comfy_api_simplified, pathlib; f = pathlib.Path(comfy_api_simplified.__file__).parent / 'comfy_api_wrapper.py'; s = f.read_text(); f.write_text(s.replace('websockets.connect(uri=self.ws_url.format(client_id))', 'websockets.connect(uri=self.ws_url.format(client_id), ping_interval=None, ping_timeout=90)'))"

# Expose any necessary ports (optional, if running a web app)
EXPOSE 5000

# Define the command to run the application
CMD ["python", "ai_frame_image_server.py"]
