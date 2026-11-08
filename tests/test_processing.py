import hashlib
import io
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app


class Engine:
    def __init__(self, result):
        self.result = result

    def load(self):
        pass

    def close(self):
        pass

    def scan(self, data):
        return self.result


class Malware:
    def __init__(self, classification="clean"):
        self.classification = classification
        self.seen = None

    def scan(self, data):
        self.seen = data
        return {
            "status": "completed",
            "classification": self.classification,
            "engineVersion": "synthetic",
            "signatureVersion": "synthetic",
        }

    def ready(self):
        return True


def settings(**kw):
    return Settings(
        _env_file=None,
        enable_processing=True,
        api_key="fictional-service-key-at-least-32-chars",
        arachnid_api_username="fictional-user",
        arachnid_api_password="fictional-pass",
        **kw,
    )


def engines(known="no-known-match"):
    return {
        "nudenet": Engine({"detections": []}),
        "nsfw": Engine({"is_nsfw": False}),
        "arachnid": Engine({"classification": known, "raw": {"private": "not returned"}}),
    }


def image():
    b = io.BytesIO()
    Image.new("RGB", (640, 480), "green").save(b, "PNG")
    return b.getvalue()


def post(c, data=None, job=None, auth=True):
    data = image() if data is None else data
    job = job or {
        "protocolVersion": 1,
        "jobId": str(uuid4()),
        "imageId": str(uuid4()),
        "purpose": "profile",
        "sourceSha256": hashlib.sha256(data).hexdigest(),
    }
    return c.post(
        "/v1/process",
        data={"job": json.dumps(job)},
        files={"file": ("upload.png", data, "image/png")},
        headers={"Authorization": "Bearer fictional-service-key-at-least-32-chars"} if auth else {},
    )


def decode(response):
    from email.parser import BytesParser
    from email.policy import default

    msg = BytesParser(policy=default).parsebytes(
        ("Content-Type: " + response.headers["content-type"] + "\r\nMIME-Version: 1.0\r\n\r\n").encode()
        + response.content
    )
    parts = {
        p.get_param("name", header="content-disposition"): p.get_payload(decode=True)
        for p in msg.iter_parts()
    }
    return json.loads(parts.pop("manifest")), parts


def test_success_original_scanned_and_variants_match_manifest():
    malware = Malware()
    with TestClient(create_app(settings(), engines(), malware=malware)) as c:
        r = post(c)
        assert r.status_code == 200
        manifest, parts = decode(r)
        assert malware.seen == image()
        assert set(parts) == {"display", "thumbnail"}
        assert "raw" not in manifest["results"]["arachnid"]
        assert manifest["sourceSha256"] == hashlib.sha256(image()).hexdigest()
        for v in manifest["variants"]:
            assert hashlib.sha256(parts[v["name"]]).hexdigest() == v["sha256"]
            assert len(parts[v["name"]]) == v["bytes"]
            with Image.open(io.BytesIO(parts[v["name"]])) as im:
                assert im.format == "WEBP"
                assert not im.getexif()
                assert list(im.size) == [v["width"], v["height"]]
        assert c.get("/ready").status_code == 200


@pytest.mark.parametrize("known", ["csam", "harmful-abusive-material", "test", "unknown"])
def test_specialist_or_unknown_never_returns_variants(known):
    with TestClient(create_app(settings(), engines(known), malware=Malware())) as c:
        manifest, parts = decode(post(c))
        assert not parts
        assert manifest["variants"] == []


def test_malware_precedes_any_decoder_or_model():
    with TestClient(create_app(settings(), engines(), malware=Malware("infected"))) as c:
        r = post(c, b"not an image")
        assert r.status_code == 200
        manifest, parts = decode(r)
        assert not parts
        assert manifest["results"]["malware"]["classification"] == "infected"
        assert manifest["results"]["nudenet"]["status"] == "not_requested"


def test_auth_and_source_hash():
    with TestClient(create_app(settings(), engines(), malware=Malware())) as c:
        assert post(c, auth=False).status_code == 401
        job = {
            "protocolVersion": 1,
            "jobId": str(uuid4()),
            "imageId": str(uuid4()),
            "purpose": "profile",
            "sourceSha256": "0" * 64,
        }
        assert post(c, job=job).status_code == 409
        assert post(c, b"invalid").status_code == 400


def test_processing_requires_all_configuration():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, enable_processing=True)
    with pytest.raises(ValidationError):
        settings(enable_nsfw=False)


