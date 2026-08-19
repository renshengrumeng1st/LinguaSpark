"""Image utility functions — shared across modules."""

import io
import base64
import logging
from PIL import Image
from typing import List, Dict, Any, Optional

logger = logging.getLogger("image_utils")

# Maximum dimension for images sent to the API.  Larger images are
# down-scaled to reduce base64 payload size and encoding time without
# materially affecting OCR/translation quality.
_MAX_IMAGE_DIMENSION = 1568


def _resize_if_needed(image: Image.Image) -> Image.Image:
    """Down-scale *image* if either dimension exceeds the API limit.

    Returns the original image unchanged if it's already small enough.
    Uses LANCZOS resampling for high-quality downscaling.
    """
    w, h = image.size
    if w <= _MAX_IMAGE_DIMENSION and h <= _MAX_IMAGE_DIMENSION:
        return image
    ratio = _MAX_IMAGE_DIMENSION / max(w, h)
    new_size = (max(1, int(w * ratio)), max(1, int(h * ratio)))
    logger.debug("Resizing image %dx%d -> %dx%d", w, h, *new_size)
    return image.resize(new_size, Image.Resampling.LANCZOS)


def image_to_base64_png(image: Image.Image) -> str:
    """Convert a PIL Image to a base64-encoded PNG string.

    Large images are automatically down-scaled to keep payload sizes
    reasonable.  Handles RGBA and other modes by converting to RGBA
    first (PNG supports alpha channel).
    """
    image = _resize_if_needed(image)
    buf = io.BytesIO()
    if image.mode == "RGBA":
        image.save(buf, format="PNG")
    else:
        image.convert("RGBA").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def build_image_content(
    image: Image.Image,
    text: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build a multimodal content list with a base64 image and optional text.

    Uses the standard OpenAI vision API format (image_url with data URI).
    """
    img_b64 = image_to_base64_png(image)
    content: List[Dict[str, Any]] = [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}",
            },
        }
    ]
    if text:
        content.insert(0, {"type": "text", "text": text})
    return content
