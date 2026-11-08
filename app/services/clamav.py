"""Bounded local clamd protocol client. No upload data or raw scanner reply is logged."""

import socket
import struct
from datetime import datetime, timezone


class ClamAV:
    def __init__(self, settings):
        self.settings = settings

    def _receive(self, connection):
        result = bytearray()
        while not result.endswith(b"\0"):
            chunk = connection.recv(1024)
            if not chunk or len(result) + len(chunk) > 4096:
                raise ValueError("invalid scanner response")
            result.extend(chunk)
        return bytes(result[:-1]).decode("ascii", errors="strict")

    def command(self, command):
        with socket.create_connection(
            (self.settings.clamav_host, self.settings.clamav_port), self.settings.clamav_timeout_seconds
        ) as conn:
            conn.settimeout(self.settings.clamav_timeout_seconds)
            conn.sendall(command)
            return self._receive(conn)

    def version(self):
        raw = self.command(b"zVERSION\0")
        engine, signature, timestamp = raw.split("/", 2)
        when = datetime.strptime(timestamp.strip(), "%a %b %d %H:%M:%S %Y").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - when).total_seconds()
        if (
            not engine.startswith("ClamAV ")
            or not signature.isdigit()
            or age < -300
            or age > self.settings.clamav_max_signature_age_hours * 3600
        ):
            raise ValueError("scanner definitions stale or unknown")
        return {
            "engineVersion": engine,
            "signatureVersion": signature,
            "signatureTimestamp": when.isoformat(),
        }

    def ready(self):
        try:
            self.version()
            return self.command(b"zPING\0") == "PONG"
        except (OSError, ValueError):
            return False

    def scan(self, data):
        if len(data) > self.settings.max_image_bytes:
            return {"status": "unsupported", "error": {"code": "scan_limit"}}
        try:
            version = self.version()
            with socket.create_connection(
                (self.settings.clamav_host, self.settings.clamav_port), self.settings.clamav_timeout_seconds
            ) as conn:
                conn.settimeout(self.settings.clamav_timeout_seconds)
                conn.sendall(b"zINSTREAM\0")
                for offset in range(0, len(data), 65536):
                    chunk = data[offset : offset + 65536]
                    conn.sendall(struct.pack("!I", len(chunk)) + chunk)
                conn.sendall(b"\0\0\0\0")
                reply = self._receive(conn)
            after = self.version()
            if any(after[key] != version[key] for key in ("engineVersion", "signatureVersion")):
                return {"status": "failed", "error": {"code": "signature_changed"}, **after}
            if reply == "stream: OK":
                return {"status": "completed", "classification": "clean", **version}
            if reply.startswith("stream: ") and reply.endswith(" FOUND"):
                if "Heuristics.Limits.Exceeded" in reply:
                    return {"status": "unsupported", "error": {"code": "scan_limit"}, **version}
                # Detection name is bounded and kept out of routine logs.
                return {
                    "status": "completed",
                    "classification": "infected",
                    "detection": reply[8:-6][:200],
                    **version,
                }
            return {"status": "failed", "error": {"code": "scanner_error"}, **version}
        except (OSError, ValueError):
            return {"status": "failed", "error": {"code": "scanner_unavailable"}}
