"""Versioned social, co-board and image-only discovery baselines."""

from dataclasses import replace
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.discovery.crop import PreparedCrop
from app.feed.contracts import Candidate, FeedContext
from app.ml.baselines import CatalogCandidateSource
from app.ml.contracts import Embedding, RetrievalHit, VectorItem
from app.ml.retrieval import ExactVectorRetriever, PgvectorANNRetriever
from app.ml.vector_store import catalog_vectors, encode_image
from app.models import Board, Save, User
from app.social.models import BoardFollow, UserFollow
from app.social.policy import visible_owner


class CropEmbedder(Protocol):
    version: str

    def embed_crop(self, crop: PreparedCrop) -> Embedding: ...


class RelatedSource(Protocol):
    version: str

    def retrieve(
        self, db: Session, context: FeedContext, context_pin_id: str
    ) -> list[Candidate]: ...


class LensSearch(Protocol):
    version: str

    def search(self, db: Session, context: FeedContext, crop: PreparedCrop) -> list[Candidate]: ...


class FollowingCandidateSource:
    version = "candidate:following-read:v1"

    def retrieve(self, db: Session, context: FeedContext) -> list[Candidate]:
        viewer = db.get(User, context.user_id)
        creators = set(
            db.scalars(
                select(UserFollow.followed_id).where(
                    UserFollow.follower_id == context.user_id,
                    UserFollow.created_at <= context.as_of,
                )
            )
        )
        board_pins = set(
            db.scalars(
                select(Save.pin_id)
                .join(Board, Board.id == Save.board_id)
                .join(BoardFollow, BoardFollow.board_id == Board.id)
                .where(
                    BoardFollow.follower_id == context.user_id,
                    BoardFollow.created_at <= context.as_of,
                    Board.is_secret.is_(False),
                    Board.created_at <= context.as_of,
                    Save.created_at <= context.as_of,
                    visible_owner(Board.owner_id, viewer, include_muted=True),
                )
            )
        )
        result = []
        for c in CatalogCandidateSource().retrieve(db, context):
            sources = []
            if c.pin.owner_id in creators:
                sources.append("following:creator:v1")
            if c.pin.id in board_pins:
                sources.append("following:public-board:v1")
            if sources:
                result.append(replace(c, sources=tuple(sources)))
        return result


class RelatedPinSource:
    version = "candidate:related-public-boards:v1"

    def retrieve(self, db: Session, context: FeedContext, context_pin_id: str) -> list[Candidate]:
        viewer = db.get(User, context.user_id)
        boards = (
            select(Save.board_id)
            .join(Board, Board.id == Save.board_id)
            .where(
                Save.pin_id == context_pin_id,
                Save.created_at <= context.as_of,
                Board.is_secret.is_(False),
                Board.created_at <= context.as_of,
                visible_owner(Board.owner_id, viewer, include_muted=True),
            )
        )
        counts = dict(
            db.execute(
                select(Save.pin_id, func.count(func.distinct(Save.board_id)))
                .where(
                    Save.board_id.in_(boards),
                    Save.created_at <= context.as_of,
                    Save.pin_id != context_pin_id,
                )
                .group_by(Save.pin_id)
            ).all()
        )
        base = {
            c.pin.id: c
            for c in CatalogCandidateSource().retrieve(db, context)
            if c.pin.id != context_pin_id
        }
        result = [
            replace(
                base[pin_id],
                sources=(self.version,),
                features=dict(base[pin_id].features, shared_public_boards=float(count)),
                retrieval_score=float(count),
            )
            for pin_id, count in counts.items()
            if pin_id in base
        ]
        if result:
            return sorted(result, key=lambda c: (-c.retrieval_score, c.pin.id))
        items = catalog_vectors(db, ClipCropEmbedder.version, context)
        query = next((item.embedding for item in items if item.pin_id == context_pin_id), None)
        if query is None:
            return []
        hits = ExactVectorRetriever().search(
            query, [item for item in items if item.pin_id != context_pin_id], context, len(items)
        )
        return [
            replace(
                base[h.pin_id],
                sources=("related:clip-fallback:v1",),
                features=dict(base[h.pin_id].features, similarity=h.similarity),
                retrieval_score=h.similarity,
            )
            for h in hits
            if h.pin_id in base
        ]


class ClipCropEmbedder:
    version = "embedder:clip-image-crop:v1"

    def __init__(self, settings=None):
        self.settings = settings or Settings()

    def embed_crop(self, crop: PreparedCrop) -> Embedding:
        return encode_image(crop.image_bytes, self.settings)


def compare_lens_retrieval(
    exact: list[RetrievalHit], approximate: list[RetrievalHit], k: int
) -> float | None:
    if k <= 0:
        raise ValueError("k must be positive")
    for hits in (exact, approximate):
        if len({hit.pin_id for hit in hits}) != len(hits):
            raise ValueError("Duplicate pin identity")
    reference = {hit.pin_id for hit in exact[:k]}
    if not reference:
        return None
    return len(reference & {hit.pin_id for hit in approximate[:k]}) / len(reference)


class LensService:
    version = "surface:lens:v1"

    def __init__(self, crop_embedder: CropEmbedder):
        self.crop_embedder = crop_embedder
        self.retriever = PgvectorANNRetriever()
        self.pool_size = 100

    def search(self, db: Session, context: FeedContext, crop: PreparedCrop) -> list[Candidate]:
        query = self.crop_embedder.embed_crop(crop)
        base = {c.pin.id: c for c in CatalogCandidateSource().retrieve(db, context)}
        if not base:
            return []
        k = min(self.pool_size, len(base))
        if isinstance(self.retriever, ExactVectorRetriever):
            hits = self.retriever.search(
                query, catalog_vectors(db, query.embedder_version, context), context, k
            )
        else:
            hits = self.retriever.search(db, query, context, k)
        return [
            replace(
                base[h.pin_id],
                sources=(self.version, self.retriever.version),
                features=dict(base[h.pin_id].features, similarity=h.similarity),
                retrieval_score=h.similarity,
            )
            for h in hits
            if h.pin_id in base
        ]


def eligible_lens_vectors(
    items: list[VectorItem], embedder_version: str, context: FeedContext
) -> list[VectorItem]:
    if len({item.pin_id for item in items}) != len(items):
        raise ValueError("Duplicate pin identity")
    return [
        item
        for item in items
        if item.embedding.embedder_version == embedder_version
        and item.available_at <= context.as_of
        and item.known_at <= context.as_of
    ]
