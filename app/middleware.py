import asyncio
from starlette.responses import JSONResponse
from app.auth import authenticate
from app.errors import APIError


class ScanGuard:
    """Bound admission before reading or parsing any multipart body."""

    def __init__(self, app, settings):
        self.app, self.settings = app, settings
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/v1/scan"):
            return await self.app(scope, receive, send)
        admitted = False
        try:
            headers = dict(scope["headers"])
            authenticate(self.settings, headers.get(b"authorization", b"").decode("latin1"))
            if self.active >= self.settings.max_concurrent_scans:
                raise APIError(503, "busy", "Scan capacity is full; retry later.")
            self.active += 1
            admitted = True
            maximum = self.settings.max_image_bytes + 65536
            length = headers.get(b"content-length")
            if length:
                try:
                    length_int = int(length)
                except ValueError:
                    raise APIError(400, "invalid_request", "Invalid Content-Length.") from None
                if length_int < 0:
                    raise APIError(400, "invalid_request", "Invalid Content-Length.")
                if length_int > maximum:
                    raise APIError(413, "request_too_large", "Request exceeds the upload limit.")
            chunks, size = [], 0
            try:
                async with asyncio.timeout(self.settings.upload_timeout_seconds):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            raise APIError(400, "disconnected", "Upload was interrupted.")
                        chunk = message.get("body", b"")
                        size += len(chunk)
                        if size > maximum:
                            raise APIError(413, "request_too_large", "Request exceeds the upload limit.")
                        chunks.append(chunk)
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                raise APIError(408, "upload_timeout", "Upload timed out.") from None
            body = b"".join(chunks)
            chunks.clear()
            consumed = False

            async def replay():
                nonlocal consumed, body
                if not consumed:
                    consumed = True
                    payload, body = body, b""
                    return {"type": "http.request", "body": payload, "more_body": False}
                return await receive()

            await self.app(scope, replay, send)
        except APIError as exc:
            headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else {}
            if exc.status_code == 503:
                headers["Retry-After"] = "1"
            await JSONResponse(exc.body(), status_code=exc.status_code, headers=headers)(scope, receive, send)
        finally:
            if admitted:
                future = scope.get("scan_future")
                if future is not None and not future.done():
                    loop = asyncio.get_running_loop()

                    def release(_):
                        try:
                            loop.call_soon_threadsafe(self.release)
                        except RuntimeError:
                            pass

                    future.add_done_callback(release)
                else:
                    self.release()

    def release(self):
        self.active -= 1


class SanitizedErrors:
    """Prevent ASGI exception messages/tracebacks reaching server diagnostics."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False
        finished = False

        async def tracked(message):
            nonlocal started, finished
            if message["type"] == "http.response.start":
                started = True
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finished = True
            await send(message)

        try:
            await self.app(scope, receive, tracked)
        except Exception:
            import logging

            logging.getLogger("moderation").error("Unexpected request failure.")
            if not started:
                await JSONResponse(
                    APIError(500, "internal_error", "Request could not be processed.").body(), status_code=500
                )(scope, receive, send)
            elif not finished:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
