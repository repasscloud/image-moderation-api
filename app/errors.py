class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


class EngineError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
