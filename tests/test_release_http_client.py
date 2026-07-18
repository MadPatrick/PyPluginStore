import hashlib
from pathlib import Path

import pytest

from conftest import REPO_ROOT, load_module_from_path


PUBLIC_IPV4 = "93.184.216.34"
PUBLIC_IPV4_SECONDARY = "93.184.216.35"
PUBLIC_IPV6 = "2606:2800:220:1:248:1893:25c8:1946"
DOWNLOAD_URL = "https://downloads.example.test/plugin.zip"


class RecordingResolver:
    """Return one configured address set per resolution call."""

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


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=()):
        self.status = status
        self.headers = dict(headers or {})
        self.chunks = list(chunks)
        self.iterated = False
        self.closed = False

    def iter_bytes(self, chunk_size):
        self.iterated = True
        assert chunk_size > 0
        for chunk in self.chunks:
            if isinstance(chunk, BaseException):
                raise chunk
            yield bytes(chunk)

    def close(self):
        self.closed = True


class RecordingTransport:
    """Require callers to provide the validated address and TLS hostname."""

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


@pytest.fixture
def release_http_module():
    module_path = REPO_ROOT / ".github" / "scripts" / "release_http.py"
    if not module_path.is_file():
        class MissingReleaseHttp:
            def __getattr__(self, name):
                raise AssertionError(
                    "Missing secure release HTTP contract: " + name
                )

        return MissingReleaseHttp()
    return load_module_from_path("release_http_under_test", module_path)


def resolver_for(hostname="downloads.example.test", addresses=None):
    selected_addresses = (
        [PUBLIC_IPV4] if addresses is None else list(addresses)
    )
    return RecordingResolver(
        {hostname: [selected_addresses]}
    )


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
def test_public_address_is_pinned_while_tls_uses_original_hostname(
    release_http_module, address
):
    resolver = resolver_for(addresses=[address])
    response = response_for(b"verified bytes")
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(release_http_module, resolver, transport)

    result = client.download(DOWNLOAD_URL)

    assert result.data == b"verified bytes"
    assert result.size == len(b"verified bytes")
    assert result.sha256 == hashlib.sha256(b"verified bytes").hexdigest()
    assert result.final_url == DOWNLOAD_URL
    assert result.redirects == 0
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


def test_explicit_https_port_is_resolved_and_pinned(release_http_module):
    url = "https://downloads.example.test:8443/plugin.zip"
    resolver = resolver_for()
    transport = RecordingTransport({url: [response_for()]})
    client = make_client(release_http_module, resolver, transport)

    client.download(url)

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
    ],
)
def test_initial_request_requires_absolute_https_url(
    release_http_module, url
):
    resolver = resolver_for()
    transport = RecordingTransport({})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "https_required",
        lambda: client.download(url),
    )

    assert resolver.calls == []
    assert transport.requests == []


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_every_redirect_hop_must_remain_https(
    release_http_module, status
):
    redirect = FakeResponse(
        status=status,
        headers={"Location": "http://downloads.example.test/insecure.zip"},
    )
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [redirect]})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "https_required",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert resolver.calls == [("downloads.example.test", 443)]
    assert len(transport.requests) == 1
    assert redirect.iterated is False
    assert redirect.closed is True


def test_relative_same_origin_redirect_remains_allowed(release_http_module):
    final_url = "https://downloads.example.test/releases/plugin.zip"
    redirect = FakeResponse(
        status=302,
        headers={"LOCATION": "/releases/plugin.zip"},
    )
    final_response = response_for(b"archive")
    resolver = RecordingResolver(
        {
            "downloads.example.test": [
                [PUBLIC_IPV4],
                [PUBLIC_IPV4_SECONDARY],
            ]
        }
    )
    transport = RecordingTransport(
        {
            DOWNLOAD_URL: [redirect],
            final_url: [final_response],
        }
    )
    client = make_client(release_http_module, resolver, transport)

    result = client.download(DOWNLOAD_URL)

    assert result.final_url == final_url
    assert result.redirects == 1
    assert [request["connect_ip"] for request in transport.requests] == [
        PUBLIC_IPV4,
        PUBLIC_IPV4_SECONDARY,
    ]
    assert resolver.calls == [
        ("downloads.example.test", 443),
        ("downloads.example.test", 443),
    ]
    assert redirect.iterated is False
    assert redirect.closed is True
    assert final_response.closed is True


def test_redirect_count_is_bounded(release_http_module):
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
        release_http_module,
        resolver,
        transport,
        max_redirects=2,
    )

    assert_reason(
        release_http_module,
        "too_many_redirects",
        lambda: client.download(urls[0]),
    )

    assert [request["url"] for request in transport.requests] == urls[:3]
    assert all(response.closed for response in responses)


