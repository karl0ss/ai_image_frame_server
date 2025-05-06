from PIL import Image
import os

def generate_thumbnail(image_path: str, size=(500, 500)) -> str:
    """
    Generates a thumbnail for a given image with a max size of 500x500,
    and saves it in a 'thumbnails' subdirectory alongside the original.

    If the filename includes the word "image", the thumbnail will always be overwritten.

    Args:
        image_path (str): Path to the original image.
        size (tuple): Maximum width and height of the thumbnail.

    Returns:
        str: Path to the thumbnail image.
    """
    image_dir = os.path.dirname(image_path)
    thumbnail_dir = os.path.join(image_dir, "thumbnails")
    os.makedirs(thumbnail_dir, exist_ok=True)

    filename = os.path.basename(image_path)
    thumbnail_path = os.path.join(thumbnail_dir, filename)

    should_overwrite = "image" in filename.lower()

    if not os.path.exists(thumbnail_path) or should_overwrite:
        try:
            img = Image.open(image_path)
            img.thumbnail(size, Image.Resampling.LANCZOS)
            img.save(thumbnail_path, optimize=True)
            print(f"Created thumbnail: {thumbnail_path}")
        except Exception as e:
            print(f"Error creating thumbnail for {image_path}: {e}")
    else:
        print(f"Thumbnail already exists: {thumbnail_path}")

    return thumbnail_path
