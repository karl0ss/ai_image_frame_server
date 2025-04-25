import os
from PIL import Image

# Define paths
input_folder = "output"
thumbs_folder = "output/thumbnails"
thumb_width = 500

# Create the thumbs folder if it doesn't exist
os.makedirs(thumbs_folder, exist_ok=True)

# Supported image extensions
image_extensions = (".png", ".jpg", ".jpeg", ".webp")

# Loop through files
for filename in os.listdir(input_folder):
    if filename.lower().endswith(image_extensions):
        input_path = os.path.join(input_folder, filename)
        output_path = os.path.join(thumbs_folder, filename)

        try:
            with Image.open(input_path) as img:
                # Maintain aspect ratio
                img.thumbnail((thumb_width, img.height), Image.LANCZOS)
                img.save(output_path)
                print(f"✅ Thumbnail saved: {output_path}")
        except Exception as e:
            print(f"❌ Error processing {filename}: {e}")
