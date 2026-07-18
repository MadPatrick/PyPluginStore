import hashlib
import os
from collections.abc import Mapping

import pytest


PUBLIC_IPV4 = "93.184.216.34"
PUBLIC_IPV4_SECONDARY = "93.184.216.35"
PUBLIC_IPV6 = "2606:2800:220:1:248:1893:25c8:1946"
DOWNLOAD_URL = "https://downloads.example.test/plugin.zip"


class RecordingResolver:
    """Return one configured address set for each resolution call."""

    def __init__(self, answers):
        self.answers = {
            hostname: list(answer_sets)
            for hostname, answer_sets in answers.items()
        }
        self.calls = []

    def resolve(self, hostname, port):
        self.calls.append((hostname, port))
        if hostname not in self.answers or not self.answers[hostname]:
            raise AssertionError("Unexpected DNS lookup: " + hostname)
        answer = self.answers[hostname].pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return list(answer)


class HeaderPairs(Mapping):
    """Preserve wire header pairs so case-fold duplicates remain observable."""

    def __init__(self, pairs):
        self.pairs = list(pairs)

    def __getitem__(self, key):
        for name, value in self.pairs:
            if name == key:
                return value
        raise KeyError(key)

    def __iter__(self):
        return (name for name, _value in self.pairs)

    def __len__(self):
        return len(self.pairs)

    def items(self):
        return iter(self.pairs)


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=(), events=None):
        self.status = status
        self.headers = {} if headers is None else headers
        self.chunks = list(chunks)
        self.events = events
        self.iterated = False
        self.closed = False

    def iter_bytes(self, chunk_size):
        self.iterated = True
        assert chunk_size > 0
        for chunk in self.chunks:
            if self.events is not None:
                self.events.append("stream")
            if isinstance(chunk, BaseException):
                raise chunk
            yield bytes(chunk)

    def close(self):
        self.closed = True


class RecordingTransport:
    """Require the client to pass the pinned address and TLS identity."""

    def __init__(self, routes):
        self.routes = {
            url: list(responses)
            for url, responses in routes.items()
        }
        self.requests = []

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
        self.requests.append(
            {
                "method": method,
                "url": url,
                "connect_ip": connect_ip,
                "server_hostname": server_hostname,
                "host_header": host_header,
                "headers": dict(headers),
                "connect_timeout": connect_timeout,
                "read_timeout": read_timeout,
            }
        )
        if url not in self.routes or not self.routes[url]:
            raise AssertionError("Unexpected HTTP request: " + url)
        response = self.routes[url].pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def resolver_for(hostname="downloads.example.test", addresses=None):
    selected = [PUBLIC_IPV4] if addresses is None else list(addresses)
    return RecordingResolver({hostname: [selected]})


def response_for(body=b"release", **headers):
    response_headers = {"Content-Length": str(len(body))}
    response_headers.update(headers)
    return FakeResponse(headers=response_headers, chunks=[body])


def make_client(
    module,
    resolver,
    transport,
    *,
    max_redirects=3,
    connect_timeout=2.0,
    read_timeout=7.0,
    max_bytes=1024,
):
    return module.SafeReleaseHttpClient(
        resolver=resolver,
        transport=transport,
        max_redirects=max_redirects,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        max_bytes=max_bytes,
    )


def download(client, destination, url=DOWNLOAD_URL, **kwargs):
    return client.download_to_path(url, str(destination), **kwargs)


def assert_reason(module, reason, operation):
    with pytest.raises(module.ReleaseHttpError) as error:
        operation()
    assert error.value.reason == reason
    return error.value


