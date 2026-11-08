"""Export actual FastAPI multipart framing using SYNTHETIC engines/image, never providers.

Companion Worker tests consume OUTPUT.bin and OUTPUT.json. No model downloads,
credentials or network calls; refuses to overwrite existing output files.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


class SyntheticEngine:
    def __init__(self, result):
        self.result = result

    def load(self):
        pass

    def close(self):
        pass

    def scan(self, data):
        return self.result


class SyntheticMalware:
    def ready(self):
        return True

    def scan(self, data):
        return {
            "status": "completed",
            "classification": "clean",
            "engineVersion": "synthetic-only",
            "signatureVersion": "synthetic-only",
        }


def export(output):
    binary, metadata = Path(str(output) + ".bin"), Path(str(output) + ".json")
    if binary.exists() or metadata.exists():
        raise FileExistsError("Output already exists")
    settings = Settings(
        _env_file=None,
        enable_processing=True,
        api_key="synthetic-service-key-at-least-32-chars",
        arachnid_api_username="synthetic-user",
        arachnid_api_password="synthetic-password",
    )
    engines = {
        "nudenet": SyntheticEngine({"detections": []}),
        "nsfw": SyntheticEngine({"is_nsfw": False}),
        "arachnid": SyntheticEngine({"classification": "no-known-match"}),
    }
    image = io.BytesIO()
    Image.new("RGB", (640, 480), "green").save(image, "PNG")
    data = image.getvalue()
    job = {
        "protocolVersion": 1,
        "jobId": str(uuid4()),
        "imageId": str(uuid4()),
        "sourceSha256": hashlib.sha256(data).hexdigest(),
        "purpose": "profile",
    }
    with TestClient(create_app(settings, engines, SyntheticMalware())) as client:
        response = client.post(
            "/v1/process",
            data={"job": json.dumps(job)},
            files={"file": ("synthetic.png", data, "image/png")},
            headers={"Authorization": "Bearer synthetic-service-key-at-least-32-chars"},
        )
    if response.status_code != 200:
        raise RuntimeError("Synthetic fixture request failed")
    with binary.open("xb") as stream:
        stream.write(response.content)
    with metadata.open("x") as stream:
        json.dump(
            {
                "contentType": response.headers["content-type"],
                "provenance": "synthetic image and fake engines; actual FastAPI multipart response",
            },
            stream,
        )
    print("Exported synthetic multipart fixture; no real providers or member images used.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        export(args.output)
    except (OSError, RuntimeError):
        raise SystemExit("Fixture export refused or failed; choose a fresh output basename.") from None
