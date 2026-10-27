"""Bounded HTTPS image downloads with DNS validation at the connection boundary."""

import ipaddress
import ssl
import time
from collections.abc import Iterator
from contextvars import ContextVar

import dns.exception
import dns.resolver

import httpcore
import httpx

from app.config import Settings
from app.errors import APIError

_deadline: ContextVar[float | None] = ContextVar("image_download_deadline", default=None)


_TRANSITION_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "2002::/16",
        "2001::/32",
        "::ffff:0:0/96",
    )
)


def is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(value.split("%")[0])
    return (
        address.is_global
        and not address.is_multicast
        and not getattr(address, "is_site_local", False)
        and not any(address in network for network in _TRANSITION_NETWORKS)
    )


def resolve_addresses(host: str, timeout: float) -> list[str]:
    """Resolve A/AAAA within one bounded DNS lifetime, without search suffixes."""
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass
    try:
        resolver = dns.resolver.Resolver()
        resolver.timeout = min(2.0, timeout)
        answers = resolver.resolve_name(host, lifetime=timeout, search=False)
        return list(dict.fromkeys(answers.addresses()))
    except dns.exception.Timeout:
        raise APIError(504, "image_download_timeout", "Image host resolution timed out.") from None
    except dns.exception.DNSException:
        raise APIError(502, "image_download_failed", "Image host could not be resolved.") from None


class DeadlineStream(httpcore.NetworkStream):
    """Enforce an absolute deadline even while HTTP headers/body arrive slowly."""

    def __init__(self, stream, deadline: float):
        self.stream, self.deadline = stream, deadline

    def timeout(self, requested: float | None) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise httpcore.ReadTimeout("Image download deadline exceeded")
        return remaining if requested is None else min(requested, remaining)

    def read(self, max_bytes: int, timeout=None) -> bytes:
        return self.stream.read(max_bytes, timeout=self.timeout(timeout))

    def write(self, buffer: bytes, timeout=None) -> None:
        self.stream.write(buffer, timeout=self.timeout(timeout))

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        stream = self.stream.start_tls(
            ssl_context, server_hostname=server_hostname, timeout=self.timeout(timeout)
        )
        return DeadlineStream(stream, self.deadline)

    def get_extra_info(self, info: str):
        return self.stream.get_extra_info(info)

    def close(self) -> None:
        self.stream.close()


class PublicNetworkBackend(httpcore.SyncBackend):
    """Pin checked DNS answers to numeric TCP destinations; preserve TLS SNI upstream."""

    def connect_tcp(self, host: str, port: int, timeout=None, local_address=None, socket_options=None):
        started = time.monotonic()
        deadline = _deadline.get()
        connect_deadline = started + (timeout if timeout is not None else 5)
        if deadline is not None:
            connect_deadline = min(connect_deadline, deadline)
        remaining = connect_deadline - time.monotonic()
        if remaining <= 0:
            raise APIError(504, "image_download_timeout", "Image download timed out.")
        addresses = resolve_addresses(host, remaining)
        if not addresses or any(not is_public_address(address) for address in addresses):
            raise APIError(
                422, "image_destination_blocked", "Image URL must resolve only to public addresses."
            )
        # Every fallback address was validated, and each receives a share of the remaining budget.
        for index, address in enumerate(addresses):
            remaining = connect_deadline - time.monotonic()
            if remaining <= 0:
                raise APIError(504, "image_download_timeout", "Image download timed out.")
            try:
                stream = super().connect_tcp(
                    address,
                    port,
                    timeout=remaining / (len(addresses) - index),
                    local_address=local_address,
                    socket_options=socket_options,
                )
                return DeadlineStream(stream, deadline) if deadline is not None else stream
            except (httpcore.ConnectError, httpcore.ConnectTimeout):
                if index == len(addresses) - 1:
                    raise
        raise APIError(502, "image_download_failed", "Image host could not be reached.")


class CoreResponseStream(httpx.SyncByteStream):
    def __init__(self, response: httpcore.Response):
        self.response = response

    def __iter__(self) -> Iterator[bytes]:
        yield from self.response.iter_stream()

    def close(self) -> None:
        self.response.close()