@pytest.mark.parametrize(
    "address",
    [
        pytest.param(PUBLIC_IPV4, id="ipv4"),
        pytest.param(PUBLIC_IPV6, id="ipv6"),
    ],
)
def test_runtime_download_pins_public_ip_but_keeps_tls_and_host_identity(
    plugin_core_module,
    tmp_path,
    address,
):
    body = b"verified archive"
    resolver = resolver_for(addresses=[address])
    response = response_for(body)
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    result = download(client, destination)

    assert destination.read_bytes() == body
    assert result.path == str(destination)
    assert result.size == len(body)
    assert result.sha256 == hashlib.sha256(body).hexdigest()
    assert result.final_url == DOWNLOAD_URL
    assert result.redirects == 0
    assert result.verified is False
    assert resolver.calls == [("downloads.example.test", 443)]
    assert transport.requests == [
        {
            "method": "GET",
            "url": DOWNLOAD_URL,
            "connect_ip": address,
            "server_hostname": "downloads.example.test",
            "host_header": "downloads.example.test",
            "headers": {"Accept-Encoding": "identity"},
            "connect_timeout": 2.0,
            "read_timeout": 7.0,
        }
    ]
    assert response.closed is True


def test_runtime_download_pins_explicit_https_port(
    plugin_core_module,
    tmp_path,
):
    url = "https://downloads.example.test:8443/plugin.zip"
    resolver = RecordingResolver(
        {"downloads.example.test": [[PUBLIC_IPV4]]}
    )
    transport = RecordingTransport({url: [response_for()]})
    client = make_client(plugin_core_module, resolver, transport)

    download(client, tmp_path / "artifact.zip", url=url)

    assert resolver.calls == [("downloads.example.test", 8443)]
    request = transport.requests[0]
    assert request["connect_ip"] == PUBLIC_IPV4
    assert request["server_hostname"] == "downloads.example.test"
    assert request["host_header"] == "downloads.example.test:8443"


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("http://downloads.example.test/plugin.zip", id="http"),
        pytest.param("ftp://downloads.example.test/plugin.zip", id="ftp"),
        pytest.param("//downloads.example.test/plugin.zip", id="schemeless"),
        pytest.param("plugin.zip", id="relative"),
        pytest.param(
            "https://user:secret@downloads.example.test/plugin.zip",
            id="credentials",
        ),
        pytest.param(
            "https://downloads.example.test/plugin.zip#fragment",
            id="fragment",
        ),
        pytest.param(
            "https://*.example.test/plugin.zip",
            id="wildcard",
        ),
        pytest.param(
            "https://downloads.example.test/bad path.zip",
            id="space",
        ),
        pytest.param(
            "https://downloads.example.test/bad\\path.zip",
            id="backslash",
        ),
        pytest.param(
            "https://downloads.example.test/bad%path.zip",
            id="invalid-percent",
        ),
    ],
)
def test_runtime_download_requires_a_canonical_absolute_https_url(
    plugin_core_module,
    tmp_path,
    url,
):
    resolver = resolver_for()
    transport = RecordingTransport({})
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    with pytest.raises(plugin_core_module.ReleaseHttpError):
        download(client, destination, url=url)

    assert resolver.calls == []
    assert transport.requests == []
    assert not destination.exists()


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_runtime_download_revalidates_https_on_every_redirect(
    plugin_core_module,
    tmp_path,
    status,
):
    redirect = FakeResponse(
        status=status,
        headers={"Location": "http://downloads.example.test/insecure.zip"},
    )
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [redirect]})
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "https_required",
        lambda: download(client, destination),
    )

    assert len(transport.requests) == 1
    assert redirect.iterated is False
    assert redirect.closed is True
    assert not destination.exists()


def test_runtime_download_follows_relative_redirect_and_repins_host(
    plugin_core_module,
    tmp_path,
):
    final_url = "https://downloads.example.test/releases/plugin.zip"
    redirect = FakeResponse(
        status=302,
        headers={"LOCATION": "/releases/plugin.zip"},
    )
    final = response_for(b"archive")
    resolver = RecordingResolver(
        {
            "downloads.example.test": [
                [PUBLIC_IPV4],
                [PUBLIC_IPV4_SECONDARY],
            ]
        }
    )
    transport = RecordingTransport(
        {DOWNLOAD_URL: [redirect], final_url: [final]}
    )
    client = make_client(plugin_core_module, resolver, transport)

    result = download(client, tmp_path / "artifact.zip")

    assert result.final_url == final_url
    assert result.redirects == 1
    assert resolver.calls == [
        ("downloads.example.test", 443),
        ("downloads.example.test", 443),
    ]
    assert [request["connect_ip"] for request in transport.requests] == [
        PUBLIC_IPV4,
        PUBLIC_IPV4_SECONDARY,
    ]
    assert redirect.closed is True
    assert final.closed is True


