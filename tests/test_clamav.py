import socket
import struct
import threading
from datetime import datetime, timezone, timedelta

import pytest
from app.config import Settings
from app.services.clamav import ClamAV


def serve(replies):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    captured = []

    def run():
        try:
            for expected, reply in replies:
                conn, _ = sock.accept()
                with conn:
                    cmd = bytearray()
                    while not cmd.endswith(b"\0"):
                        cmd.extend(conn.recv(1))
                    assert bytes(cmd) == expected
                    if expected == b"zINSTREAM\0":
                        data = bytearray()

                        def read(n):
                            out = bytearray()
                            while len(out) < n:
                                out.extend(conn.recv(n - len(out)))
                            return out

                        while True:
                            n = struct.unpack("!I", read(4))[0]
                            if not n:
                                break
                            data.extend(read(n))
                        captured.append(bytes(data))
                    conn.sendall(reply + b"\0")
        finally:
            sock.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return sock.getsockname()[1], captured, thread


def version(age=0):
    return (
        "ClamAV 1.5.4/12345/"
        + (datetime.now(timezone.utc) - timedelta(hours=age)).strftime("%a %b %d %H:%M:%S %Y")
    ).encode()


@pytest.mark.parametrize(
    "reply,status,classification",
    [
        (b"stream: OK", "completed", "clean"),
        (b"stream: Eicar-Test-Signature FOUND", "completed", "infected"),
        (b"stream: Heuristics.Limits.Exceeded FOUND", "unsupported", None),
        (b"private scanner failure ERROR", "failed", None),
    ],
)
def test_protocol_and_fail_closed(reply, status, classification):
    port, captured, thread = serve(
        [(b"zVERSION\0", version()), (b"zINSTREAM\0", reply), (b"zVERSION\0", version())]
    )
    client = ClamAV(Settings(_env_file=None, clamav_host="127.0.0.1", clamav_port=port))
    result = client.scan(b"original-bytes" * 6000)
    thread.join(2)
    assert result["status"] == status
    assert result.get("classification") == classification
    assert captured == [b"original-bytes" * 6000]
    assert result["signatureVersion"] == "12345"


def test_stale_signatures_do_not_scan_or_pass():
    port, captured, thread = serve([(b"zVERSION\0", version(73))])
    result = ClamAV(Settings(_env_file=None, clamav_host="127.0.0.1", clamav_port=port)).scan(b"data")
    thread.join(2)
    assert not captured
    assert result["status"] == "failed"


def test_scanner_unreachable():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    result = ClamAV(
        Settings(_env_file=None, clamav_host="127.0.0.1", clamav_port=port, clamav_timeout_seconds=0.1)
    ).scan(b"data")
    assert result["status"] == "failed"
    assert "classification" not in result


def test_signature_reload_during_scan_is_not_misattributed():
    before = version()
    after = before.replace(b"/12345/", b"/12346/")
    port, _, thread = serve(
        [(b"zVERSION\0", before), (b"zINSTREAM\0", b"stream: OK"), (b"zVERSION\0", after)]
    )
    result = ClamAV(Settings(_env_file=None, clamav_host="127.0.0.1", clamav_port=port)).scan(b"data")
    assert result["status"] == "failed"
    assert result["error"]["code"] == "signature_changed"
    thread.join(2)
