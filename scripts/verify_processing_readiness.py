"""Nonroot container control-mount smoke check with synthetic engine readiness.

Tests actual UID10001 filesystem access and FastAPI readiness/admission, not provider acceptance.
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

SOURCE = """
import os
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
class Engine:
 def load(self): pass
 def close(self): pass
class Malware:
 def ready(self): return True
assert os.getuid()==10001
settings=Settings(_env_file=None,enable_processing=True,api_key="synthetic-service-key-at-least-32-chars",arachnid_api_username="synthetic-user",arachnid_api_password="synthetic-password")
with TestClient(create_app(settings, {n:Engine() for n in ("nudenet","nsfw","arachnid")},malware=Malware())) as client:
 expected=int(os.environ["EXPECTED_STATUS"])
 assert client.get("/ready").status_code==expected
 if expected==503:
  assert client.post("/v1/process",headers={"Authorization":"Bearer synthetic-service-key-at-least-32-chars"}).status_code==503
 print("nonroot-readiness",expected,"passed")
"""


def main(image):
    with tempfile.TemporaryDirectory(prefix="swoovr-294-readiness-") as tmp:
        control = Path(tmp)
        control.chmod(0o755)
        for status in (200, 503):
            if status == 503:
                marker = control / "drain"
                marker.touch(mode=0o644)
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-i",
                    "--network",
                    "none",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:size=32m",
                    "--memory",
                    "256m",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--mount",
                    f"type=bind,source={control},target=/run/processor-control,readonly",
                    "-e",
                    f"EXPECTED_STATUS={status}",
                    "--entrypoint",
                    "python",
                    image,
                    "-",
                ],
                input=SOURCE.encode(),
                check=True,
                timeout=30,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    main(parser.parse_args().image)