def test_runtime_download_bounds_redirect_count(
    plugin_core_module,
    tmp_path,
):
    urls = [
        "https://downloads.example.test/0",
        "https://downloads.example.test/1",
        "https://downloads.example.test/2",
        "https://downloads.example.test/3",
    ]
    responses = [
        FakeResponse(status=302, headers={"Location": urls[index + 1]})
        for index in range(3)
    ]
    resolver = RecordingResolver(
        {"downloads.example.test": [[PUBLIC_IPV4] for _ in range(3)]}
    )
    transport = RecordingTransport(
        {url: [response] for url, response in zip(urls, responses)}
    )
    client = make_client(
        plugin_core_module,
        resolver,
        transport,
        max_redirects=2,
    )
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "too_many_redirects",
        lambda: download(client, destination, url=urls[0]),
    )

    assert [request["url"] for request in transport.requests] == urls[:3]
    assert all(response.closed for response in responses)
    assert not destination.exists()


def test_runtime_download_forwards_timeouts_on_every_hop(
    plugin_core_module,
    tmp_path,
):
    final_url = "https://downloads.example.test/final.zip"
    resolver = RecordingResolver(
        {"downloads.example.test": [[PUBLIC_IPV4], [PUBLIC_IPV4]]}
    )
    transport = RecordingTransport(
        {
            DOWNLOAD_URL: [
                FakeResponse(status=307, headers={"Location": final_url})
            ],
            final_url: [response_for()],
        }
    )
    client = make_client(
        plugin_core_module,
        resolver,
        transport,
        connect_timeout=1.25,
        read_timeout=4.5,
    )

    download(client, tmp_path / "artifact.zip")

    assert [request["connect_timeout"] for request in transport.requests] == [
        1.25,
        1.25,
    ]
    assert [request["read_timeout"] for request in transport.requests] == [
        4.5,
        4.5,
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("max_redirects", -1, id="redirects-negative"),
        pytest.param("max_redirects", True, id="redirects-boolean"),
        pytest.param("connect_timeout", 0, id="connect-zero"),
        pytest.param("connect_timeout", float("inf"), id="connect-infinite"),
        pytest.param("read_timeout", -1, id="read-negative"),
        pytest.param("read_timeout", float("nan"), id="read-nan"),
        pytest.param("max_bytes", 0, id="bytes-zero"),
        pytest.param("max_bytes", True, id="bytes-boolean"),
    ],
)
def test_runtime_client_rejects_ambiguous_or_unbounded_limits(
    plugin_core_module,
    field,
    value,
):
    arguments = {
        "max_redirects": 3,
        "connect_timeout": 2.0,
        "read_timeout": 7.0,
        "max_bytes": 1024,
    }
    arguments[field] = value

    with pytest.raises(ValueError):
        plugin_core_module.SafeReleaseHttpClient(
            resolver=resolver_for(),
            transport=RecordingTransport({}),
            **arguments,
        )


def test_runtime_transport_timeout_does_not_create_destination_or_retry(
    plugin_core_module,
    tmp_path,
):
    resolver = resolver_for()
    transport = RecordingTransport(
        {DOWNLOAD_URL: [TimeoutError("connect timed out")]}
    )
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "timeout",
        lambda: download(client, destination),
    )

    assert len(transport.requests) == 1
    assert not destination.exists()


def test_runtime_stream_timeout_closes_response_and_removes_partial_file(
    plugin_core_module,
    tmp_path,
):
    response = FakeResponse(
        headers={},
        chunks=[b"partial", TimeoutError("read timed out")],
    )
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "timeout",
        lambda: download(client, destination),
    )

    assert response.closed is True
    assert not destination.exists()


