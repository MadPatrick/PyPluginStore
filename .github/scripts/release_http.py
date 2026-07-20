"""Bounded, SSRF-resistant HTTPS downloads for release scanner automation."""

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import http.client
import ipaddress
import math
import re
import socket
import ssl
import sys
import urllib.parse


REDIRECT_STATUSES = {301, 302, 303, 307, 308}
SECRET_REQUEST_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "cookie2",
    "private-token",
}
HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
LOWER_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CONTENT_LENGTH_PATTERN = re.compile(r"^[0-9]+$")
INVALID_PERCENT_PATTERN = re.compile(r"%(?![0-9A-Fa-f]{2})")
CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
DEFAULT_STREAM_CHUNK_SIZE = 64 * 1024
MAX_DNS_ANSWERS = 64
HOST_LABEL_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


class ReleaseHttpError(Exception):
    """A categorized release-fetch failure safe for scanner diagnostics."""

    def __init__(self, reason, message="", *, status=None, url=None):
        self.reason = str(reason)
        self.status = status
        self.url = url
        super().__init__(message or self.reason)


class SystemResolver:
    """Resolve every stream address using the operating-system resolver."""

    def resolve(self, hostname, port):
        answers = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        addresses = []
        seen = set()
        for family, _kind, _protocol, _canonical_name, socket_address in answers:
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            address = socket_address[0]
            if address not in seen:
                seen.add(address)
                addresses.append(address)
        return addresses


class _ResponseHeaderMapping(Mapping):
    """Expose wire header pairs without hiding case-fold duplicates."""

    def __init__(self, pairs):
        self._pairs = tuple(pairs)

    def __getitem__(self, key):
        for name, value in self._pairs:
            if name == key:
                return value
        raise KeyError(key)

    def __iter__(self):
        return (name for name, _value in self._pairs)

    def __len__(self):
        return len(self._pairs)

    def items(self):
        return iter(self._pairs)


class _PinnedHttpsConnection(http.client.HTTPSConnection):
    """Connect to one validated IP while authenticating the URL hostname."""

    def __init__(
        self,
        connect_ip,
        server_hostname,
        port,
        timeout,
        context,
    ):
        super().__init__(
            server_hostname,
            port=port,
            timeout=timeout,
            context=context,
        )
        self._connect_ip = connect_ip
        self._server_hostname = server_hostname

    def connect(self):
        if self._tunnel_host is not None:
            raise RuntimeError("Pinned HTTPS connections do not support proxies.")

        address = ipaddress.ip_address(self._connect_ip)
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        endpoint = (
            (str(address), self.port, 0, 0)
            if family == socket.AF_INET6
            else (str(address), self.port)
        )
        raw_socket = socket.socket(family, socket.SOCK_STREAM)
        try:
            raw_socket.settimeout(self.timeout)
            raw_socket.connect(endpoint)
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self._server_hostname,
            )
        except Exception:
            raw_socket.close()
            self.sock = None
            raise


class _StdlibHttpsResponse:
    """Adapt an ``http.client`` response to the bounded reader contract."""

    def __init__(self, response, connection):
        self._response = response
        self._connection = connection
        self.status = response.status
        self.headers = _ResponseHeaderMapping(response.getheaders())
        self._closed = False

    def iter_bytes(self, chunk_size):
        while True:
            chunk = self._response.read(chunk_size)
            if not chunk:
                return
            yield chunk

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._response.close()
        finally:
            self._connection.close()


