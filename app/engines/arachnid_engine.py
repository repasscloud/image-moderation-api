import base64
import httpx
from app.config import Settings
from app.errors import EngineError


class ArachnidEngine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client: httpx.Client | None = None

    def load(self) -> None:
        self.client = httpx.Client(
            auth=httpx.BasicAuth(
                self.settings.arachnid_api_username.get_secret_value(),
                self.settings.arachnid_api_password.get_secret_value(),
            ),
            timeout=httpx.Timeout(self.settings.arachnid_timeout_seconds, connect=5),
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            follow_redirects=False,
            trust_env=False,
        )

    @staticmethod
    def hash_image(data: bytes) -> tuple[str, int]:
        import cv2
        import numpy as np
        import pdqhash

        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("decode failed")
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        vector, quality = pdqhash.compute(image)
        if len(vector) != 256:
            raise ValueError("invalid hash length")
        packed = np.packbits(np.asarray(vector, dtype=np.uint8)).tobytes()
        return base64.b64encode(packed).decode("ascii"), int(quality)

    def scan(self, data: bytes) -> dict:
        encoded, quality = self.hash_image(data)
        try:
            # Bound upstream body too. No retries; never forward upstream error bodies.
            with self.client.stream(
                "POST", "https://shield.projectarachnid.com/v1/pdq", json={"hashes": [encoded]}
            ) as response:
                if response.status_code == 429:
                    raise EngineError("upstream_rate_limited", "Shield rate limit reached; retry later.")
                if response.status_code != 200:
                    raise EngineError("upstream_error", "Shield request failed.")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 1024 * 1024:
                        raise EngineError("upstream_response_invalid", "Shield response was invalid.")
            import json

            raw = json.loads(body)
            match = raw["scanned_hashes"][encoded]
            if not isinstance(match["classification"], str):
                raise ValueError("invalid classification")
            return {
                "classification": match["classification"],
                "match_type": match.get("match_type"),
                "pdq_quality": quality,
                "raw": raw,
            }
        except httpx.TimeoutException:
            raise EngineError("upstream_timeout", "Shield request timed out.") from None
        except httpx.HTTPError:
            raise EngineError("upstream_error", "Shield request failed.") from None
        except (KeyError, TypeError, ValueError):
            raise EngineError("upstream_response_invalid", "Shield response was invalid.") from None

    def close(self) -> None:
        if self.client:
            self.client.close()
            self.client = None
