"""Resolve independent learning modules from versioned config, before accepting traffic."""

from collections.abc import Callable

from app.discovery.config import DiscoveryConfig
from app.feed.contracts import CandidateSource
from app.feed.registry import Registry
from app.ml.discovery import (
    ClipCropEmbedder,
    CropEmbedder,
    FollowingCandidateSource,
    LensSearch,
    LensService,
    RelatedPinSource,
    RelatedSource,
)


class DiscoveryServices:
    def __init__(
        self,
        config: DiscoveryConfig,
        *,
        settings=None,
        following_registry: Registry[CandidateSource] | None = None,
        related_registry: Registry[RelatedSource] | None = None,
        crop_registry: Registry[CropEmbedder] | None = None,
        lens_registry: Registry[Callable[[CropEmbedder], LensSearch]] | None = None,
    ):
        self.config = config
        if following_registry is None:
            following_registry = Registry()
            following_registry.register(
                FollowingCandidateSource.version, FollowingCandidateSource()
            )
        if related_registry is None:
            related_registry = Registry()
            related_registry.register(RelatedPinSource.version, RelatedPinSource())
        if crop_registry is None:
            crop_registry = Registry()
            crop_registry.register(ClipCropEmbedder.version, ClipCropEmbedder(settings))
        if lens_registry is None:
            lens_registry = Registry()
            lens_registry.register(LensService.version, LensService)
        self.following_source = following_registry.resolve(config.following_source)
        self.related_source = related_registry.resolve(config.related_source)
        self.crop_embedder = crop_registry.resolve(config.crop_embedder)
        self.lens_service = lens_registry.resolve(config.lens_service)(self.crop_embedder)
        if isinstance(self.lens_service, LensService):
            from app.ml.retrieval import ExactVectorRetriever, PgvectorANNRetriever

            self.lens_service.retriever = (
                ExactVectorRetriever()
                if config.lens_retriever == ExactVectorRetriever.version
                else PgvectorANNRetriever()
            )
            self.lens_service.pool_size = config.lens_pool_size