class PinnedHttpsTransport:
    """Direct stdlib HTTPS transport that never consults proxy settings."""

    def __init__(self, context=None):
        self.context = ssl.create_default_context() if context is None else context
        if not callable(getattr(self.context, "wrap_socket", None)):
            raise ValueError("context must provide wrap_socket().")

    def request(
        self,
        method,
        url,
        *,
        connect_ip,
        server_hostname,
        host_header,
        headers,
        connect_timeout,
        read_timeout,
    ):
        target = _validate_url(url)
        if method != "GET":
            raise ValueError("PinnedHttpsTransport only supports GET.")
        if (
            server_hostname != target.hostname
            or host_header != target.host_header
        ):
            raise ValueError("TLS and Host identities must match the URL.")
        try:
            pinned_address = str(ipaddress.ip_address(connect_ip))
        except ValueError as error:
            raise ValueError("connect_ip must be an IP address literal.") from error
        request_headers = _validate_request_headers(headers)
        parsed = urllib.parse.urlsplit(target.url)
        request_target = parsed.path or "/"
        if parsed.query:
            request_target += "?" + parsed.query

        connection = _PinnedHttpsConnection(
            pinned_address,
            target.hostname,
            target.port,
            connect_timeout,
            self.context,
        )
        try:
            connection.connect()
            connection.putrequest(
                method,
                request_target,
                skip_host=True,
                skip_accept_encoding=True,
            )
            connection.putheader("Host", target.host_header)
            for name, value in request_headers.items():
                connection.putheader(name, value)
            connection.endheaders()
            connection.sock.settimeout(read_timeout)
            response = connection.getresponse()
            return _StdlibHttpsResponse(response, connection)
        except Exception:
            connection.close()
            raise


@dataclass(frozen=True)
class DownloadResult:
    """Immutable bytes and verification details from one completed download."""

    data: bytes
    size: int
    sha256: str
    final_url: str
    redirects: int
    verified: bool


ReleaseDownload = DownloadResult


@dataclass(frozen=True)
class _ValidatedUrl:
    url: str
    hostname: str
    port: int
    host_header: str
    origin: tuple


def _http_error(reason, message, *, status=None, url=None):
    return ReleaseHttpError(
        reason,
        message,
        status=status,
        url=url,
    )


def _validate_url(url):
    """Validate an absolute credential-free HTTPS request target."""
    if not isinstance(url, str) or not url:
        raise _http_error("https_required", "An absolute HTTPS URL is required.")
    if (
        CONTROL_CHARACTER_PATTERN.search(url)
        or any(character.isspace() for character in url)
        or "\\" in url
        or "#" in url
        or INVALID_PERCENT_PATTERN.search(url)
    ):
        raise _http_error("invalid_url", "URL is not canonical.", url=url)
    try:
        parsed = urllib.parse.urlsplit(url)
        explicit_port = parsed.port
    except ValueError as error:
        raise _http_error("invalid_url", "URL authority is invalid.", url=url) from error
    if parsed.scheme.lower() != "https":
        raise _http_error("https_required", "An absolute HTTPS URL is required.", url=url)
    hostname = parsed.hostname
    if (
        not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or "*" in hostname
        or hostname.startswith(".")
        or hostname.endswith(".")
        or parsed.netloc.endswith(":")
    ):
        raise _http_error(
            "invalid_url",
            "URL must have a canonical credential-free authority.",
            url=url,
        )
    port = 443 if explicit_port is None else explicit_port
    if not 1 <= port <= 65535:
        raise _http_error("invalid_url", "URL port is invalid.", url=url)
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise _http_error("invalid_url", "URL hostname is invalid.", url=url) from error
    try:
        ipaddress.ip_address(ascii_hostname)
        hostname_is_ip = True
    except ValueError:
        hostname_is_ip = False
    if (
        not ascii_hostname
        or CONTROL_CHARACTER_PATTERN.search(ascii_hostname)
        or "%" in ascii_hostname
        or len(ascii_hostname) > 253
        or (
            not hostname_is_ip
            and any(
                not HOST_LABEL_PATTERN.fullmatch(label)
                for label in ascii_hostname.split(".")
            )
        )
    ):
        raise _http_error("invalid_url", "URL hostname is invalid.", url=url)

    host_name = (
        "[" + ascii_hostname + "]"
        if ":" in ascii_hostname
        else ascii_hostname
    )
    host_header = host_name
    if explicit_port is not None:
        host_header += ":" + str(explicit_port)
    return _ValidatedUrl(
        url=url,
        hostname=ascii_hostname,
        port=port,
        host_header=host_header,
        origin=("https", ascii_hostname, port),
    )


