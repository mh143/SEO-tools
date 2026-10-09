import asyncio
import socket

import httpcore
import pytest

from app.core.config import get_settings
from app.crawler import ssrf
from app.crawler.fetcher import SafeFetcher
from app.crawler.ssrf import BlockedURLError, is_public_ip, validate_url
from tests.fixtures.site import FixtureSite


@pytest.fixture
def allow_loopback():
    s = get_settings()
    old = s.ssrf_dev_allow_hosts
    s.ssrf_dev_allow_hosts = "127.0.0.1"
    yield
    s.ssrf_dev_allow_hosts = old


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "javascript:alert(1)",
        "http://user:pass@example.com/",
        "http://127.0.0.1/",
        "http://127.1/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fd00:ec2::254]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.100.100.200/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://172.16.3.4/",
        "http://localhost/",
        "http://foo.localhost/",
        "http://metadata.google.internal/",
        "http://printer.local/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://intranet/",
        "http://example.com:22/",
        "http://example.com:6379/",
        "",
    ],
)
def test_validate_url_blocks(url):
    with pytest.raises(BlockedURLError):
        validate_url(url)


@pytest.mark.parametrize("url", ["https://example.com/", "http://example.com/path?q=1", "https://93.184.216.34/"])
def test_validate_url_allows_public(url):
    assert validate_url(url)


@pytest.mark.parametrize(
    "ip,ok",
    [("8.8.8.8", True), ("127.0.0.1", False), ("10.1.1.1", False), ("169.254.169.254", False),
     ("::ffff:10.0.0.1", False), ("2002:7f00:1::", False), ("64:ff9b::7f00:1", False), ("2606:4700::1111", True),
     ("fe80::1", False), ("224.0.0.1", False), ("100.64.0.1", False)],
)
def test_is_public_ip(ip, ok):
    assert is_public_ip(ip) is ok


def _fake_resolver(monkeypatch, answers):
    calls = []

    async def fake_getaddrinfo(self, host, port, *a, **kw):
        calls.append(host)
        result = answers(host, len(calls))
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                for ip in result]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)
    return calls


async def test_hostname_resolving_to_private_is_blocked(monkeypatch):
    _fake_resolver(monkeypatch, lambda h, n: ["10.0.0.7"])
    async with SafeFetcher() as f:
        r = await f.fetch("http://evil.example.com/")
    assert r.error_kind == "blocked", r.error


async def test_mixed_public_private_answers_blocked(monkeypatch):
    _fake_resolver(monkeypatch, lambda h, n: ["93.184.216.34", "127.0.0.1"])
    async with SafeFetcher() as f:
        r = await f.fetch("http://rebind.example.com/")
    assert r.error_kind == "blocked"


async def test_connection_pinned_to_validated_ip(monkeypatch):
    """DNS rebinding: the socket must connect to the address that was validated, resolved once."""
    calls = _fake_resolver(monkeypatch, lambda h, n: ["93.184.216.34"] if n == 1 else ["127.0.0.1"])
    connected = []

    async def fake_connect(self, host, port, timeout=None, local_address=None, socket_options=None):
        connected.append(host)
        raise httpcore.ConnectError("test stop")

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", fake_connect)
    async with SafeFetcher() as f:
        r = await f.fetch("http://rebind.example.com/")
    assert connected == ["93.184.216.34"]
    assert calls == ["rebind.example.com"]
    assert r.error_kind == "network"


async def test_redirect_to_internal_blocked(allow_loopback):
    routes = {
        "/to-localhost": (302, {"Location": "http://localhost:8080/admin"}, ""),
        "/to-metadata": (301, {"Location": "http://169.254.169.254/latest/meta-data/"}, ""),
        "/to-file": (302, {"Location": "file:///etc/passwd"}, ""),
    }
    with FixtureSite(routes) as site:
        async with SafeFetcher() as f:
            for p in routes:
                r = await f.fetch(site.base + p)
                assert r.error_kind == "blocked", (p, r.error)
                assert r.redirect_chain, p


async def test_response_size_cap(allow_loopback):
    big = "x" * (3 * 1024 * 1024)
    with FixtureSite({"/big": (200, {}, big)}) as site:
        async with SafeFetcher(max_bytes=1024 * 1024) as f:
            r = await f.fetch(site.base + "/big")
    assert r.error_kind == "too_large"
    assert r.content == b""


async def test_gzip_bomb_capped(allow_loopback):
    import gzip

    bomb = gzip.compress(b"\0" * (20 * 1024 * 1024))
    with FixtureSite({"/bomb": (200, {"Content-Encoding": "gzip"}, bomb)}) as site:
        async with SafeFetcher(max_bytes=1024 * 1024) as f:
            r = await f.fetch(site.base + "/bomb")
    assert r.error_kind == "too_large"


async def test_timeout(allow_loopback, monkeypatch):
    from tests.fixtures.site import slow

    s = get_settings()
    monkeypatch.setattr(s, "crawler_read_timeout", 0.5)
    monkeypatch.setattr(s, "crawler_total_timeout", 1.0)
    with FixtureSite({"/slow": slow(3)}) as site:
        async with SafeFetcher() as f:
            r = await f.fetch(site.base + "/slow")
    assert r.error_kind == "timeout"


async def test_redirect_loop_detected(allow_loopback):
    with FixtureSite({"/a": (301, {"Location": "/b"}, ""), "/b": (301, {"Location": "/a"}, "")}) as site:
        async with SafeFetcher() as f:
            r = await f.fetch(site.base + "/a")
    assert r.error_kind == "redirect_loop"


async def test_dev_allowlist_refused_in_production(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "ssrf_dev_allow_hosts", "127.0.0.1")
    monkeypatch.setattr(s, "app_env", "production")
    with pytest.raises(BlockedURLError):
        validate_url("http://127.0.0.1/")
    with pytest.raises(RuntimeError):
        s.validate_for_environment()


def test_proxy_env_ignored(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://10.0.0.1:3128")
    f = SafeFetcher()

    async def go():
        async with f:
            assert f.client._mounts == {} or all(v is None for v in f.client._mounts.values())

    asyncio.run(go())
    assert ssrf  # module imported
