import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.errors import APIError
from app.services.downloads import ImageDownloader, PublicNetworkBackend
from tests.test_api import image_bytes


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", ()),
        ("  ", ()),
        ("Images.Example.com, cdn.example.com", ("images.example.com", "cdn.example.com")),
        ("images.example.com,images.example.com", ("images.example.com",)),
    ],
)
def test_allowlist_config(value, expected):
    assert Settings(allowed_image_hosts=value, _env_file=None).allowed_image_hosts == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com",
        "*.example.com",
        "example.com:443",
        "example.com/path",
        "a.com,,b.com",
        "localhost",
        "127.0.0.1",
    ],
)
def test_bad_allowlist_config(value):
    with pytest.raises(ValidationError):
        Settings(allowed_image_hosts=value, _env_file=None)


def downloader(handler, **settings):
    d = ImageDownloader(Settings(_env_file=None, **settings))
    d.client.close()
    d.client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False)
    return d


def test_signed_query_preserved_and_no_auth_forwarded():
    raw = "https://images.example.com/a.png?token=secret%2Fvalue%2bX&x=one+two&x=three"

    def handler(request):
        assert str(request.url) == raw
        assert "authorization" not in request.headers
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, content=image_bytes())

    with downloader(handler, allowed_image_hosts="images.example.com") as d:
        assert d.fetch(raw) == image_bytes()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/a",
        "file:///etc/passwd",
        "https://u:p@example.com/a",
        "https://example.com:8443/a",
        "https://example.com/a#fragment",
        "https://127.0.0.1/a",
        "https://[::1]/a",
        "https://localhost/a",
        "https://example.com/\nsecret",
        " https://example.com/a",
    ],
)
def test_reject_invalid_urls_before_request(url):
    def forbidden(request):
        pytest.fail("Blocked URL reached transport")

    with downloader(forbidden) as d, pytest.raises(APIError):
        d.fetch(url)


@pytest.mark.parametrize(
    "host", ["evil.example.com", "images.example.com.evil.test", "notimages.example.com"]
)
def test_exact_host_allowlist(host):
    with downloader(
        lambda request: pytest.fail("Disallowed hostname fetched"), allowed_image_hosts="images.example.com"
    ) as d:
        with pytest.raises(APIError) as e:
            d.fetch("https://" + host + "/a")
        assert e.value.code == "image_host_not_allowed"


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "100.100.100.200",
        "0.0.0.0",
        "224.0.0.1",
        "192.168.1.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "64:ff9b::7f00:1",
        "2002:7f00:1::",
    ],
)
def test_block_nonpublic_dns_answers(monkeypatch, address):
    monkeypatch.setattr("app.services.downloads.resolve_addresses", lambda *a, **k: [address])
    with pytest.raises(APIError):
        PublicNetworkBackend().connect_tcp("images.example.com", 443)


def test_dns_pinned_at_actual_connection(monkeypatch):
    import httpcore

    calls = []
    monkeypatch.setattr("app.services.downloads.resolve_addresses", lambda *a, **k: ["93.184.216.34"])

    def connect(self, host, port, **kwargs):
        calls.append((host, port))
        return "connected"

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect)
    assert PublicNetworkBackend().connect_tcp("images.example.com", 443) == "connected"
    assert calls == [("93.184.216.34", 443)]


@pytest.mark.parametrize("code", [301, 302, 307, 308, 401, 403, 404, 429, 500])
def test_http_failure_sanitized(code):
    with downloader(
        lambda request: httpx.Response(
            code, headers={"Location": "http://127.0.0.1/secret"}, text="token=secret"
        )
    ) as d:
        with pytest.raises(APIError) as e:
            d.fetch("https://images.example.com/a?token=secret")
        assert "secret" not in str(e.value.body())


def test_download_size_limit():
    with downloader(
        lambda request: httpx.Response(200, content=b"x" * (1024 * 1024 + 1)), max_image_size_mb=1
    ) as d:
        with pytest.raises(APIError) as e:
            d.fetch("https://images.example.com/a")
        assert e.value.status_code == 413


