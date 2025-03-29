# Use an official Python image as a base
FROM python:3.11

# Set the working directory in the container
WORKDIR /app

# Copy project files into the container
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose any necessary ports (optional, if running a web app)
EXPOSE 5000

# Define the command to run the application
CMD ["python", "ai_frame_image_server.py"]
