"""Poster source URL validation and fetch-boundary tests."""

import pytest

from app.routers.movies import (
    POSTER_MAX_BYTES,
    _all_resolved_addresses_are_public,
    _is_allowed_poster_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://img1.doubanio.com/view/photo/l/public/p123.jpg",
        "https://img2.doubanio.com/view/photo/l/public/p456.webp",
        "https://img12.doubanio.com/path/poster.avif",
        "https://IMG3.DOUBANIO.COM/poster.jpg",
        "https://img1.doubanio.com:443/poster.jpg",
    ],
)
def test_poster_allowlist_accepts_https_douban_image_cdn(url):
    assert _is_allowed_poster_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://img1.doubanio.com/poster.jpg",
        "https://doubanio.com/poster.jpg",
        "https://img1.doubanio.com.evil.example/poster.jpg",
        "https://evil.example/img1.doubanio.com/poster.jpg",
        "https://127.0.0.1/poster.jpg",
        "https://localhost/poster.jpg",
        "https://img1.doubanio.com:8443/poster.jpg",
        "https://user:pass@img1.doubanio.com/poster.jpg",
        "file:///etc/passwd",
        "gopher://img1.doubanio.com/poster.jpg",
    ],
)
def test_poster_allowlist_rejects_untrusted_urls(url):
    assert not _is_allowed_poster_url(url)


def test_poster_download_has_a_strict_size_limit():
    assert POSTER_MAX_BYTES == 8 * 1024 * 1024


@pytest.mark.parametrize(
    "addresses",
    [
        ["8.8.8.8", "1.1.1.1"],
        ["2606:4700:4700::1111"],
    ],
)
def test_poster_dns_accepts_only_public_ip_addresses(addresses):
    assert _all_resolved_addresses_are_public(addresses)


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.0.0.5"],
        ["172.16.0.10"],
        ["192.168.1.1"],
        ["169.254.169.254"],
        ["::1"],
        ["fd00::1"],
        ["8.8.8.8", "192.168.1.10"],
        [],
    ],
)
def test_poster_dns_rejects_private_or_mixed_ip_addresses(addresses):
    assert not _all_resolved_addresses_are_public(addresses)
