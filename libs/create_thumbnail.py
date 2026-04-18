import logging
import os
from PIL import Image

logger = logging.getLogger(__name__)

def generate_thumbnail(image_path: str, size=(500, 500)) -> str:
    """Generates a thumbnail for a given image with a max size of 500x500,
    and saves it in a 'thumbnails' subdirectory alongside the original.

    If the filename includes the word "image", the thumbnail will always be overwritten.

    Args:
        image_path: Path to the original image.
        size: Maximum width and height of the thumbnail.

    Returns:
        Path to the thumbnail image.
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
            logger.info("Created thumbnail: %s", thumbnail_path)
        except Exception as e:
            logger.warning("Error creating thumbnail for %s: %s", image_path, e)
    else:
        logger.debug("Thumbnail already exists: %s", thumbnail_path)

    return thumbnail_path