def test_disabled_endpoint_and_drain(tmp_path):
    with TestClient(create_app(Settings(_env_file=None), engines(), malware=Malware())) as c:
        assert post(c).status_code == 404
    drain = tmp_path / "drain"
    with TestClient(create_app(settings(processing_drain_file=drain), engines(), malware=Malware())) as c:
        drain.touch()
        assert c.get("/ready").status_code == 503
        assert post(c).status_code == 503


def test_member_minimum_dimensions_preserved():
    small = io.BytesIO()
    Image.new("RGB", (199, 300), "green").save(small, "PNG")
    with TestClient(create_app(settings(), engines(), malware=Malware())) as c:
        response = post(c, small.getvalue())
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "image_too_small"


def test_failed_required_engine_cannot_prepare_variants():
    class FailedEngine(Engine):
        def scan(self, data):
            raise RuntimeError("fixture provider unavailable")

    fake = engines()
    fake["arachnid"] = FailedEngine({})
    with TestClient(create_app(settings(), fake, malware=Malware())) as c:
        manifest, parts = decode(post(c))
        assert manifest["results"]["arachnid"]["status"] == "failed"
        assert not parts and not manifest["variants"]


def test_small_image_never_reaches_models():
    class ForbiddenEngine(Engine):
        def scan(self, data):
            pytest.fail("Small image should be rejected before inference")

    small = io.BytesIO()
    Image.new("RGB", (199, 300), "green").save(small, "PNG")
    fake = {name: ForbiddenEngine({}) for name in ("nudenet", "nsfw", "arachnid")}
    with TestClient(create_app(settings(), fake, malware=Malware())) as c:
        assert post(c, small.getvalue()).status_code == 422


@pytest.mark.parametrize("version", [True, 1.0, "1", 2])
def test_protocol_version_is_strict(version):
    job = {
        "protocolVersion": version,
        "jobId": str(uuid4()),
        "imageId": str(uuid4()),
        "purpose": "profile",
        "sourceSha256": hashlib.sha256(image()).hexdigest(),
    }
    with TestClient(create_app(settings(), engines(), malware=Malware())) as c:
        assert post(c, job=job).status_code == 422


def test_processing_requires_long_inbound_service_key():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            enable_processing=True,
            api_key="short",
            arachnid_api_username="fixture-user",
            arachnid_api_password="fixture-password",
        )


def test_processing_openapi_declares_multipart_response():
    schema = create_app(settings(), engines(), Malware()).openapi()
    content = schema["paths"]["/v1/process"]["post"]["responses"]["200"]["content"]
    assert "multipart/form-data" in content
    assert "application/json" not in content


def test_cross_repository_fixture_export(tmp_path):
    import subprocess
    import sys

    output = tmp_path / "response"
    result = subprocess.run(
        [sys.executable, "scripts/export_processing_fixture.py", "--output", str(output)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert output.with_suffix(".bin").read_bytes()
    assert json.loads(output.with_suffix(".json").read_text())["contentType"].startswith(
        "multipart/form-data;"
    )
    again = subprocess.run(
        [sys.executable, "scripts/export_processing_fixture.py", "--output", str(output)],
        capture_output=True,
        text=True,
    )
    assert again.returncode != 0


@pytest.mark.parametrize("mode", ["P", "RGB", "L", "RGBA"])
def test_transparent_png_pixels_are_composited_on_white(mode):
    color = {"P": 0, "RGB": (255, 0, 0), "L": 0, "RGBA": (255, 0, 0, 0)}[mode]
    with Image.new(mode, (640, 480), color) as original:
        if mode == "P":
            original.putpalette([255, 0, 0] + [0, 0, 0] * 255)
        stream = io.BytesIO()
        save = {"transparency": {"P": 0, "RGB": (255, 0, 0), "L": 0}[mode]} if mode != "RGBA" else {}
        original.save(stream, "PNG", **save)
    with TestClient(create_app(settings(), engines(), malware=Malware())) as client:
        response = post(client, stream.getvalue())
    assert response.status_code == 200
    _, parts = decode(response)
    for payload in parts.values():
        with Image.open(io.BytesIO(payload)) as prepared:
            pixel = prepared.convert("RGB").getpixel((prepared.width // 2, prepared.height // 2))
            assert min(pixel) >= 250, (mode, pixel)
            assert "transparency" not in prepared.info