def test_connection_and_read_timeouts_are_forwarded_on_every_hop(
    release_http_module,
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
        release_http_module,
        resolver,
        transport,
        connect_timeout=1.25,
        read_timeout=4.5,
    )

    client.download(DOWNLOAD_URL)

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
def test_client_rejects_unbounded_or_ambiguous_limits(
    release_http_module, field, value
):
    arguments = {
        "max_redirects": 3,
        "connect_timeout": 2.0,
        "read_timeout": 7.0,
        "max_bytes": 1024,
    }
    arguments[field] = value

    with pytest.raises(ValueError):
        release_http_module.SafeReleaseHttpClient(
            resolver=resolver_for(),
            transport=RecordingTransport({}),
            **arguments,
        )


def test_transport_timeout_is_reported_without_retrying_unknown_bytes(
    release_http_module,
):
    resolver = resolver_for()
    transport = RecordingTransport(
        {DOWNLOAD_URL: [TimeoutError("connect timed out")]}
    )
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "timeout",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert len(transport.requests) == 1


def test_stream_timeout_closes_response_and_discards_partial_download(
    release_http_module,
):
    response = FakeResponse(
        headers={},
        chunks=[b"partial", TimeoutError("read timed out")],
    )
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "timeout",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert response.closed is True


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
        pytest.param("100.64.0.1", id="ipv4-shared-non-global"),
        pytest.param("192.0.2.1", id="ipv4-documentation"),
        pytest.param("::1", id="ipv6-loopback"),
        pytest.param("fc00::1", id="ipv6-private"),
        pytest.param("fe80::1", id="ipv6-link-local"),
        pytest.param("ff02::1", id="ipv6-multicast"),
        pytest.param("::", id="ipv6-unspecified"),
        pytest.param("2001:db8::1", id="ipv6-documentation"),
        pytest.param("::ffff:127.0.0.1", id="ipv4-mapped-loopback"),
    ],
)
def test_dns_rejects_every_non_public_address(
    release_http_module, address
):
    resolver = resolver_for(addresses=[address])
    transport = RecordingTransport({})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "non_public_address",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert resolver.calls == [("downloads.example.test", 443)]
    assert transport.requests == []


def test_dns_answer_with_public_and_private_addresses_is_rejected_as_a_whole(
    release_http_module,
):
    resolver = resolver_for(addresses=[PUBLIC_IPV4, "127.0.0.1"])
    transport = RecordingTransport({})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "non_public_address",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert transport.requests == []


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param([], id="empty-answer"),
        pytest.param(["not-an-ip"], id="malformed-address"),
    ],
)
def test_invalid_dns_answer_fails_closed(release_http_module, answer):
    resolver = resolver_for(addresses=answer)
    transport = RecordingTransport({})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "dns_resolution_failed",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert transport.requests == []


def test_dns_resolution_exception_fails_closed(release_http_module):
    resolver = RecordingResolver(
        {"downloads.example.test": [[OSError("DNS unavailable")]]}
    )
    # Store the exception as the answer itself rather than an address list.
    resolver.answers["downloads.example.test"] = [
        OSError("DNS unavailable")
    ]
    transport = RecordingTransport({})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "dns_resolution_failed",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert transport.requests == []


def test_hostname_is_resolved_and_repinned_for_same_host_redirect(
    release_http_module,
):
    final_url = "https://downloads.example.test/final.zip"
    resolver = RecordingResolver(
        {
            "downloads.example.test": [
                [PUBLIC_IPV4],
                [PUBLIC_IPV4_SECONDARY],
            ]
        }
    )
    transport = RecordingTransport(
        {
            DOWNLOAD_URL: [
                FakeResponse(status=302, headers={"Location": final_url})
            ],
            final_url: [response_for()],
        }
    )
    client = make_client(release_http_module, resolver, transport)

    client.download(DOWNLOAD_URL)

    assert resolver.calls == [
        ("downloads.example.test", 443),
        ("downloads.example.test", 443),
    ]
    assert [request["connect_ip"] for request in transport.requests] == [
        PUBLIC_IPV4,
        PUBLIC_IPV4_SECONDARY,
    ]


