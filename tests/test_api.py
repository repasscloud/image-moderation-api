import io
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app


class FakeEngine:
    def __init__(self, name, fail=False, delay=0):
        self.name, self.fail, self.delay = name, fail, delay
        self.loads = 0

    def load(self):
        self.loads += 1

    def scan(self, data):
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("private/path secret-password")
        return (
            {"detections": []}
            if self.name == "nudenet"
            else {
                "classification": False,
                "probabilities": [{"high": 0.1, "medium": 0.2, "low": 0.3, "neutral": 0.7}],
            }
        )

    def close(self):
        pass


def image_bytes(fmt="PNG", size=(32, 32)):
    b = io.BytesIO()
    Image.new("RGB", size, "green").save(b, format=fmt)
    return b.getvalue()


def client(settings=None, engines=None):
    return TestClient(
        create_app(
            settings or Settings(_env_file=None),
            engines or {"nudenet": FakeEngine("nudenet"), "nsfw": FakeEngine("nsfw")},
        )
    )


def scan(c, path="/v1/scan", data=None, headers=None, image=None):
    return c.post(
        path,
        files={"file": ("image.png", image if image is not None else image_bytes(), "image/png")},
        data=data,
        headers=headers,
    )


@pytest.mark.parametrize("path", ["/v1/scan", "/v1/scan/nudenet", "/v1/scan/nsfw", "/v1/scan/arachnid"])
def test_shared_auth(path):
    with client(Settings(api_key="secret", _env_file=None)) as c:
        assert scan(c, path).status_code == 401
        assert scan(c, path, headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert scan(c, path + "?api_key=secret").status_code == 401
        assert scan(c, "/v1/scan/nudenet", headers={"Authorization": "Bearer secret"}).status_code == 200
        assert c.get("/health").status_code == 200


@pytest.mark.parametrize("key", [None, "", "   "])
def test_auth_disabled(key):
    with client(Settings(api_key=key, _env_file=None)) as c:
        assert scan(c).status_code == 200


@pytest.mark.parametrize(
    "username,password,enabled",
    [(None, None, False), ("u", None, False), (None, "p", False), ("u", "p", True), (" ", " ", False)],
)
def test_arachnid_config(username, password, enabled):
    s = Settings(arachnid_api_username=username, arachnid_api_password=password, _env_file=None)
    assert s.arachnid_enabled is enabled
    assert "p" not in str(s.arachnid_api_password) or password is None


def test_scan_results_and_single_load():
    engines = {"nudenet": FakeEngine("nudenet"), "nsfw": FakeEngine("nsfw")}
    with client(engines=engines) as c:
        for _ in range(2):
            r = scan(c)
            assert r.status_code == 200
            assert r.json()["status"] == "completed"
            assert r.json()["results"]["arachnid"]["status"] == "disabled"
            assert r.json()["results"]["nsfw"]["classification"] is False
        assert all(e.loads == 1 for e in engines.values())
        assert c.get("/ready").json()["ready"] is True
        assert c.get("/v1/engines").json()["engines"]["arachnid"]["enabled"] is False


@pytest.mark.parametrize("selection", ["arachnid", "unknown", "nudenet,arachnid", ""])
def test_bad_selection(selection):
    with client() as c:
        assert scan(c, data={"engines": selection}).status_code == 422
        assert scan(c, "/v1/scan/arachnid").status_code == 422


def test_selection():
    with client() as c:
        r = scan(c, data={"engines": "nudenet"})
        assert r.json()["results"]["nsfw"]["status"] == "not_requested"


def test_partial_failure_sanitized():
    with client(engines={"nudenet": FakeEngine("nudenet", fail=True), "nsfw": FakeEngine("nsfw")}) as c:
        r = scan(c)
        assert r.status_code == 200
        assert r.json()["status"] == "partial"
        assert "secret-password" not in r.text
        assert r.json()["results"]["nudenet"]["status"] == "failed"


@pytest.mark.parametrize(
    "payload,code", [(b"not an image", 400), (image_bytes("GIF"), 415), (b"x" * (1024 * 1024 + 1), 413)]
)
def test_invalid_images(payload, code):
    with client(Settings(max_image_size_mb=1, _env_file=None)) as c:
        assert scan(c, image=payload).status_code == code


def test_pixel_limit():
    with client(Settings(max_image_pixels=100, _env_file=None)) as c:
        assert scan(c).status_code == 413


def test_concurrency_bound():
    with client(engines={"nudenet": FakeEngine("nudenet", delay=0.25), "nsfw": FakeEngine("nsfw")}) as c:
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(scan, c)
            time.sleep(0.08)
            second = scan(c)
            assert second.status_code == 503
            assert first.result().status_code == 200


def test_initialization_failure():
    e = FakeEngine("nudenet")

    def fail():
        raise RuntimeError("sensitive")

    e.load = fail
    with client(engines={"nudenet": e, "nsfw": FakeEngine("nsfw")}) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/ready").status_code == 503
        r = scan(c)
        assert r.json()["status"] == "partial"
        assert "sensitive" not in r.text
