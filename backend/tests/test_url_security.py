import pytest

from app.core.url_security import check_target_url


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000", "http://localhost:3000", "http://10.0.0.5", "http://192.168.1.10/admin",
    "http://[::1]/", "http://169.254.169.254/latest/meta-data/", "ftp://example.com", "file:///etc/passwd",
    "javascript:alert(1)", "http://user:secret@example.com/", "not a url",
])
async def test_blocked_when_private_networks_disallowed(url):
    r = await check_target_url(url, allow_private=False)
    assert not r.ok and r.error


async def test_cloud_metadata_always_blocked_even_if_private_allowed():
    r = await check_target_url("http://169.254.169.254/", allow_private=True)
    assert not r.ok


async def test_private_allowed_only_with_warning():
    r = await check_target_url("http://127.0.0.1:8080", allow_private=True)
    assert r.ok and any("local/private" in w for w in r.warnings)


async def test_plain_http_public_ip_warns():
    r = await check_target_url("http://93.184.216.34/", allow_private=False)
    assert r.ok and any("plain HTTP" in w for w in r.warnings)
