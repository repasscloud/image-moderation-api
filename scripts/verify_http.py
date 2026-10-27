"""Local HTTP smoke checks; explicitly excludes external Shield transmission."""

import io
import json
import os
import subprocess
import time
from pathlib import Path

import httpx
from PIL import Image


def main():
    base = "http://127.0.0.1:8080"
    with httpx.Client(timeout=150) as c:
        assert c.get(base + "/health").json() == {"status": "ok"}
        assert c.get(base + "/ready").json()["ready"] is True
        statuses = {}
        for fmt in ("JPEG", "PNG", "WEBP"):
            buf = io.BytesIO()
            Image.new("RGB", (64, 64), "green").save(buf, format=fmt)
            r = c.post(base + "/v1/scan", files={"file": ("fixture." + fmt.lower(), buf.getvalue())})
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "completed"
            statuses[fmt] = r.status_code
        assert c.post(base + "/v1/scan/arachnid", files={"file": ("test.png", b"invalid")}).status_code == 422
    # A separate throwaway container verifies actual server authentication with NudeNet.
    env = dict(os.environ, API_KEY=os.urandom(32).hex())
    name = "image-moderation-auth-check"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            "127.0.0.1:8081:8080",
            "-e",
            "API_KEY",
            "-e",
            "ENABLE_NSFW=false",
            "--cpus",
            "2",
            "--memory",
            "2g",
            "image-moderation-api-moderation-api",
        ],
        env=env,
        check=True,
        capture_output=True,
    )
    try:
        with httpx.Client(timeout=30) as c:
            for _ in range(60):
                try:
                    if c.get("http://127.0.0.1:8081/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise AssertionError("Auth check container failed startup")
            fixture = io.BytesIO()
            Image.new("RGB", (64, 64), "green").save(fixture, format="PNG")
            data = fixture.getvalue()
            missing = c.post("http://127.0.0.1:8081/v1/scan/nudenet", files={"file": ("fixture.png", data)})
            wrong = c.post(
                "http://127.0.0.1:8081/v1/scan/nudenet",
                headers={"Authorization": "Bearer wrong"},
                files={"file": ("fixture.png", data)},
            )
            correct = c.post(
                "http://127.0.0.1:8081/v1/scan/nudenet",
                headers={"Authorization": "Bearer " + env["API_KEY"]},
                files={"file": ("fixture.png", data)},
            )
            assert [missing.status_code, wrong.status_code, correct.status_code] == [401, 401, 200]
            assert correct.json()["results"]["nudenet"]["status"] == "completed"
            report = {
                "formats": statuses,
                "authentication": {"missing": 401, "incorrect": 401, "correct": 200},
                "external_calls": False,
            }
            Path("outputs").mkdir(exist_ok=True)
            Path("outputs/http-verification.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(report))
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=True, capture_output=True)


if __name__ == "__main__":
    main()
