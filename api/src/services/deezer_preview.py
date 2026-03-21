from typing import Optional

from asgiref.sync import sync_to_async

from ..graphql_types.models import DeezerArtistPreview


class DeezerPreviewService:
    async def get_artist_preview(self, deezer_id: int) -> Optional[DeezerArtistPreview]:
        from src.providers.deezer import DeezerMetadataProvider

        provider = DeezerMetadataProvider()
        result = await sync_to_async(provider.get_artist)(deezer_id)
        if result is None:
            return None

        return DeezerArtistPreview(
            deezer_id=deezer_id,
            name=result.name,
            image_url=result.image_url,
        )
