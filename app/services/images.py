import io
import warnings
from PIL import Image, UnidentifiedImageError
from app.config import Settings
from app.errors import APIError


def validate_image(data: bytes, settings: Settings) -> None:
    if len(data) > settings.max_image_bytes:
        raise APIError(413, "image_too_large", "Image exceeds the upload limit.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise APIError(415, "unsupported_format", "Only JPEG, PNG and WebP are supported.")
                if max(image.size) > settings.max_image_dimension:
                    raise APIError(413, "dimension_limit", "Image dimensions exceed the limit.")
                if image.width * image.height > settings.max_image_pixels:
                    raise APIError(413, "pixel_limit", "Decoded image exceeds the pixel limit.")
                if getattr(image, "n_frames", 1) != 1:
                    raise APIError(415, "animated_image", "Only single-frame images are supported.")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()  # force actual decoding before passing bytes to native engines
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise APIError(413, "pixel_limit", "Decoded image exceeds the pixel limit.") from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise APIError(400, "invalid_image", "Image could not be decoded.") from None
