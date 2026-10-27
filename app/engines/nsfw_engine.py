import io
from contextlib import nullcontext
from app.config import Settings


class NSFWEngine:
    def __init__(self, settings: Settings):
        self.path = settings.model_cache / "freepik"
        self.dtype = settings.nsfw_dtype
        self.detector = None

    def load(self) -> None:
        import torch
        from nsfw_image_detector import NSFWDetector

        if not (self.path / "config.json").is_file():
            raise RuntimeError("Run model setup first")
        self.detector = NSFWDetector(
            model_name=str(self.path.resolve()), device="cpu", dtype=getattr(torch, self.dtype)
        )
        self.detector.model.eval()

    def scan(self, data: bytes) -> dict:
        import torch
        from PIL import Image, ImageOps

        # Same EXIF transpose and RGB conversion as the working reference script.
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            try:
                context = (
                    torch.autocast("cpu", dtype=torch.bfloat16) if self.dtype == "bfloat16" else nullcontext()
                )
                with context:
                    classification = bool(self.detector.is_nsfw(image))
                    probabilities = self.detector.predict_proba(image)
            finally:
                image.close()
        return {
            "classification": classification,
            "is_nsfw": classification,
            "probabilities": [
                {str(getattr(k, "value", k)): float(v) for k, v in row.items()} for row in probabilities
            ],
        }

    def close(self) -> None:
        self.detector = None