def test_download_timeout():
    def handler(request):
        raise httpx.ReadTimeout("https://example.com/?token=secret")

    with downloader(handler) as d, pytest.raises(APIError) as e:
        d.fetch("https://images.example.com/a")
    assert e.value.status_code == 504
    assert "secret" not in str(e.value.body())


def test_mixed_dns_answers_are_rejected(monkeypatch):
    monkeypatch.setattr(
        "app.services.downloads.resolve_addresses", lambda *a, **k: ["93.184.216.34", "127.0.0.1"]
    )
    with pytest.raises(APIError):
        PublicNetworkBackend().connect_tcp("images.example.com", 443)


@pytest.mark.parametrize("ip", ["fec0::1", "ff0e::1"])
def test_site_local_and_multicast_are_not_public(ip):
    from app.services.downloads import is_public_address

    assert not is_public_address(ip)


def test_download_cookie_is_not_reused():
    def handler(request):
        assert "cookie" not in request.headers
        return httpx.Response(200, content=image_bytes(), headers={"Set-Cookie": "token=secret; Path=/"})

    with downloader(handler) as d:
        d.fetch("https://images.example.com/a")
        d.fetch("https://images.example.com/b")
        assert not d.client.cookies


def test_chunked_download_limit_and_close():
    class Stream(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            yield b"x" * 700000
            yield b"y" * 700000

        def close(self):
            self.closed = True

    stream = Stream()
    with downloader(lambda request: httpx.Response(200, stream=stream), max_image_size_mb=1) as d:
        with pytest.raises(APIError) as e:
            d.fetch("https://images.example.com/a")
        assert e.value.status_code == 413
    assert stream.closed


def test_slow_stream_total_deadline(monkeypatch):
    import app.services.downloads as module

    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"x"
            clock[0] = 31
            yield b"y"

    with downloader(lambda request: httpx.Response(200, stream=Stream())) as d:
        with pytest.raises(APIError) as e:
            d.fetch("https://images.example.com/a")
        assert e.value.status_code == 504


def test_content_encoding_rejected():
    with downloader(
        lambda request: httpx.Response(
            200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"not-gzip")
        )
    ) as d:
        with pytest.raises(APIError) as e:
            d.fetch("https://images.example.com/a")
        assert e.value.status_code == 415


def test_hosts_from_environment(monkeypatch):
    monkeypatch.setenv("ALLOWED_IMAGE_HOSTS", "images.example.com,cdn.example.com")
    assert Settings(_env_file=None).allowed_image_hosts == ("images.example.com", "cdn.example.com")


def test_absolute_deadline_covers_headers_and_body(monkeypatch):
    import httpcore
    import app.services.downloads as module

    clock = [10.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    class Stream:
        def read(self, max_bytes, timeout=None):
            assert timeout == 2.0
            return b"x"

        def close(self):
            pass

    stream = module.DeadlineStream(Stream(), 12.0)
    assert stream.read(1, timeout=30) == b"x"
    clock[0] = 12.1
    with pytest.raises(httpcore.ReadTimeout):
        stream.read(1, timeout=30)


def test_fallback_uses_only_validated_addresses(monkeypatch):
    import httpcore

    monkeypatch.setattr(
        "app.services.downloads.resolve_addresses", lambda *a, **k: ["2606:4700:4700::1111", "1.1.1.1"]
    )
    calls = []

    def connect(self, host, port, **kwargs):
        calls.append(host)
        if ":" in host:
            raise httpcore.ConnectError("IPv6 unreachable")
        return "connected"

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect)
    assert PublicNetworkBackend().connect_tcp("images.example.com", 443, timeout=5) == "connected"
    assert calls == ["2606:4700:4700::1111", "1.1.1.1"]


def test_dns_resolver_receives_absolute_budget(monkeypatch):
    import dns.resolver
    from app.services.downloads import resolve_addresses

    def resolve(self, name, **kwargs):
        assert kwargs["lifetime"] == 0.02 and kwargs["search"] is False
        raise dns.exception.Timeout("private domain details")

    monkeypatch.setattr(dns.resolver.Resolver, "resolve_name", resolve)
    with pytest.raises(APIError) as e:
        resolve_addresses("images.example.com", 0.02)
    assert e.value.status_code == 504
    assert "private domain" not in str(e.value.body())
