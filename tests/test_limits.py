import asyncio
import time
import pytest
from app.config import Settings
from tests.test_api import FakeEngine, client, scan, image_bytes


def test_timeout_keeps_capacity_until_thread_done():
    with client(
        Settings(scan_timeout_seconds=0.04, _env_file=None),
        {"nudenet": FakeEngine("nudenet", delay=0.25), "nsfw": FakeEngine("nsfw")},
    ) as c:
        assert scan(c).status_code == 504
        assert scan(c).status_code == 503
        time.sleep(0.3)
        assert c.get("/ready").status_code == 200
        assert scan(c, "/v1/scan/nsfw").status_code == 200


def test_all_failed_status():
    with client(
        engines={"nudenet": FakeEngine("nudenet", fail=True), "nsfw": FakeEngine("nsfw", fail=True)}
    ) as c:
        r = scan(c)
        assert r.status_code == 502
        assert r.json()["status"] == "failed"


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_formats(fmt):
    with client() as c:
        assert scan(c, image=image_bytes(fmt)).status_code == 200


def test_no_disk_rollover(monkeypatch):
    from tempfile import SpooledTemporaryFile

    def reject_rollover(self):
        pytest.fail("Uploaded image was persisted")

    monkeypatch.setattr(SpooledTemporaryFile, "rollover", reject_rollover)
    # Valid PNG with harmless trailing bytes to exceed default 1 MiB spool threshold.
    with client() as c:
        assert scan(c, image=image_bytes() + b"x" * (2 * 1024 * 1024)).status_code == 200


def test_invalid_multipart_and_no_file():
    with client() as c:
        assert (
            c.post("/v1/scan", content=b"bad", headers={"Content-Type": "multipart/form-data"}).status_code
            == 400
        )
        assert c.post("/v1/scan", data={"engines": "nudenet"}).status_code == 400
        assert c.post("/v1/scan", files={"other": ("x.png", image_bytes())}).status_code == 422
        assert (
            c.post(
                "/v1/scan", files=[("file", ("a.png", image_bytes())), ("file", ("b.png", image_bytes()))]
            ).status_code
            == 400
        )


def test_no_engines():
    with client(Settings(enable_nudenet=False, enable_nsfw=False, _env_file=None)) as c:
        assert scan(c).status_code == 503
        assert c.get("/ready").json()["ready"] is True


def test_openapi_documents_auth_and_upload():
    with client() as c:
        spec = c.get("/openapi.json").json()
        operation = spec["paths"]["/v1/scan"]["post"]
        assert "multipart/form-data" in operation["requestBody"]["content"]
        assert operation["security"] == [{"BearerAuth": []}, {}]
        assert "401" in operation["responses"]


@pytest.mark.asyncio
async def test_chunked_request_limit_and_slow_upload():
    from app.middleware import ScanGuard

    async def downstream(scope, receive, send):
        pytest.fail("Oversize/slow body reached parser")

    for mode, status in [("large", 413), ("slow", 408)]:
        guard = ScanGuard(
            downstream, Settings(max_image_size_mb=1, upload_timeout_seconds=0.01, _env_file=None)
        )
        output = []

        async def receive():
            if mode == "slow":
                await asyncio.sleep(0.1)
            return {"type": "http.request", "body": b"x" * 700000, "more_body": True}

        async def send(message):
            output.append(message)

        await guard({"type": "http", "path": "/v1/scan", "headers": []}, receive, send)
        assert output[0]["status"] == status
        assert guard.active == 0


def test_extreme_aspect_ratio_rejected_before_native_preprocessing():
    with client(Settings(max_image_dimension=1024, _env_file=None)) as c:
        assert scan(c, image=image_bytes(size=(2048, 1))).status_code == 413


def test_unexpected_exception_does_not_escape_sanitized_boundary():
    from app.middleware import SanitizedErrors
    import asyncio

    async def broken(scope, receive, send):
        raise RuntimeError("password=secret /private/path")

    output = []

    async def send(message):
        output.append(message)

    asyncio.run(SanitizedErrors(broken)({"type": "http"}, None, send))
    assert output[0]["status"] == 500
    assert b"secret" not in output[1]["body"]


def test_openapi_all_failed_scan_schema():
    with client() as c:
        schema = c.get("/openapi.json").json()
        response = schema["paths"]["/v1/scan"]["post"]["responses"]["502"]
        assert response["content"]["application/json"]["schema"]["$ref"].endswith("/ScanResponse")
