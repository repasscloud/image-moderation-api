import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.config import Settings
from tests.test_api import client, image_bytes, scan

URL = "https://images.example.com/image.png?token=do-not-log-this"


def use_transport(c, handler):
    d = c.app.state.downloader
    d.client.close()
    d.client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False)


def test_url_default_engines_and_no_url_echo(capsys):
    with client() as c:
        use_transport(c, lambda request: httpx.Response(200, content=image_bytes()))
        r = c.post("/v1/scan/url", json={"url": URL})
        assert r.status_code == 200
        assert r.json()["filename"] is None
        assert r.json()["status"] == "completed"
        assert r.json()["results"]["nsfw"]["status"] == "completed"
        assert "do-not-log-this" not in r.text
    assert "do-not-log-this" not in capsys.readouterr().err


def test_url_selection():
    with client() as c:
        use_transport(c, lambda request: httpx.Response(200, content=image_bytes()))
        r = c.post("/v1/scan/url", json={"url": URL, "engines": ["nudenet"]})
        assert r.json()["results"]["nsfw"]["status"] == "not_requested"
        assert c.post("/v1/scan/url", json={"url": URL, "engines": ["arachnid"]}).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"url": URL, "engines": []},
        {"url": URL, "engines": ["fake"]},
        {"url": URL, "extra": "secret"},
        {"url": URL, "engines": ""},
    ],
)
def test_invalid_json(payload):
    with client() as c:
        r = c.post("/v1/scan/url", json=payload)
        assert r.status_code == 422
        assert "do-not-log-this" not in r.text


def test_url_auth_before_download():
    with client(Settings(api_key="secret", _env_file=None)) as c:
        use_transport(c, lambda request: httpx.Response(200, content=image_bytes()))
        assert c.post("/v1/scan/url", json={"url": URL}).status_code == 401
        assert (
            c.post("/v1/scan/url", json={"url": URL}, headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
        assert (
            c.post("/v1/scan/url", json={"url": URL}, headers={"Authorization": "Bearer secret"}).status_code
            == 200
        )


@pytest.mark.parametrize(
    "data,status", [(b"not-image", 400), (image_bytes("GIF"), 415), (image_bytes(), 413)]
)
def test_downloaded_image_validation(data, status):
    settings = Settings(max_image_pixels=10, _env_file=None) if status == 413 else Settings(_env_file=None)
    with client(settings) as c:
        use_transport(c, lambda request: httpx.Response(200, content=data))
        assert c.post("/v1/scan/url", json={"url": URL}).status_code == status


def test_download_occupies_upload_capacity():
    def slow(request):
        time.sleep(0.2)
        return httpx.Response(200, content=image_bytes())

    with client() as c:
        use_transport(c, slow)
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(c.post, "/v1/scan/url", json={"url": URL})
            time.sleep(0.05)
            assert scan(c).status_code == 503
            assert first.result().status_code == 200


def test_json_body_bound():
    with client() as c:
        assert c.post("/v1/scan/url", content=b"x" * 16385).status_code == 413


def test_url_timeout_retains_capacity():
    def handler(request):
        time.sleep(0.15)
        return httpx.Response(200, content=image_bytes())

    with client(Settings(scan_timeout_seconds=0.03, _env_file=None)) as c:
        use_transport(c, handler)
        assert c.post("/v1/scan/url", json={"url": URL}).status_code == 504
        assert scan(c).status_code == 503
        time.sleep(0.2)
        assert scan(c).status_code == 200


def test_url_download_failure_and_openapi_schema():
    with client() as c:
        use_transport(c, lambda request: httpx.Response(403, text="do-not-log-this"))
        r = c.post("/v1/scan/url", json={"url": URL})
        assert r.status_code == 502
        assert r.json()["error"]["code"] == "image_download_failed"
        assert "do-not-log-this" not in r.text
        schema = c.get("/openapi.json").json()["paths"]["/v1/scan/url"]["post"]["responses"]["502"][
            "content"
        ]["application/json"]["schema"]
        assert len(schema["anyOf"]) == 2
