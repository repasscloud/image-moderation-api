from app.config import Settings


class NudeNetEngine:
    def __init__(self, settings: Settings):
        self.threshold = settings.nudenet_confidence_threshold
        self.detector = None

    def load(self) -> None:
        from nudenet import NudeDetector

        self.detector = NudeDetector()  # packaged 320n, unchanged library preprocessing/NMS
        self.detector.onnx_session.set_providers(["CPUExecutionProvider"])

    def scan(self, data: bytes) -> dict:
        import cv2
        import numpy as np

        # imread(path) in the reference uses IMREAD_COLOR, including EXIF orientation.
        # Supply the same BGR pixels in memory (bytes input would use IMREAD_UNCHANGED).
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("decode failed")
        detections = self.detector.detect(image)
        return {"detections": [d for d in detections if d["score"] >= self.threshold]}

    def close(self) -> None:
        self.detector = None