@pytest.mark.parametrize(
    "address",
    [
        pytest.param("127.0.0.1", id="ipv4-loopback"),
        pytest.param("10.0.0.1", id="ipv4-private-10"),
        pytest.param("172.16.0.1", id="ipv4-private-172"),
        pytest.param("192.168.0.1", id="ipv4-private-192"),
        pytest.param("169.254.169.254", id="ipv4-link-local"),
        pytest.param("224.0.0.1", id="ipv4-multicast"),
        pytest.param("240.0.0.1", id="ipv4-reserved"),
        pytest.param("0.0.0.0", id="ipv4-unspecified"),
        pytest.param("100.64.0.1", id="ipv4-shared"),
        pytest.param("192.0.2.1", id="ipv4-documentation"),
        pytest.param("::1", id="ipv6-loopback"),
        pytest.param("fc00::1", id="ipv6-private"),
        pytest.param("fe80::1", id="ipv6-link-local"),
        pytest.param("ff02::1", id="ipv6-multicast"),
        pytest.param("::", id="ipv6-unspecified"),
        pytest.param("2001:db8::1", id="ipv6-documentation"),
        pytest.param("::ffff:127.0.0.1", id="mapped-loopback"),
    ],
)
def test_runtime_dns_rejects_non_public_addresses(
    plugin_core_module,
    tmp_path,
    address,
):
    resolver = resolver_for(addresses=[address])
    transport = RecordingTransport({})
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "non_public_address",
        lambda: download(client, destination),
    )

    assert resolver.calls == [("downloads.example.test", 443)]
    assert transport.requests == []
    assert not destination.exists()


def test_runtime_dns_rejects_mixed_public_and_private_answer_as_a_whole(
    plugin_core_module,
    tmp_path,
):
    resolver = resolver_for(addresses=[PUBLIC_IPV4, "127.0.0.1"])
    transport = RecordingTransport({})
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "non_public_address",
        lambda: download(client, destination),
    )

    assert transport.requests == []
    assert not destination.exists()


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param([], id="empty-answer"),
        pytest.param(["not-an-ip"], id="malformed-address"),
        pytest.param([PUBLIC_IPV4] * 65, id="too-many-addresses"),
    ],
)
def test_runtime_dns_rejects_invalid_or_unbounded_answers(
    plugin_core_module,
    tmp_path,
    answer,
):
    resolver = resolver_for(addresses=answer)
    transport = RecordingTransport({})
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "dns_resolution_failed",
        lambda: download(client, destination),
    )

    assert transport.requests == []
    assert not destination.exists()


def test_runtime_dns_resolution_exception_fails_closed(
    plugin_core_module,
    tmp_path,
):
    resolver = RecordingResolver(
        {"downloads.example.test": [OSError("DNS unavailable")]}
    )
    transport = RecordingTransport({})
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "dns_resolution_failed",
        lambda: download(client, destination),
    )

    assert transport.requests == []
    assert not destination.exists()


def test_runtime_dns_rebinding_blocks_redirected_private_address(
    plugin_core_module,
    tmp_path,
):
    final_url = "https://downloads.example.test/final.zip"
    redirect = FakeResponse(status=302, headers={"Location": final_url})
    resolver = RecordingResolver(
        {
            "downloads.example.test": [
                [PUBLIC_IPV4],
                ["127.0.0.1"],
            ]
        }
    )
    transport = RecordingTransport({DOWNLOAD_URL: [redirect]})
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "non_public_address",
        lambda: download(client, destination),
    )

    assert resolver.calls == [
        ("downloads.example.test", 443),
        ("downloads.example.test", 443),
    ]
    assert len(transport.requests) == 1
    assert redirect.closed is True
    assert not destination.exists()


def cross_origin_setup():
    source_url = "https://api.example.test/releases/latest"
    target_url = "https://cdn.example.test/plugin.zip"
    redirect = FakeResponse(status=302, headers={"Location": target_url})
    resolver = RecordingResolver(
        {
            "api.example.test": [[PUBLIC_IPV4]],
            "cdn.example.test": [[PUBLIC_IPV4_SECONDARY]],
        }
    )
    transport = RecordingTransport(
        {source_url: [redirect], target_url: [response_for()]}
    )
    return source_url, target_url, redirect, resolver, transport