def test_dns_rebinding_to_private_address_blocks_redirected_hop(
    release_http_module,
):
    final_url = "https://downloads.example.test/final.zip"
    redirect = FakeResponse(
        status=302,
        headers={"Location": final_url},
    )
    resolver = RecordingResolver(
        {
            "downloads.example.test": [
                [PUBLIC_IPV4],
                ["127.0.0.1"],
            ]
        }
    )
    transport = RecordingTransport({DOWNLOAD_URL: [redirect]})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "non_public_address",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert resolver.calls == [
        ("downloads.example.test", 443),
        ("downloads.example.test", 443),
    ]
    assert len(transport.requests) == 1
    assert redirect.closed is True


def cross_origin_setup():
    source_url = "https://api.example.test/releases/latest"
    target_url = "https://cdn.example.test/plugin.zip"
    redirect = FakeResponse(
        status=302,
        headers={"Location": target_url},
    )
    resolver = RecordingResolver(
        {
            "api.example.test": [[PUBLIC_IPV4]],
            "cdn.example.test": [[PUBLIC_IPV4_SECONDARY]],
        }
    )
    transport = RecordingTransport(
        {
            source_url: [redirect],
            target_url: [response_for()],
        }
    )
    return source_url, target_url, redirect, resolver, transport


def test_cross_origin_redirect_requires_reviewed_origin_allowlist(
    release_http_module,
):
    source_url, _, redirect, resolver, transport = cross_origin_setup()
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "origin_not_allowed",
        lambda: client.download(source_url),
    )

    assert resolver.calls == [("api.example.test", 443)]
    assert len(transport.requests) == 1
    assert redirect.closed is True


def test_allowlisted_cross_origin_redirect_strips_authorization_headers(
    release_http_module,
):
    source_url, target_url, _, resolver, transport = cross_origin_setup()
    client = make_client(release_http_module, resolver, transport)

    result = client.download(
        source_url,
        headers={
            "Authorization": "Bearer scanner-secret",
            "Proxy-Authorization": "Basic proxy-secret",
            "Cookie": "session=secret",
            "Cookie2": "legacy=secret",
            "PRIVATE-TOKEN": "gitlab-secret",
            "Accept": "application/zip",
        },
        allowed_origins=["https://cdn.example.test"],
    )

    first_headers = {
        key.lower(): value
        for key, value in transport.requests[0]["headers"].items()
    }
    redirected_headers = {
        key.lower(): value
        for key, value in transport.requests[1]["headers"].items()
    }
    assert first_headers["authorization"] == "Bearer scanner-secret"
    assert first_headers["proxy-authorization"] == "Basic proxy-secret"
    assert "authorization" not in redirected_headers
    assert "proxy-authorization" not in redirected_headers
    assert "cookie" not in redirected_headers
    assert "cookie2" not in redirected_headers
    assert "private-token" not in redirected_headers
    assert redirected_headers["accept"] == "application/zip"
    assert redirected_headers["accept-encoding"] == "identity"
    assert result.final_url == target_url


def test_same_origin_redirect_preserves_authorization(release_http_module):
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
    client = make_client(release_http_module, resolver, transport)

    client.download(
        DOWNLOAD_URL,
        headers={"aUtHoRiZaTiOn": "Bearer same-origin"},
    )

    redirected_headers = {
        key.lower(): value
        for key, value in transport.requests[1]["headers"].items()
    }
    assert redirected_headers["authorization"] == "Bearer same-origin"


def test_reviewed_origin_allowlist_matches_exact_port(release_http_module):
    source_url = "https://api.example.test/releases/latest"
    target_url = "https://cdn.example.test:8443/plugin.zip"
    redirect = FakeResponse(status=302, headers={"Location": target_url})
    resolver = RecordingResolver(
        {"api.example.test": [[PUBLIC_IPV4]]}
    )
    transport = RecordingTransport({source_url: [redirect]})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "origin_not_allowed",
        lambda: client.download(
            source_url,
            allowed_origins=["https://cdn.example.test"],
        ),
    )

    assert resolver.calls == [("api.example.test", 443)]
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "origin",
    [
        pytest.param("http://cdn.example.test", id="http"),
        pytest.param("https://*.example.test", id="wildcard"),
        pytest.param("https://cdn.example.test/releases", id="path"),
        pytest.param("https://user:secret@cdn.example.test", id="credentials"),
        pytest.param("https://cdn.example.test?target=other", id="query"),
        pytest.param("https://cdn.example.test#fragment", id="fragment"),
    ],
)
def test_reviewed_origin_allowlist_rejects_non_origin_values(
    release_http_module, origin
):
    resolver = resolver_for()
    transport = RecordingTransport({})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "invalid_origin_allowlist",
        lambda: client.download(
            DOWNLOAD_URL,
            allowed_origins=[origin],
        ),
    )

    assert resolver.calls == []
    assert transport.requests == []