def _validate_origin_allowlist(allowed_origins):
    """Return exact HTTPS origins from reviewed configuration."""
    if allowed_origins is None:
        return set()
    if isinstance(allowed_origins, (str, bytes)) or not isinstance(
        allowed_origins, (list, tuple, set, frozenset)
    ):
        raise _http_error(
            "invalid_origin_allowlist",
            "Origin allowlist must be a collection of exact HTTPS origins.",
        )

    validated = set()
    for origin in allowed_origins:
        if (
            not isinstance(origin, str)
            or not origin
            or CONTROL_CHARACTER_PATTERN.search(origin)
            or any(character.isspace() for character in origin)
            or "\\" in origin
            or "?" in origin
            or "#" in origin
        ):
            raise _http_error(
                "invalid_origin_allowlist",
                "Origin allowlist contains an invalid value.",
            )
        try:
            parsed = urllib.parse.urlsplit(origin)
            explicit_port = parsed.port
        except ValueError as error:
            raise _http_error(
                "invalid_origin_allowlist",
                "Origin allowlist contains an invalid authority.",
            ) from error
        hostname = parsed.hostname
        if (
            parsed.scheme.lower() != "https"
            or not parsed.netloc
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or "*" in hostname
            or hostname.startswith(".")
            or hostname.endswith(".")
            or parsed.netloc.endswith(":")
        ):
            raise _http_error(
                "invalid_origin_allowlist",
                "Origin allowlist values must be exact HTTPS origins.",
            )
        port = 443 if explicit_port is None else explicit_port
        if not 1 <= port <= 65535:
            raise _http_error(
                "invalid_origin_allowlist",
                "Origin allowlist contains an invalid port.",
            )
        try:
            ascii_hostname = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as error:
            raise _http_error(
                "invalid_origin_allowlist",
                "Origin allowlist contains an invalid hostname.",
            ) from error
        try:
            ipaddress.ip_address(ascii_hostname)
            hostname_is_ip = True
        except ValueError:
            hostname_is_ip = False
        if (
            not ascii_hostname
            or "%" in ascii_hostname
            or len(ascii_hostname) > 253
            or (
                not hostname_is_ip
                and any(
                    not HOST_LABEL_PATTERN.fullmatch(label)
                    for label in ascii_hostname.split(".")
                )
            )
        ):
            raise _http_error(
                "invalid_origin_allowlist",
                "Origin allowlist contains an invalid hostname.",
            )
        validated.add(("https", ascii_hostname, port))
    return validated


def _validate_request_headers(headers):
    """Validate caller headers and force an undecoded response body."""
    if headers is None:
        headers = {}
    if not isinstance(headers, Mapping):
        raise ValueError("headers must be a mapping.")

    result = {}
    seen = set()
    for name, value in headers.items():
        if not isinstance(name, str) or not HEADER_NAME_PATTERN.fullmatch(name):
            raise ValueError("HTTP header name is invalid.")
        lower_name = name.lower()
        if lower_name in seen:
            raise ValueError("HTTP header names must be unique ignoring case.")
        seen.add(lower_name)
        if not isinstance(value, str) or CONTROL_CHARACTER_PATTERN.search(value):
            raise ValueError("HTTP header value is invalid.")
        if lower_name == "host":
            raise ValueError("Host is controlled by the pinned transport.")
        if lower_name == "accept-encoding":
            continue
        result[name] = value
    result["Accept-Encoding"] = "identity"
    return result


def _strip_cross_origin_secrets(headers):
    """Remove credentials and ambient cookies on an approved origin change."""
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in SECRET_REQUEST_HEADERS
    }