def test_runtime_cross_origin_redirect_requires_exact_reviewed_origin(
    plugin_core_module,
    tmp_path,
):
    source_url, _target, redirect, resolver, transport = cross_origin_setup()
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "origin_not_allowed",
        lambda: download(client, destination, url=source_url),
    )

    assert resolver.calls == [("api.example.test", 443)]
    assert len(transport.requests) == 1
    assert redirect.closed is True
    assert not destination.exists()


def test_runtime_cross_origin_redirect_strips_all_secret_headers(
    plugin_core_module,
    tmp_path,
):
    source_url, target_url, _redirect, resolver, transport = (
        cross_origin_setup()
    )
    client = make_client(plugin_core_module, resolver, transport)

    result = download(
        client,
        tmp_path / "artifact.zip",
        url=source_url,
        headers={
            "Authorization": "Bearer runtime-secret",
            "Proxy-Authorization": "Basic proxy-secret",
            "Cookie": "session=secret",
            "Cookie2": "legacy=secret",
            "PRIVATE-TOKEN": "forge-secret",
            "Accept": "application/zip",
        },
        allowed_origins=["https://cdn.example.test"],
    )

    first_headers = {
        name.lower(): value
        for name, value in transport.requests[0]["headers"].items()
    }
    redirected_headers = {
        name.lower(): value
        for name, value in transport.requests[1]["headers"].items()
    }
    assert first_headers["authorization"] == "Bearer runtime-secret"
    assert first_headers["proxy-authorization"] == "Basic proxy-secret"
    assert "authorization" not in redirected_headers
    assert "proxy-authorization" not in redirected_headers
    assert "cookie" not in redirected_headers
    assert "cookie2" not in redirected_headers
    assert "private-token" not in redirected_headers
    assert redirected_headers["accept"] == "application/zip"
    assert redirected_headers["accept-encoding"] == "identity"
    assert result.final_url == target_url


def test_runtime_same_origin_redirect_preserves_authorization(
    plugin_core_module,
    tmp_path,
):
    target_url = "https://downloads.example.test/final.zip"
    resolver = RecordingResolver(
        {"downloads.example.test": [[PUBLIC_IPV4], [PUBLIC_IPV4]]}
    )
    transport = RecordingTransport(
        {
            DOWNLOAD_URL: [
                FakeResponse(status=302, headers={"Location": target_url})
            ],
            target_url: [response_for()],
        }
    )
    client = make_client(plugin_core_module, resolver, transport)

    download(
        client,
        tmp_path / "artifact.zip",
        headers={"aUtHoRiZaTiOn": "Bearer same-origin"},
    )

    redirected_headers = {
        name.lower(): value
        for name, value in transport.requests[1]["headers"].items()
    }
    assert redirected_headers["authorization"] == "Bearer same-origin"


def test_runtime_reviewed_origin_matches_exact_port(
    plugin_core_module,
    tmp_path,
):
    source_url = "https://api.example.test/releases/latest"
    target_url = "https://cdn.example.test:8443/plugin.zip"
    redirect = FakeResponse(status=302, headers={"Location": target_url})
    resolver = RecordingResolver({"api.example.test": [[PUBLIC_IPV4]]})
    transport = RecordingTransport({source_url: [redirect]})
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "origin_not_allowed",
        lambda: download(
            client,
            destination,
            url=source_url,
            allowed_origins=["https://cdn.example.test"],
        ),
    )

    assert len(transport.requests) == 1
    assert not destination.exists()


