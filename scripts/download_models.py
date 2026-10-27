"""Explicit setup step. Runtime uses only this pinned local snapshot."""

import os
from pathlib import Path
from huggingface_hub import snapshot_download

MODEL_REVISION = "15b85477e4fd2000db76ae9aae0f89a72f95e2e3"

if __name__ == "__main__":
    cache = Path(os.environ.get("MODEL_CACHE", "model-cache"))
    snapshot_download(
        "Freepik/nsfw_image_detector",
        revision=MODEL_REVISION,
        local_dir=cache / "freepik",
        allow_patterns=["config.json", "model.safetensors", "README.md"],
    )
    (cache / "freepik" / "REVISION").write_text(MODEL_REVISION + "\n")
