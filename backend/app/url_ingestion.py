"""Bounded public-web ingestion with SSRF-resistant redirect validation."""
from __future__ import annotations

import ipaddress
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from contextvars import ContextVar
from threading import BoundedSemaphore
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx
import httpcore

from .material_service import problem

MAX_BYTES = 2 * 1024 * 1024
TOTAL_TIMEOUT_SECONDS = 25.0
ALLOWED_CONTENT_TYPES = {"text/html", "text/plain", "text/markdown"}
_deadline: ContextVar[float | None] = ContextVar("public_fetch_deadline", default=None)
_resolver_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="public-url-dns")
_resolver_slots = BoundedSemaphore(16)


def _system_resolver(host: str) -> list[str]:
    return list({item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})


def _remaining_timeout(timeout: float | None, timeout_error):
    deadline = _deadline.get()
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise timeout_error("The public page exceeded its total time limit.")
    return remaining if timeout is None else min(timeout, remaining)


def _bounded_resolve(host: str, resolver) -> list[str]:
    deadline = _deadline.get()
    if deadline is None:
        return resolver(host)
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not _resolver_slots.acquire(timeout=max(0, remaining)):
        raise TimeoutError("DNS lookup exceeded the public page time limit.")
    try:
        future = _resolver_pool.submit(resolver, host)
    except Exception:
        _resolver_slots.release()
        raise
    future.add_done_callback(lambda _: _resolver_slots.release())
    try:
        return future.result(timeout=max(0, deadline - time.monotonic()))
    except FutureTimeout as exc:
        future.cancel()
        raise TimeoutError("DNS lookup exceeded the public page time limit.") from exc


def _public_addresses(host: str, resolver) -> list[str]:
    addresses = _bounded_resolve(host, resolver)
    if not addresses:
        raise ValueError("No address was resolved.")
    validated = []
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address.split("%")[0])
        except ValueError as exc:
            raise ValueError("An address could not be validated.") from exc
        if not ip.is_global:
            raise PermissionError("The hostname resolved to a non-public address.")
        validated.append(str(ip))
    return validated


class _DeadlineNetworkStream(httpcore.NetworkStream):
    """Apply the same absolute deadline to connect, TLS, reads, and writes."""
    def __init__(self, stream):
        self._stream = stream

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._stream.read(max_bytes, _remaining_timeout(timeout, httpcore.ReadTimeout))

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._stream.write(buffer, _remaining_timeout(timeout, httpcore.WriteTimeout))

    def close(self) -> None:
        self._stream.close()

    def start_tls(self, ssl_context: ssl.SSLContext, server_hostname: str | None = None,
                  timeout: float | None = None) -> httpcore.NetworkStream:
        stream = self._stream.start_tls(ssl_context, server_hostname,
                                        _remaining_timeout(timeout, httpcore.ConnectTimeout))
        return _DeadlineNetworkStream(stream)

    def get_extra_info(self, info: str):
        return self._stream.get_extra_info(info)


class _PinnedPublicBackend(httpcore.NetworkBackend):
    """Resolve and validate immediately before connecting to the selected IP.

    The URL authority remains the original hostname, so httpcore still sends
    its Host header and uses that hostname for TLS SNI/certificate validation.
    """
    def __init__(self, resolver):
        self._resolver = resolver
        self._backend = httpcore.SyncBackend()

    def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                    local_address: str | None = None, socket_options=None) -> httpcore.NetworkStream:
        try:
            addresses = _public_addresses(host, self._resolver)
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout(str(exc)) from exc
        except (OSError, ValueError, PermissionError) as exc:
            raise httpcore.ConnectError("Public host resolution was rejected.") from exc
        last_error = None
        for address in addresses:
            try:
                stream = self._backend.connect_tcp(
                    address, port,
                    timeout=_remaining_timeout(timeout, httpcore.ConnectTimeout),
                    local_address=local_address,
                    socket_options=socket_options,
                )
                return _DeadlineNetworkStream(stream)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise httpcore.ConnectError("No validated public address was available.")

    def connect_unix_socket(self, path: str, timeout: float | None = None,
                            socket_options=None) -> httpcore.NetworkStream:
        raise httpcore.ConnectError("Unix sockets are unavailable for public URL ingestion.")


class _CoreResponseStream(httpx.SyncByteStream):
    def __init__(self, response):
        self._response = response

    def __iter__(self):
        yield from self._response.iter_stream()

    def close(self):
        self._response.close()


class _PinnedHTTPTransport(httpx.BaseTransport):
    """Bridge HTTPX's public transport interface to a pinned httpcore pool."""
    def __init__(self, resolver):
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl.create_default_context(),
            max_connections=2,
            max_keepalive_connections=0,
            keepalive_expiry=0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=_PinnedPublicBackend(resolver),
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(scheme=request.url.raw_scheme, host=request.url.raw_host,
                             port=request.url.port, target=request.url.raw_path),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            response = self._pool.handle_request(core_request)
        except httpcore.TimeoutException as exc:
            error_type = httpx.TimeoutException
            for core_type, httpx_type in (
                (httpcore.ConnectTimeout, httpx.ConnectTimeout),
                (httpcore.ReadTimeout, httpx.ReadTimeout),
                (httpcore.WriteTimeout, httpx.WriteTimeout),
                (httpcore.PoolTimeout, httpx.PoolTimeout),
            ):
                if isinstance(exc, core_type):
                    error_type = httpx_type
                    break
            raise error_type(str(exc), request=request) from exc
        except httpcore.NetworkError as exc:
            error_type = httpx.NetworkError
            for core_type, httpx_type in (
                (httpcore.ConnectError, httpx.ConnectError),
                (httpcore.ReadError, httpx.ReadError),
                (httpcore.WriteError, httpx.WriteError),
                (httpcore.ProxyError, httpx.ProxyError),
            ):
                if isinstance(exc, core_type):
                    error_type = httpx_type
                    break
            raise error_type(str(exc), request=request) from exc
        except httpcore.ProtocolError as exc:
            error_type = httpx.ProtocolError
            if isinstance(exc, httpcore.LocalProtocolError): error_type = httpx.LocalProtocolError
            elif isinstance(exc, httpcore.RemoteProtocolError): error_type = httpx.RemoteProtocolError
            elif isinstance(exc, httpcore.UnsupportedProtocol): error_type = httpx.UnsupportedProtocol
            raise error_type(str(exc), request=request) from exc
        return httpx.Response(status_code=response.status, headers=response.headers,
                              stream=_CoreResponseStream(response), extensions=response.extensions,
                              request=request)

    def close(self):
        self._pool.close()