@pytest.mark.parametrize(
    "origin",
    [
        pytest.param("http://cdn.example.test", id="http"),
        pytest.param("https://*.example.test", id="wildcard"),
        pytest.param("https://cdn.example.test/releases", id="path"),
        pytest.param(
            "https://user:secret@cdn.example.test",
            id="credentials",
        ),
        pytest.param("https://cdn.example.test?target=other", id="query"),
        pytest.param("https://cdn.example.test#fragment", id="fragment"),
    ],
)
def test_runtime_origin_allowlist_rejects_non_origin_values_before_network(
    plugin_core_module,
    tmp_path,
    origin,
):
    resolver = resolver_for()
    transport = RecordingTransport({})
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "invalid_origin_allowlist",
        lambda: download(
            client,
            destination,
            allowed_origins=[origin],
        ),
    )

    assert resolver.calls == []
    assert transport.requests == []
    assert not destination.exists()


def test_runtime_forces_identity_request_encoding(
    plugin_core_module,
    tmp_path,
):
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response_for()]})
    client = make_client(plugin_core_module, resolver, transport)

    download(
        client,
        tmp_path / "artifact.zip",
        headers={"Accept-Encoding": "gzip", "Accept": "application/zip"},
    )

    request_headers = {
        name.lower(): value
        for name, value in transport.requests[0]["headers"].items()
    }
    assert request_headers["accept-encoding"] == "identity"
    assert request_headers["accept"] == "application/zip"


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate"])
def test_runtime_rejects_encoded_response_without_writing(
    plugin_core_module,
    tmp_path,
    encoding,
):
    response = FakeResponse(
        headers={
            "Content-Encoding": encoding,
            "Content-Length": "7",
        },
        chunks=[b"archive"],
    )
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "unsupported_content_encoding",
        lambda: download(client, destination),
    )

    assert response.iterated is False
    assert response.closed is True
    assert not destination.exists()


def test_runtime_rejects_casefold_duplicate_response_headers(
    plugin_core_module,
    tmp_path,
):
    response = FakeResponse(
        headers=HeaderPairs(
            [("Content-Length", "7"), ("content-length", "7")]
        ),
        chunks=[b"archive"],
    )
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "invalid_response_headers",
        lambda: download(client, destination),
    )

    assert response.iterated is False
    assert response.closed is True
    assert not destination.exists()


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param(
            HeaderPairs([("Bad Header", "value")]),
            id="invalid-name",
        ),
        pytest.param(
            HeaderPairs([("X-Test", "value\r\ninjected")]),
            id="control-value",
        ),
    ],
)
def test_runtime_rejects_malformed_response_headers(
    plugin_core_module,
    tmp_path,
    headers,
):
    response = FakeResponse(headers=headers, chunks=[b"archive"])
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "invalid_response_headers",
        lambda: download(client, destination),
    )

    assert response.iterated is False
    assert response.closed is True
    assert not destination.exists()


def test_runtime_rejects_casefold_duplicate_request_headers_before_network(
    plugin_core_module,
    tmp_path,
):
    resolver = resolver_for()
    transport = RecordingTransport({})
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    with pytest.raises(ValueError):
        download(
            client,
            destination,
            headers={"Accept": "one", "aCcEpT": "two"},
        )

    assert resolver.calls == []
    assert transport.requests == []
    assert not destination.exists()


def test_runtime_content_length_over_limit_is_rejected_before_writing(
    plugin_core_module,
    tmp_path,
):
    response = FakeResponse(
        headers={"Content-Length": "6"},
        chunks=[b"123456"],
    )
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
        max_bytes=5,
    )
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "content_too_large",
        lambda: download(client, destination),
    )

    assert response.iterated is False
    assert response.closed is True
    assert not destination.exists()


def test_runtime_stream_cap_removes_partial_file_without_content_length(
    plugin_core_module,
    tmp_path,
):
    response = FakeResponse(headers={}, chunks=[b"1234", b"56"])
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
        max_bytes=5,
    )
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "content_too_large",
        lambda: download(client, destination),
    )

    assert response.iterated is True
    assert response.closed is True
    assert not destination.exists()


def test_runtime_stream_exactly_at_limit_is_persisted(
    plugin_core_module,
    tmp_path,
):
    body = b"12345"
    response = FakeResponse(headers={}, chunks=[b"12", b"345"])
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
        max_bytes=len(body),
    )
    destination = tmp_path / "artifact.zip"

    result = download(client, destination)

    assert destination.read_bytes() == body
    assert result.size == len(body)


