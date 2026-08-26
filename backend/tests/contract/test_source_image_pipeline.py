import asyncio
from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

import httpx
import pytest
from app.application.ports.acquisition import SourceArticleImageIntent
from app.application.services.execute_acquisition import AcquisitionExecutor
from app.core.config import Settings
from app.core.errors import AppError, PermanentFetchError, PolicyRejectedError
from app.domain.entities import DiscoveredItem, FetchedResponse, SourceImageReference, SourceProfile
from app.domain.enums import SourceTier
from app.infrastructure.ingestion.connectors import HtmlConnector
from app.infrastructure.ingestion.source_image_fetcher import SafeSourceImageFetcher
from PIL import Image


def _profile() -> SourceProfile:
    return SourceProfile(
        source_id=uuid4(),
        source_version_id=uuid4(),
        slug="fixture",
        display_name="Fixture",
        organization_type="test",
        tier=SourceTier.A,
        connector_key="fixture_v1",
        entry_url="https://source.example/news/",
        allowed_hosts=("source.example",),
        allowed_path_prefixes=("/news/",),
        connector_version="1.0.0",
        parser_version="1.0.0",
    )


def _raster(media_type: str = "image/png", *, size: tuple[int, int] = (640, 360)) -> bytes:
    output = BytesIO()
    image = Image.new("RGB", size, (25, 90, 180))
    image.save(
        output, format={"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[media_type]
    )
    return output.getvalue()


def _animated_webp() -> bytes:
    output = BytesIO()
    frames = [Image.new("RGB", (640, 360), color) for color in ((20, 30, 40), (80, 90, 100))]
    frames[0].save(output, format="WEBP", save_all=True, append_images=frames[1:], duration=50)
    return output.getvalue()


def test_extracts_bounded_ordered_same_page_images_without_io() -> None:
    profile = _profile()
    url = "https://source.example/news/2026/article.html"
    html = """
    <html><head><meta property="og:title" content="Science news">
      <meta property="og:image" content="/news/media/lead.jpg"></head>
    <body><article><p>This is a long article body with enough text for deterministic extraction.
      It contains a governed news report and additional explanatory paragraphs for readers.</p>
      <figure><img data-src="../media/body.png" alt="课堂实验现场">
        <figcaption>学生在老师指导下完成实验 <span class="credit">摄影: 测试机构</span></figcaption>
      </figure>
      <img src="/news/media/logo.png" class="site-logo" alt="logo">
      <img src="https://cdn.example/news/other.jpg" alt="off domain">
      <img src="/news/media/signed.jpg?token=secret" alt="signed">
      <img src="/news/media/body.png" alt="duplicate">
    </article></body></html>
    """
    document = HtmlConnector(lambda _url: True, ("article",)).extract(
        FetchedResponse(
            requested_url=url,
            final_url=url,
            status_code=200,
            media_type="text/html",
            body=html.encode(),
            sha256="detail",
            fetched_at=datetime.now(UTC),
        ),
        DiscoveredItem(source_item_id="article", url=url),
        profile,
    )

    assert [(item.ordinal, item.role, item.image_url) for item in document.source_images] == [
        (0, "lead", "https://source.example/news/media/lead.jpg"),
        (1, "body", "https://source.example/news/media/body.png"),
    ]
    assert document.source_images[1].alt_text == "课堂实验现场"
    assert document.source_images[1].caption == "学生在老师指导下完成实验 摄影: 测试机构"
    assert document.source_images[1].credit == "摄影: 测试机构"


async def _public_resolver(_host: str) -> list[str]:
    return ["93.184.216.34"]


@pytest.mark.asyncio
@pytest.mark.parametrize("media_type", ["image/jpeg", "image/png", "image/webp"])
async def test_fetcher_preserves_validated_raster_bytes(media_type: str) -> None:
    body = _raster(media_type)
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, headers={"Content-Type": media_type}, content=body)

    reference = SourceImageReference(
        image_url="https://source.example/news/media/image",
        source_page_url="https://source.example/news/article.html",
        ordinal=0,
        role="lead",
    )
    fetched = await SafeSourceImageFetcher(
        Settings(),
        resolver=_public_resolver,
        transport=httpx.MockTransport(handler),
    ).fetch(reference, _profile())

    assert requests == 1
    assert fetched.response.body == body
    assert fetched.response.media_type == media_type
    assert (fetched.width, fetched.height) == (640, 360)


