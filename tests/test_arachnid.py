import base64
import json

import httpx
import pytest

from app.config import Settings
from app.engines.arachnid_engine import ArachnidEngine
from app.errors import EngineError

HASH = base64.b64encode(bytes(range(32))).decode()


def engine(handler):
    e = ArachnidEngine(
        Settings(arachnid_api_username="user", arachnid_api_password="password", _env_file=None)
    )
    e.client = httpx.Client(transport=httpx.MockTransport(handler), auth=("user", "password"))
    e.hash_image = lambda _: (HASH, 98)
    return e


@pytest.mark.parametrize(
    "classification", ["no-known-match", "csam", "harmful-abusive-material", "test", "future-class"]
)
def test_shield_classifications_and_wire_contract(classification):
    def handler(request):
        assert str(request.url) == "https://shield.projectarachnid.com/v1/pdq"
        assert request.headers["authorization"] == "Basic " + base64.b64encode(b"user:password").decode()
        assert json.loads(request.content) == {"hashes": [HASH]}
        assert b"original image" not in request.content
        return httpx.Response(
            200, json={"scanned_hashes": {HASH: {"classification": classification, "match_type": None}}}
        )

    e = engine(handler)
    try:
        assert e.scan(b"original image")["classification"] == classification
    finally:
        e.close()


@pytest.mark.parametrize(
    "status,code", [(429, "upstream_rate_limited"), (401, "upstream_error"), (500, "upstream_error")]
)
def test_http_errors(status, code):
    e = engine(lambda request: httpx.Response(status, text="password sensitive path"))
    with pytest.raises(EngineError) as caught:
        e.scan(b"image")
    assert caught.value.code == code
    assert "password" not in caught.value.message
    e.close()


def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("sensitive details")

    e = engine(handler)
    with pytest.raises(EngineError) as caught:
        e.scan(b"image")
    assert caught.value.code == "upstream_timeout"
    e.close()


@pytest.mark.parametrize(
    "body", [{}, {"scanned_hashes": {}}, {"scanned_hashes": {HASH: {"classification": 42}}}, []]
)
def test_invalid_upstream(body):
    e = engine(lambda request: httpx.Response(200, json=body))
    with pytest.raises(EngineError) as caught:
        e.scan(b"image")
    assert caught.value.code == "upstream_response_invalid"
    e.close()