@pytest.mark.parametrize(
    "content_length",
    [
        pytest.param("-1", id="negative"),
        pytest.param("not-a-number", id="nonnumeric"),
        pytest.param("5, 5", id="multiple"),
        pytest.param("+5", id="signed"),
    ],
)
def test_runtime_rejects_malformed_content_length(
    plugin_core_module,
    tmp_path,
    content_length,
):
    response = FakeResponse(
        headers={"Content-Length": content_length},
        chunks=[b"12345"],
    )
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "invalid_content_length",
        lambda: download(client, destination),
    )

    assert response.iterated is False
    assert response.closed is True
    assert not destination.exists()


def test_runtime_received_bytes_must_equal_declared_length(
    plugin_core_module,
    tmp_path,
):
    response = FakeResponse(
        headers={"Content-Length": "6"},
        chunks=[b"short"],
    )
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "length_mismatch",
        lambda: download(client, destination),
    )

    assert response.closed is True
    assert not destination.exists()


def test_runtime_expected_length_mismatch_rejects_before_streaming(
    plugin_core_module,
    tmp_path,
):
    response = response_for(b"12345")
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "length_mismatch",
        lambda: download(client, destination, expected_size=6),
    )

    assert response.iterated is False
    assert response.closed is True
    assert not destination.exists()


def test_runtime_expected_length_is_checked_without_content_length(
    plugin_core_module,
    tmp_path,
):
    response = FakeResponse(headers={}, chunks=[b"12345"])
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "length_mismatch",
        lambda: download(client, destination, expected_size=6),
    )

    assert response.closed is True
    assert not destination.exists()


def test_runtime_expected_digest_mismatch_removes_downloaded_file(
    plugin_core_module,
    tmp_path,
):
    response = response_for(b"artifact bytes")
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "digest_mismatch",
        lambda: download(
            client,
            destination,
            expected_sha256="0" * 64,
        ),
    )

    assert response.closed is True
    assert not destination.exists()


def test_runtime_verified_download_returns_file_metadata(
    plugin_core_module,
    tmp_path,
):
    body = b"artifact bytes"
    digest = hashlib.sha256(body).hexdigest()
    response = FakeResponse(
        headers={"CONTENT-LENGTH": str(len(body))},
        chunks=[b"artifact ", b"bytes"],
    )
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )
    destination = tmp_path / "artifact.zip"

    result = download(
        client,
        destination,
        expected_sha256=digest,
        expected_size=len(body),
    )

    assert destination.read_bytes() == body
    assert result.path == str(destination)
    assert result.size == len(body)
    assert result.sha256 == digest
    assert result.verified is True
    assert response.closed is True


@pytest.mark.parametrize(
    ("expected_sha256", "expected_size"),
    [
        pytest.param("A" * 64, 5, id="noncanonical-digest"),
        pytest.param("short", 5, id="short-digest"),
        pytest.param("0" * 64, 0, id="zero-size"),
        pytest.param("0" * 64, True, id="boolean-size"),
    ],
)
def test_runtime_invalid_integrity_expectations_fail_before_network_or_file(
    plugin_core_module,
    tmp_path,
    expected_sha256,
    expected_size,
):
    resolver = resolver_for()
    transport = RecordingTransport({})
    client = make_client(plugin_core_module, resolver, transport)
    destination = tmp_path / "artifact.zip"

    with pytest.raises(ValueError):
        download(
            client,
            destination,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
        )

    assert resolver.calls == []
    assert transport.requests == []
    assert not destination.exists()


@pytest.mark.parametrize("status", [204, 400, 404, 500])
def test_runtime_rejects_non_success_status_without_creating_file(
    plugin_core_module,
    tmp_path,
    status,
):
    response = FakeResponse(status=status, chunks=[b"error body"])
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )
    destination = tmp_path / "artifact.zip"

    error = assert_reason(
        plugin_core_module,
        "http_error",
        lambda: download(client, destination),
    )

    assert error.status == status
    assert response.iterated is False
    assert response.closed is True
    assert not destination.exists()


