import pytest
from app.core.errors import PolicyRejectedError
from app.core.security import normalize_https_url, validate_allowlist, validate_public_resolution


def test_normalizes_approved_https_url() -> None:
    assert (
        validate_allowlist(
            "https://WWW.GOV.CN/zhengce/a.html?x=1",
            allowed_hosts=("www.gov.cn",),
            allowed_path_prefixes=("/zhengce/",),
        )
        == "https://www.gov.cn/zhengce/a.html?x=1"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://www.gov.cn/zhengce/a.html",
        "https://user:pass@www.gov.cn/zhengce/a.html",
        "https://127.0.0.1/zhengce/a.html",
        "https://localhost/zhengce/a.html",
        "https://www.gov.cn:444/zhengce/a.html",
        "https://www.gov.cn/other/a.html",
        "https://evil.example/zhengce/a.html",
    ],
)
def test_rejects_disallowed_url_shapes(url: str) -> None:
    with pytest.raises(PolicyRejectedError):
        validate_allowlist(
            url,
            allowed_hosts=("www.gov.cn",),
            allowed_path_prefixes=("/zhengce/",),
        )


@pytest.mark.asyncio
async def test_resolution_requires_only_public_addresses() -> None:
    async def public(_host: str) -> list[str]:
        return ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]

    assert await validate_public_resolution("example.com", public)

    async def private(_host: str) -> list[str]:
        return ["93.184.216.34", "169.254.169.254"]

    with pytest.raises(PolicyRejectedError, match="non-public"):
        await validate_public_resolution("example.com", private)


def test_fragment_is_not_silently_discarded() -> None:
    with pytest.raises(PolicyRejectedError, match="fragments"):
        normalize_https_url("https://example.com/page#section")


@pytest.mark.parametrize(
    "url",
    [
        "https://www.sensetime.com/cn/newsevil/123",
        "https://www.sensetime.com/cn/news/../private",
        "https://www.sensetime.com/cn/news/%2e%2e/private",
        "https://www.sensetime.com/cn/news/%252e%252e/private",
        "https://www.sensetime.com/cn/news%2f..%2fprivate",
    ],
)
def test_path_prefix_requires_a_segment_boundary_and_rejects_encoded_traversal(
    url: str,
) -> None:
    with pytest.raises(PolicyRejectedError):
        validate_allowlist(
            url,
            allowed_hosts=("www.sensetime.com",),
            allowed_path_prefixes=("/cn/news",),
        )
