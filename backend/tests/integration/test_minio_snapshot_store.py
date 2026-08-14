from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from app.infrastructure.storage.minio_snapshot_store import MinioSnapshotStore
from minio import Minio

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_minio_snapshot_is_content_addressed_and_reused(
    integration_context: IntegrationContext,
) -> None:
    store = MinioSnapshotStore(integration_context.settings)
    body = f"immutable evidence fixture {uuid4()}".encode()
    first = await store.put_immutable(body, "text/plain")
    second = await store.put_immutable(body, "text/plain")
    assert first == second
    assert first.object_key.endswith(first.sha256)

    minio_endpoint = urlsplit(integration_context.settings.minio_endpoint)
    client = Minio(
        minio_endpoint.netloc,
        access_key=integration_context.settings.minio_access_key.get_secret_value(),
        secret_key=integration_context.settings.minio_secret_key.get_secret_value(),
        secure=minio_endpoint.scheme == "https",
    )
    response = client.get_object(first.bucket, first.object_key)
    try:
        assert response.read() == body
    finally:
        response.close()
        response.release_conn()