def test_runtime_rejects_redirect_without_location(
    plugin_core_module,
    tmp_path,
):
    response = FakeResponse(status=302)
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )
    destination = tmp_path / "artifact.zip"

    assert_reason(
        plugin_core_module,
        "redirect_location_missing",
        lambda: download(client, destination),
    )

    assert response.closed is True
    assert not destination.exists()


def test_runtime_download_refuses_existing_destination_without_network(
    plugin_core_module,
    tmp_path,
):
    destination = tmp_path / "artifact.zip"
    destination.write_bytes(b"keep me")
    resolver = resolver_for()
    transport = RecordingTransport({})
    client = make_client(plugin_core_module, resolver, transport)

    assert_reason(
        plugin_core_module,
        "destination_exists",
        lambda: download(client, destination),
    )

    assert destination.read_bytes() == b"keep me"
    assert resolver.calls == []
    assert transport.requests == []


def test_runtime_download_refuses_symlink_destination_without_touching_target(
    plugin_core_module,
    tmp_path,
):
    target = tmp_path / "target.zip"
    target.write_bytes(b"keep target")
    destination = tmp_path / "artifact.zip"
    try:
        destination.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("Symbolic links are unavailable on this test host.")
    resolver = resolver_for()
    transport = RecordingTransport({})
    client = make_client(plugin_core_module, resolver, transport)

    assert_reason(
        plugin_core_module,
        "destination_exists",
        lambda: download(client, destination),
    )

    assert destination.is_symlink()
    assert target.read_bytes() == b"keep target"
    assert resolver.calls == []
    assert transport.requests == []


def test_runtime_fsync_failure_removes_untrusted_file(
    plugin_core_module,
    tmp_path,
    monkeypatch,
):
    response = response_for(b"complete but not durable")
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )
    destination = tmp_path / "artifact.zip"

    def fail_fsync(_descriptor):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(plugin_core_module.os, "fsync", fail_fsync)

    assert_reason(
        plugin_core_module,
        "write_failed",
        lambda: download(client, destination),
    )

    assert response.closed is True
    assert not destination.exists()


def test_runtime_fsync_occurs_only_after_stream_and_integrity_verification(
    plugin_core_module,
    tmp_path,
    monkeypatch,
):
    body = b"verified then durable"
    digest = hashlib.sha256(body).hexdigest()
    events = []
    response = FakeResponse(
        headers={"Content-Length": str(len(body))},
        chunks=[body],
        events=events,
    )
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )

    def record_fsync(_descriptor):
        events.append("fsync")

    monkeypatch.setattr(plugin_core_module.os, "fsync", record_fsync)

    download(
        client,
        tmp_path / "artifact.zip",
        expected_sha256=digest,
        expected_size=len(body),
    )

    assert events == ["stream", "fsync"]


def test_runtime_digest_failure_never_fsyncs_unverified_file(
    plugin_core_module,
    tmp_path,
    monkeypatch,
):
    fsync_calls = []
    response = response_for(b"wrong bytes")
    client = make_client(
        plugin_core_module,
        resolver_for(),
        RecordingTransport({DOWNLOAD_URL: [response]}),
    )
    destination = tmp_path / "artifact.zip"
    monkeypatch.setattr(
        plugin_core_module.os,
        "fsync",
        lambda descriptor: fsync_calls.append(descriptor),
    )

    assert_reason(
        plugin_core_module,
        "digest_mismatch",
        lambda: download(
            client,
            destination,
            expected_sha256="0" * 64,
        ),
    )

    assert fsync_calls == []
    assert not destination.exists()


def test_runtime_default_client_uses_system_resolver_and_pinned_transport(
    plugin_core_module,
):
    client = plugin_core_module.SafeReleaseHttpClient(max_bytes=321)

    assert isinstance(client.resolver, plugin_core_module.SystemResolver)
    assert isinstance(client.transport, plugin_core_module.PinnedHttpsTransport)
    assert client.max_bytes == 321