def validate_public_url(value: str, resolver=_system_resolver) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        problem("invalid_url", "Enter a valid public HTTP or HTTPS URL.")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        problem("invalid_url", "Only public HTTP and HTTPS URLs without embedded credentials are supported.")
    try:
        port = parsed.port
    except ValueError:
        problem("invalid_url", "Enter a valid public HTTP or HTTPS URL.")
    if port not in {None, 80, 443}:
        problem("url_port_forbidden", "Only standard HTTP and HTTPS ports are supported.")
    try:
        addresses = _public_addresses(parsed.hostname, resolver)
    except TimeoutError:
        problem("url_timeout", "The page address lookup exceeded the time limit.", 504)
    except PermissionError:
        problem("url_private_address", "Local and private-network pages cannot be imported.", 403)
    except (OSError, socket.gaierror, ValueError):
        problem("url_resolution_failed", "The page address could not be resolved.")
    return parsed.geturl()


class _ReadableHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.title = ""
        self.in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}: self.hidden += 1
        if tag == "title": self.in_title = True
        if tag in {"p", "div", "article", "section", "h1", "h2", "h3", "li", "br"}: self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.hidden: self.hidden -= 1
        if tag == "title": self.in_title = False

    def handle_data(self, data):
        if self.hidden: return
        text = " ".join(data.split())
        if not text: return
        if self.in_title: self.title = f"{self.title} {text}".strip()
        self.parts.append(text)

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in " ".join(self.parts).splitlines()]
        return "\n\n".join(line for line in lines if line).strip()


def extract_readable(content: bytes, content_type: str) -> tuple[str, str]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        problem("url_encoding_unsupported", "The page is not readable UTF-8 text.")
    if content_type in {"text/plain", "text/markdown"}:
        text = decoded.strip()
        if not text: problem("url_extraction_failed", "The page did not contain readable text.")
        return "Imported page", text
    parser = _ReadableHTML(); parser.feed(decoded)
    text = parser.text()
    if len(text) < 40:
        problem("url_extraction_failed", "The page did not contain enough readable text.")
    return parser.title or "Imported page", text


def fetch_public_page(value: str, *, resolver=_system_resolver, client: httpx.Client | None = None) -> dict:
    """Fetch one readable public page within a single total time budget.

    ``client`` is retained only for deterministic in-process mock transports;
    production callers omit it and use the DNS-pinned transport below.
    """
    deadline_token = _deadline.set(time.monotonic() + TOTAL_TIMEOUT_SECONDS)
    owned = client is None
    try:
        if client is None:
            client = httpx.Client(timeout=httpx.Timeout(12, connect=5), follow_redirects=False, trust_env=False,
                transport=_PinnedHTTPTransport(resolver), headers={"User-Agent": "Open-Learn-Material-Importer/1.0", "Accept": "text/html,text/plain,text/markdown", "Accept-Encoding": "identity"})
        current = value
        for _ in range(4):
            _remaining_timeout(None, httpx.ConnectTimeout)
            current = validate_public_url(current, resolver)
            remaining = _remaining_timeout(None, httpx.ConnectTimeout)
            timeout = httpx.Timeout(remaining, connect=min(5.0, remaining))
            with client.stream("GET", current, timeout=timeout) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location: problem("url_redirect_invalid", "The page returned an invalid redirect.")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in ALLOWED_CONTENT_TYPES:
                    problem("url_content_type_unsupported", "Only HTML, plain text, and Markdown pages can be imported.", 415)
                if response.headers.get("content-encoding", "identity").strip().lower() not in {"", "identity"}:
                    problem("url_content_encoding_unsupported", "Compressed pages are not supported for import.", 415)
                data = bytearray()
                for chunk in response.iter_bytes():
                    _remaining_timeout(None, httpx.ReadTimeout)
                    data.extend(chunk)
                    if len(data) > MAX_BYTES: problem("url_response_too_large", "The page exceeds the 2 MB import limit.", 413)
                _remaining_timeout(None, httpx.ReadTimeout)
                title, text = extract_readable(bytes(data), content_type)
                _remaining_timeout(None, httpx.ReadTimeout)
                return {"url": current, "title": title[:300], "text": text[:100000], "contentType": content_type}
        problem("url_redirect_limit", "The page redirected too many times.")
    except httpx.TimeoutException:
        problem("url_timeout", "The page took too long to respond.", 504)
    except httpx.HTTPStatusError as exc:
        problem("url_fetch_failed", f"The page returned HTTP {exc.response.status_code}.", 422)
    except httpx.HTTPError:
        problem("url_fetch_failed", "The page could not be downloaded.", 422)
    finally:
        if owned and client is not None: client.close()
        _deadline.reset(deadline_token)
