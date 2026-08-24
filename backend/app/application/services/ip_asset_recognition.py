from __future__ import annotations

import asyncio

from app.application.ports.ip_assets import IpAssetRecognitionModel
from app.core.errors import IpAssetUploadRejectedError
from app.domain.ip_asset_recognition import (
    IpAssetRecognitionSuggestion,
    normalize_ip_asset_recognition_request,
)
from app.domain.ip_assets import IpAssetValidationError, validate_ip_asset_upload


class IpAssetRecognitionService:
    """Application boundary for one transient, provider-assisted upload suggestion."""

    def __init__(self, model: IpAssetRecognitionModel) -> None:
        self._model = model

    async def recognize(
        self, *, filename: str, media_type: str | None, body: bytes
    ) -> IpAssetRecognitionSuggestion:
        try:
            validated = await asyncio.to_thread(
                validate_ip_asset_upload,
                filename=filename,
                declared_media_type=media_type,
                body=body,
            )
            normalized = await asyncio.to_thread(
                normalize_ip_asset_recognition_request,
                validated,
            )
        except (IpAssetValidationError, ValueError) as error:
            code = error.code if isinstance(error, IpAssetValidationError) else "invalid_raster"
            raise IpAssetUploadRejectedError(code) from error
        return await self._model.suggest(normalized)