def test_content_length_over_limit_is_rejected_before_streaming(
    release_http_module,
):
    response = FakeResponse(
        headers={"content-length": "6"},
        chunks=[b"123456"],
    )
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(
        release_http_module,
        resolver,
        transport,
        max_bytes=5,
    )

    assert_reason(
        release_http_module,
        "content_too_large",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert response.iterated is False
    assert response.closed is True


def test_stream_limit_is_enforced_without_content_length(
    release_http_module,
):
    response = FakeResponse(headers={}, chunks=[b"1234", b"56"])
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(
        release_http_module,
        resolver,
        transport,
        max_bytes=5,
    )

    assert_reason(
        release_http_module,
        "content_too_large",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert response.iterated is True
    assert response.closed is True


def test_stream_exactly_at_limit_is_accepted(release_http_module):
    body = b"12345"
    response = FakeResponse(headers={}, chunks=[b"12", b"345"])
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(
        release_http_module,
        resolver,
        transport,
        max_bytes=len(body),
    )

    result = client.download(DOWNLOAD_URL)

    assert result.data == body
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
def test_malformed_content_length_is_rejected(
    release_http_module, content_length
):
    response = FakeResponse(
        headers={"Content-Length": content_length},
        chunks=[b"12345"],
    )
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "invalid_content_length",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert response.iterated is False
    assert response.closed is True


def test_received_bytes_must_equal_declared_content_length(
    release_http_module,
):
    response = FakeResponse(
        headers={"Content-Length": "6"},
        chunks=[b"short"],
    )
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "length_mismatch",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert response.closed is True


def test_expected_length_mismatch_is_rejected_before_streaming_when_declared(
    release_http_module,
):
    response = response_for(b"12345")
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "length_mismatch",
        lambda: client.download(DOWNLOAD_URL, expected_size=6),
    )

    assert response.iterated is False
    assert response.closed is True


def test_expected_length_is_checked_without_content_length(
    release_http_module,
):
    response = FakeResponse(headers={}, chunks=[b"12345"])
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "length_mismatch",
        lambda: client.download(DOWNLOAD_URL, expected_size=6),
    )

    assert response.closed is True


def test_expected_digest_must_match_streamed_bytes(release_http_module):
    body = b"artifact bytes"
    response = response_for(body)
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "digest_mismatch",
        lambda: client.download(
            DOWNLOAD_URL,
            expected_sha256="0" * 64,
        ),
    )

    assert response.closed is True


def test_expected_digest_and_length_are_returned_after_verification(
    release_http_module,
):
    body = b"artifact bytes"
    digest = hashlib.sha256(body).hexdigest()
    response = FakeResponse(
        headers={"CONTENT-LENGTH": str(len(body))},
        chunks=[b"artifact ", b"bytes"],
    )
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(release_http_module, resolver, transport)

    result = client.download(
        DOWNLOAD_URL,
        expected_sha256=digest,
        expected_size=len(body),
    )

    assert result.data == body
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
def test_invalid_integrity_expectations_are_rejected_before_request(
    release_http_module, expected_sha256, expected_size
):
    resolver = resolver_for()
    transport = RecordingTransport({})
    client = make_client(release_http_module, resolver, transport)

    with pytest.raises(ValueError):
        client.download(
            DOWNLOAD_URL,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
        )

    assert resolver.calls == []
    assert transport.requests == []


@pytest.mark.parametrize("status", [204, 400, 404, 500])
def test_non_success_non_redirect_status_is_rejected_and_closed(
    release_http_module, status
):
    response = FakeResponse(status=status, chunks=[b"error body"])
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(release_http_module, resolver, transport)

    error = assert_reason(
        release_http_module,
        "http_error",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert error.status == status
    assert response.iterated is False
    assert response.closed is True


def test_redirect_without_location_is_rejected_and_closed(
    release_http_module,
):
    response = FakeResponse(status=302)
    resolver = resolver_for()
    transport = RecordingTransport({DOWNLOAD_URL: [response]})
    client = make_client(release_http_module, resolver, transport)

    assert_reason(
        release_http_module,
        "redirect_location_missing",
        lambda: client.download(DOWNLOAD_URL),
    )

    assert response.closed is True


def test_default_secure_client_builds_production_components(
    release_http_module,
):
    client = release_http_module.default_secure_client(max_bytes=321)

    assert isinstance(client, release_http_module.SafeReleaseHttpClient)
    assert isinstance(client.resolver, release_http_module.SystemResolver)
    assert isinstance(client.transport, release_http_module.PinnedHttpsTransport)
    assert client.max_bytes == 321
