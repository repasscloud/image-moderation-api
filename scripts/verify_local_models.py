"""Docker-local parity check. Generates harmless pixels; never calls Shield."""

import io
from contextlib import nullcontext
import json
import os
import tempfile
import urllib.request

import torch
from PIL import Image, ImageDraw, ImageOps
from nudenet import NudeDetector
from nsfw_image_detector import NSFWDetector


def main():
    nude = NudeDetector()
    nude.onnx_session.set_providers(["CPUExecutionProvider"])
    nsfw = NSFWDetector(
        model_name=os.environ["MODEL_CACHE"] + "/freepik",
        device="cpu",
        dtype=getattr(torch, os.environ.get("NSFW_DTYPE", "float32")),
    )
    image = Image.new("RGB", (256, 192), "#507080")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 40, 150, 160), fill="#40a050")
    draw.ellipse((100, 20, 240, 130), fill="#b0c0e0")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    data = buf.getvalue()
    # Temporary fixture is required only to compare against the original file-path script.
    with tempfile.NamedTemporaryFile(suffix=".png") as fixture:
        fixture.write(data)
        fixture.flush()
        detections = nude.detect(fixture.name)
    with Image.open(io.BytesIO(data)) as source:
        prepared = ImageOps.exif_transpose(source).convert("RGB")
        with (
            torch.autocast("cpu", dtype=getattr(torch, os.environ.get("NSFW_DTYPE", "float32")))
            if os.environ.get("NSFW_DTYPE") == "bfloat16"
            else nullcontext()
        ):
            classification = bool(nsfw.is_nsfw(prepared))
            probabilities = nsfw.predict_proba(prepared)
    probabilities = [{str(getattr(k, "value", k)): float(v) for k, v in p.items()} for p in probabilities]
    boundary = "local-model-verification"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.png"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    headers = {"Content-Type": "multipart/form-data; boundary=" + boundary}
    if os.environ.get("API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["API_KEY"]
    request = urllib.request.Request("http://127.0.0.1:8080/v1/scan", data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.load(response)
    assert result["status"] == "completed", result
    assert result["results"]["nudenet"]["detections"] == detections
    assert result["results"]["nsfw"]["classification"] == classification
    assert result["results"]["nsfw"]["probabilities"] == probabilities
    assert result["results"]["arachnid"]["status"] == "disabled"
    print(
        json.dumps(
            {
                "parity": "exact",
                "reference": {
                    "nudenet": detections,
                    "nsfw": {"classification": classification, "probabilities": probabilities},
                },
                "api": result,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