@pytest.mark.asyncio
async def test_fetcher_rejects_cross_host_before_request_and_mime_mismatch() -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "image/jpeg"},
            content=_raster("image/png"),
        )

    fetcher = SafeSourceImageFetcher(
        Settings(), resolver=_public_resolver, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(PolicyRejectedError, match="host"):
        await fetcher.fetch(
            SourceImageReference(
                image_url="https://other.example/news/image.jpg",
                source_page_url="https://source.example/news/article.html",
                ordinal=0,
                role="lead",
            ),
            _profile(),
        )
    assert requests == 0

    with pytest.raises(PermanentFetchError, match="MIME"):
        await fetcher.fetch(
            SourceImageReference(
                image_url="https://source.example/news/image.jpg",
                source_page_url="https://source.example/news/article.html",
                ordinal=0,
                role="lead",
            ),
            _profile(),
        )
    assert requests == 1


@pytest.mark.asyncio
async def test_fetcher_rejects_private_dns_and_cross_host_redirect_without_following() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "https://cdn.example/news/image.jpg"},
        )

    reference = SourceImageReference(
        image_url="https://source.example/news/image.jpg",
        source_page_url="https://source.example/news/article.html",
        ordinal=0,
        role="lead",
    )
    private_fetcher = SafeSourceImageFetcher(
        Settings(),
        resolver=lambda _host: _resolved(["127.0.0.1"]),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(PolicyRejectedError, match="non-public"):
        await private_fetcher.fetch(reference, _profile())
    assert requests == []

    public_fetcher = SafeSourceImageFetcher(
        Settings(), resolver=_public_resolver, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(PolicyRejectedError, match="host"):
        await public_fetcher.fetch(reference, _profile())
    assert requests == ["https://source.example/news/image.jpg"]


async def _resolved(addresses: list[str]) -> list[str]:
    return addresses


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "body", "error"),
    [
        (
            {"Content-Type": "image/png", "Content-Length": str(15 * 1024 * 1024 + 1)},
            b"",
            "response_too_large",
        ),
        (
            {"Content-Type": "image/png"},
            _raster(size=(319, 180)),
            "source_image_too_small",
        ),
        (
            {"Content-Type": "image/webp"},
            _animated_webp(),
            "source_image_animated_rejected",
        ),
    ],
)
async def test_fetcher_rejects_oversize_too_small_and_animated_images(
    headers: dict[str, str], body: bytes, error: str
) -> None:
    fetcher = SafeSourceImageFetcher(
        Settings(),
        resolver=_public_resolver,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, headers=headers, content=body)
        ),
    )
    with pytest.raises(AppError) as caught:
        await fetcher.fetch(
            SourceImageReference(
                image_url="https://source.example/news/image",
                source_page_url="https://source.example/news/article.html",
                ordinal=0,
                role="lead",
            ),
            _profile(),
        )
    assert caught.value.code == error


@pytest.mark.asyncio
async def test_fetcher_maps_pillow_decompression_bomb_to_dimensions_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_decompression_bomb(_stream: object) -> None:
        raise Image.DecompressionBombError("pixel limit")

    monkeypatch.setattr(Image, "open", raise_decompression_bomb)
    fetcher = SafeSourceImageFetcher(
        Settings(),
        resolver=_public_resolver,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "image/png"},
                content=b"oversized-raster-header",
            )
        ),
    )

    with pytest.raises(AppError) as caught:
        await fetcher.fetch(
            SourceImageReference(
                image_url="https://source.example/news/image.png",
                source_page_url="https://source.example/news/article.html",
                ordinal=0,
                role="lead",
            ),
            _profile(),
        )

    assert caught.value.code == "source_image_dimensions_exceeded"