def _response_headers(response, url):
    """Normalize response headers while rejecting case-fold duplicates."""
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        raise _http_error(
            "invalid_response_headers",
            "HTTP response headers are not a mapping.",
            url=url,
        )
    normalized = {}
    for name, value in headers.items():
        if not isinstance(name, str) or not HEADER_NAME_PATTERN.fullmatch(name):
            raise _http_error(
                "invalid_response_headers",
                "HTTP response contains an invalid header name.",
                url=url,
            )
        lower_name = name.lower()
        if lower_name in normalized:
            raise _http_error(
                "invalid_response_headers",
                "HTTP response contains duplicate headers.",
                url=url,
            )
        if not isinstance(value, str) or CONTROL_CHARACTER_PATTERN.search(value):
            raise _http_error(
                "invalid_response_headers",
                "HTTP response contains an invalid header value.",
                url=url,
            )
        normalized[lower_name] = value
    return normalized


def _is_rate_limited_response(status, headers):
    """Recognize explicit provider throttling without inspecting error bodies."""
    if status == 429:
        return True
    if status != 403:
        return False
    return any(
        headers.get(name) == "0"
        for name in ("x-ratelimit-remaining", "ratelimit-remaining")
    )


def _safe_close(response):
    """Best-effort close without masking the categorized fetch failure."""
    try:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    except Exception:
        pass


