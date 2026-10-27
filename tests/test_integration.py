"""Real models; external Shield test requires separate explicit configuration."""

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


@pytest.mark.skipif(os.getenv("RUN_MODEL_INTEGRATION") != "1", reason="Explicit real-model opt-in required")
def test_real_local_models():
    from tests.test_api import image_bytes

    with TestClient(create_app(Settings(arachnid_api_username=None, arachnid_api_password=None))) as client:
        assert client.get("/ready").status_code == 200
        response = client.post(
            "/v1/scan",
            files={"file": ("synthetic.png", image_bytes(), "image/png")},
            headers={"Authorization": "Bearer " + os.getenv("API_KEY", "")},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"


@pytest.mark.skipif(
    os.getenv("RUN_ARACHNID_INTEGRATION") != "1",
    reason="Explicit external-image transmission opt-in required",
)
def test_real_shield():
    from app.engines.arachnid_engine import ArachnidEngine

    settings = Settings()
    path = os.environ.get("ARACHNID_TEST_IMAGE")
    if not settings.arachnid_enabled or not path:
        pytest.fail("Both Shield credentials and ARACHNID_TEST_IMAGE must be explicitly configured")
    data = Path(path).read_bytes()
    from app.services.images import validate_image

    validate_image(data, settings)
    e = ArachnidEngine(settings)
    e.load()
    try:
        assert isinstance(e.scan(data)["classification"], str)
    finally:
        e.close()