@pytest.mark.asyncio
async def test_optional_image_failure_does_not_reject_news_or_repeat_get() -> None:
    class Repository:
        def __init__(self) -> None:
            self.intent_id = uuid4()
            self.status = "discovered"
            self.reservations = 0
            self.failures = 0

        async def reserve_source_image(self, **_kwargs: object) -> SourceArticleImageIntent:
            self.reservations += 1
            return SourceArticleImageIntent(
                id=self.intent_id,
                status=self.status,  # type: ignore[arg-type]
                request_fingerprint="a" * 64,
            )

        async def reserve_source_request_slot(self, **_kwargs: object) -> float:
            return 0

        async def fail_source_image(self, **_kwargs: object) -> None:
            self.failures += 1
            self.status = "failed"

    class Fetcher:
        def __init__(self) -> None:
            self.calls = 0

        async def fetch(self, *_args: object) -> None:
            self.calls += 1
            raise PermanentFetchError("source_image_http_404")

    repository = Repository()
    fetcher = Fetcher()
    executor = object.__new__(AcquisitionExecutor)
    executor._repository = repository  # type: ignore[attr-defined]
    executor._source_image_fetcher = fetcher  # type: ignore[attr-defined]
    executor._snapshot_store = object()  # type: ignore[attr-defined]
    executor._sleep = None  # type: ignore[attr-defined]
    claimed = type(
        "Claimed",
        (),
        {
            "run_id": uuid4(),
            "job_id": uuid4(),
            "profile": _profile(),
        },
    )()
    reference = SourceImageReference(
        image_url="https://source.example/news/image.jpg",
        source_page_url="https://source.example/news/article.html",
        ordinal=0,
        role="lead",
    )

    for _attempt in range(2):
        assert (
            await executor._acquire_source_images(  # type: ignore[attr-defined]
                claimed=claimed,
                lease_lost=asyncio.Event(),
                candidate_id=uuid4(),
                detail_snapshot_id=uuid4(),
                references=(reference,),
            )
            == 0
        )

    assert repository.reservations == 2
    assert repository.failures == 1
    assert fetcher.calls == 1


@pytest.mark.asyncio
async def test_unknown_image_failure_is_rethrown_and_leaves_intent_retryable() -> None:
    class Repository:
        def __init__(self) -> None:
            self.intent_id = uuid4()
            self.failures = 0

        async def reserve_source_image(self, **_kwargs: object) -> SourceArticleImageIntent:
            return SourceArticleImageIntent(
                id=self.intent_id,
                status="discovered",
                request_fingerprint="a" * 64,
            )

        async def reserve_source_request_slot(self, **_kwargs: object) -> float:
            return 0

        async def fail_source_image(self, **_kwargs: object) -> None:
            self.failures += 1

    class Fetcher:
        async def fetch(self, *_args: object) -> None:
            raise RuntimeError("unexpected storage boundary failure")

    repository = Repository()
    executor = object.__new__(AcquisitionExecutor)
    executor._repository = repository  # type: ignore[attr-defined]
    executor._source_image_fetcher = Fetcher()  # type: ignore[attr-defined]
    executor._snapshot_store = object()  # type: ignore[attr-defined]
    claimed = type(
        "Claimed",
        (),
        {
            "run_id": uuid4(),
            "job_id": uuid4(),
            "profile": _profile(),
        },
    )()

    with pytest.raises(RuntimeError, match="unexpected storage boundary failure"):
        await executor._acquire_source_images(  # type: ignore[attr-defined]
            claimed=claimed,
            lease_lost=asyncio.Event(),
            candidate_id=uuid4(),
            detail_snapshot_id=uuid4(),
            references=(
                SourceImageReference(
                    image_url="https://source.example/news/image.jpg",
                    source_page_url="https://source.example/news/article.html",
                    ordinal=0,
                    role="lead",
                ),
            ),
        )

    assert repository.failures == 0