class SafeReleaseHttpClient:
    """Download one bounded artifact through DNS-pinned HTTPS hops."""

    def __init__(
        self,
        *,
        resolver=None,
        transport=None,
        max_redirects=3,
        connect_timeout=5.0,
        read_timeout=30.0,
        max_bytes=50 * 1024 * 1024,
        stream_chunk_size=DEFAULT_STREAM_CHUNK_SIZE,
    ):
        if type(max_redirects) is not int or max_redirects < 0:
            raise ValueError("max_redirects must be a non-negative integer.")
        for value, label in (
            (connect_timeout, "connect_timeout"),
            (read_timeout, "read_timeout"),
        ):
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(label + " must be a finite positive number.")
        if (
            type(max_bytes) is not int
            or max_bytes <= 0
            or max_bytes > sys.maxsize
        ):
            raise ValueError("max_bytes must be a positive integer.")
        if type(stream_chunk_size) is not int or stream_chunk_size <= 0:
            raise ValueError("stream_chunk_size must be a positive integer.")
        if resolver is None:
            resolver = SystemResolver()
        if transport is None:
            transport = PinnedHttpsTransport()
        if not callable(getattr(resolver, "resolve", None)):
            raise ValueError("resolver must provide resolve().")
        if not callable(getattr(transport, "request", None)):
            raise ValueError("transport must provide request().")

        self.resolver = resolver
        self.transport = transport
        self.max_redirects = max_redirects
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.max_bytes = max_bytes
        self.stream_chunk_size = min(stream_chunk_size, max_bytes)

    def _resolve_public_address(self, hostname, port, url):
        """Validate the entire DNS answer, then pin its first public address."""
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            literal = None
        if literal is not None:
            answers = [hostname]
        else:
            try:
                answers = self.resolver.resolve(hostname, port)
            except Exception as error:
                raise _http_error(
                    "dns_resolution_failed",
                    "DNS resolution failed.",
                    url=url,
                ) from error
        if isinstance(answers, (str, bytes)):
            answers = None
        try:
            answer_iterator = iter(answers) if answers is not None else iter(())
        except Exception as error:
            raise _http_error(
                "dns_resolution_failed",
                "DNS answer is invalid.",
                url=url,
            ) from error

        parsed_addresses = []
        for answer_index in range(MAX_DNS_ANSWERS + 1):
            try:
                answer = next(answer_iterator)
            except StopIteration:
                break
            except Exception as error:
                raise _http_error(
                    "dns_resolution_failed",
                    "DNS answer could not be read.",
                    url=url,
                ) from error
            if answer_index == MAX_DNS_ANSWERS:
                raise _http_error(
                    "dns_resolution_failed",
                    "DNS answer contains too many addresses.",
                    url=url,
                )
            if not isinstance(answer, str):
                raise _http_error(
                    "dns_resolution_failed",
                    "DNS answer contains a malformed address.",
                    url=url,
                )
            try:
                address = ipaddress.ip_address(answer)
            except ValueError as error:
                raise _http_error(
                    "dns_resolution_failed",
                    "DNS answer contains a malformed address.",
                    url=url,
                ) from error
            public_address = getattr(address, "ipv4_mapped", None) or address
            if not public_address.is_global or public_address.is_multicast:
                raise _http_error(
                    "non_public_address",
                    "DNS answer contains a non-public address.",
                    url=url,
                )
            parsed_addresses.append(str(address))
        if not parsed_addresses:
            raise _http_error(
                "dns_resolution_failed",
                "DNS answer is empty.",
                url=url,
            )
        return parsed_addresses[0]

    def _request(self, target, headers):
        """Open one pinned transport request without retrying unknown bytes."""
        connect_ip = self._resolve_public_address(
            target.hostname,
            target.port,
            target.url,
        )
        try:
            return self.transport.request(
                "GET",
                target.url,
                connect_ip=connect_ip,
                server_hostname=target.hostname,
                host_header=target.host_header,
                headers=dict(headers),
                connect_timeout=self.connect_timeout,
                read_timeout=self.read_timeout,
            )
        except TimeoutError as error:
            raise _http_error(
                "timeout",
                "HTTP request timed out.",
                url=target.url,
            ) from error
        except ReleaseHttpError:
            raise
        except Exception as error:
            raise _http_error(
                "transport_error",
                "HTTP transport failed.",
                url=target.url,
            ) from error

    def _read_download(
        self,
        response,
        target,
        response_headers,
        expected_sha256,
        expected_size,
        redirects,
    ):
        """Stream, hash, and verify one successful identity-encoded response."""
        content_encoding = response_headers.get("content-encoding")
        if content_encoding is not None and content_encoding.strip().lower() != "identity":
            raise _http_error(
                "unsupported_content_encoding",
                "Compressed response bodies are not accepted.",
                url=target.url,
            )

        declared_size = None
        content_length = response_headers.get("content-length")
        if content_length is not None:
            if not CONTENT_LENGTH_PATTERN.fullmatch(content_length):
                raise _http_error(
                    "invalid_content_length",
                    "Content-Length is malformed.",
                    url=target.url,
                )
            normalized_length = content_length.lstrip("0") or "0"
            maximum_length = str(self.max_bytes)
            if (
                len(normalized_length) > len(maximum_length)
                or (
                    len(normalized_length) == len(maximum_length)
                    and normalized_length > maximum_length
                )
            ):
                raise _http_error(
                    "content_too_large",
                    "Declared response size exceeds the limit.",
                    url=target.url,
                )
            declared_size = int(normalized_length)
            if declared_size > self.max_bytes:
                raise _http_error(
                    "content_too_large",
                    "Declared response size exceeds the limit.",
                    url=target.url,
                )
            if expected_size is not None and declared_size != expected_size:
                raise _http_error(
                    "length_mismatch",
                    "Declared response size differs from expected size.",
                    url=target.url,
                )

        iterator = getattr(response, "iter_bytes", None)
        if not callable(iterator):
            raise _http_error(
                "transport_error",
                "HTTP response does not expose a byte iterator.",
                url=target.url,
            )
        contents = bytearray()
        digest = hashlib.sha256()
        try:
            for chunk in iterator(self.stream_chunk_size):
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise _http_error(
                        "transport_error",
                        "HTTP response yielded non-byte data.",
                        url=target.url,
                    )
                chunk = bytes(chunk)
                if len(contents) + len(chunk) > self.max_bytes:
                    raise _http_error(
                        "content_too_large",
                        "Streamed response exceeds the size limit.",
                        url=target.url,
                    )
                contents.extend(chunk)
                digest.update(chunk)
        except ReleaseHttpError:
            raise
        except TimeoutError as error:
            raise _http_error(
                "timeout",
                "HTTP response stream timed out.",
                url=target.url,
            ) from error
        except Exception as error:
            raise _http_error(
                "transport_error",
                "HTTP response stream failed.",
                url=target.url,
            ) from error

        actual_size = len(contents)
        if declared_size is not None and actual_size != declared_size:
            raise _http_error(
                "length_mismatch",
                "Received bytes differ from Content-Length.",
                url=target.url,
            )
        if expected_size is not None and actual_size != expected_size:
            raise _http_error(
                "length_mismatch",
                "Received bytes differ from expected size.",
                url=target.url,
            )
        actual_digest = digest.hexdigest()
        if expected_sha256 and actual_digest != expected_sha256:
            raise _http_error(
                "digest_mismatch",
                "Received bytes differ from expected SHA-256.",
                url=target.url,
            )
        return DownloadResult(
            data=bytes(contents),
            size=actual_size,
            sha256=actual_digest,
            final_url=target.url,
            redirects=redirects,
            verified=bool(expected_sha256 or expected_size is not None),
        )

    def download(
        self,
        url,
        *,
        headers=None,
        allowed_origins=None,
        expected_sha256="",
        expected_size=None,
    ):
        """Download and verify one artifact through independently pinned hops."""
        if expected_sha256 is None:
            expected_sha256 = ""
        if not isinstance(expected_sha256, str) or (
            expected_sha256
            and not LOWER_SHA256_PATTERN.fullmatch(expected_sha256)
        ):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 digest.")
        if expected_size is not None and (
            type(expected_size) is not int
            or expected_size <= 0
            or expected_size > self.max_bytes
        ):
            raise ValueError(
                "expected_size must be a positive integer within max_bytes."
            )
        request_headers = _validate_request_headers(headers)
        reviewed_origins = _validate_origin_allowlist(allowed_origins)
        target = _validate_url(url)
        approved_origins = set(reviewed_origins)
        approved_origins.add(target.origin)
        redirects = 0

        while True:
            response = self._request(target, request_headers)
            try:
                status = getattr(response, "status", None)
                if type(status) is not int:
                    raise _http_error(
                        "transport_error",
                        "HTTP response status is invalid.",
                        url=target.url,
                    )
                response_headers = _response_headers(response, target.url)
                if status in REDIRECT_STATUSES:
                    if redirects >= self.max_redirects:
                        raise _http_error(
                            "too_many_redirects",
                            "HTTP redirect limit exceeded.",
                            status=status,
                            url=target.url,
                        )
                    location = response_headers.get("location")
                    if not location:
                        raise _http_error(
                            "redirect_location_missing",
                            "HTTP redirect did not include Location.",
                            status=status,
                            url=target.url,
                        )
                    next_url = urllib.parse.urljoin(target.url, location)
                    next_target = _validate_url(next_url)
                    if next_target.origin != target.origin:
                        if next_target.origin not in approved_origins:
                            raise _http_error(
                                "origin_not_allowed",
                                "Redirect target origin was not reviewed.",
                                status=status,
                                url=next_target.url,
                            )
                        request_headers = _strip_cross_origin_secrets(
                            request_headers
                        )
                    redirects += 1
                    target = next_target
                    continue
                if _is_rate_limited_response(status, response_headers):
                    raise _http_error(
                        "rate_limited",
                        "HTTP provider rate limit was exceeded.",
                        status=status,
                        url=target.url,
                    )
                if status != 200:
                    raise _http_error(
                        "http_error",
                        "HTTP response status is not a successful download.",
                        status=status,
                        url=target.url,
                    )
                return self._read_download(
                    response,
                    target,
                    response_headers,
                    expected_sha256,
                    expected_size,
                    redirects,
                )
            finally:
                _safe_close(response)


def default_secure_client(**kwargs):
    """Build the scanner's direct, DNS-pinned HTTPS client."""
    return SafeReleaseHttpClient(**kwargs)