class PublicHTTPTransport(httpx.BaseTransport):
    """HTTPX transport using the documented HTTPCore custom-backend interface."""

    def __init__(self):
        self.pool = httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=PublicNetworkBackend(),
            max_connections=1,
            max_keepalive_connections=0,
            retries=0,
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        token = _deadline.set(request.extensions.get("image_deadline"))
        try:
            response = self.pool.handle_request(
                httpcore.Request(
                    method=request.method,
                    url=httpcore.URL(
                        scheme=request.url.raw_scheme,
                        host=request.url.raw_host,
                        port=request.url.port,
                        target=request.url.raw_path,
                    ),
                    headers=request.headers.raw,
                    content=request.stream,
                    extensions=request.extensions,
                )
            )
        finally:
            _deadline.reset(token)
        return httpx.Response(
            response.status,
            headers=response.headers,
            stream=CoreResponseStream(response),
            extensions=response.extensions,
        )

    def close(self) -> None:
        self.pool.close()


class ImageDownloader:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.Client(
            transport=PublicHTTPTransport(),
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(
                settings.url_download_timeout_seconds,
                connect=5,
                read=min(5, settings.url_download_timeout_seconds),
            ),
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        self.client.close()

    def validate_url(self, value: str) -> httpx.URL:
        try:
            if not value or len(value) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in value):
                raise ValueError()
            url = httpx.URL(value)
            if (
                url.scheme != "https"
                or not url.host
                or url.port not in (None, 443)
                or url.userinfo
                or "#" in value
                or "\\" in value
            ):
                raise ValueError()
            # Reject local literals without performing any HTTP request (also checked at DNS connect).
            try:
                literal = ipaddress.ip_address(url.host)
            except ValueError:
                literal = None
            if url.host.lower().rstrip(".") == "localhost" or (
                literal is not None and not is_public_address(str(literal))
            ):
                raise ValueError()
        except (ValueError, httpx.InvalidURL):
            raise APIError(
                422,
                "invalid_image_url",
                "Provide a public HTTPS image URL on port 443 without URL credentials or fragments.",
            ) from None
        # Do not normalize away trailing dots: exact configured hostnames only.
        if (
            self.settings.allowed_image_hosts
            and url.raw_host.decode("ascii").lower() not in self.settings.allowed_image_hosts
        ):
            raise APIError(422, "image_host_not_allowed", "Image URL hostname is not allowed.")
        return url

    def fetch(self, value: str) -> bytes:
        url = self.validate_url(value)
        deadline = time.monotonic() + self.settings.url_download_timeout_seconds
        self.client.cookies.clear()
        try:
            with self.client.stream(
                "GET",
                url,
                headers={"Accept": "image/jpeg,image/png,image/webp", "Accept-Encoding": "identity"},
                extensions={"image_deadline": deadline},
            ) as response:
                if time.monotonic() >= deadline:
                    raise APIError(504, "image_download_timeout", "Image download timed out.")
                if response.status_code != 200:
                    raise APIError(
                        502,
                        "image_download_failed",
                        "Image host did not return an image successfully; redirects are not followed.",
                    )
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise APIError(
                        415,
                        "image_encoding_unsupported",
                        "Compressed HTTP image responses are not supported.",
                    )
                length = response.headers.get("content-length")
                if length is not None:
                    try:
                        size = int(length)
                        if size < 0:
                            raise ValueError()
                    except ValueError:
                        raise APIError(
                            502, "image_download_failed", "Image host returned an invalid response."
                        ) from None
                    if size > self.settings.max_image_bytes:
                        raise APIError(413, "image_too_large", "Image exceeds the upload limit.")
                body = bytearray()
                for chunk in response.iter_bytes():
                    if time.monotonic() >= deadline:
                        raise APIError(504, "image_download_timeout", "Image download timed out.")
                    if len(body) + len(chunk) > self.settings.max_image_bytes:
                        raise APIError(413, "image_too_large", "Image exceeds the upload limit.")
                    body.extend(chunk)
                if time.monotonic() >= deadline:
                    raise APIError(504, "image_download_timeout", "Image download timed out.")
                return bytes(body)
        except (httpx.TimeoutException, httpcore.TimeoutException):
            raise APIError(504, "image_download_timeout", "Image download timed out.") from None
        except (httpx.HTTPError, httpcore.NetworkError, httpcore.ProtocolError):
            raise APIError(502, "image_download_failed", "Image host could not be reached.") from None

        finally:
            self.client.cookies.clear()
