"""Check real pgvector roundtrips and constraints without generating model embeddings."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.ml.models import EmbeddingModel, PinEmbedding
from app.models import Pin, utcnow

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="Set RUN_INTEGRATION=1"),
]


@pytest.fixture
def vectors():
    engine = make_engine(Settings())
    try:
        with Session(engine) as db:
            model = EmbeddingModel(
                version=f"fixture:{uuid4()}",
                dimension=2,
                architecture="toy",
                checkpoint="fixture",
                weights_sha256="0" * 64,
                preprocess_version="fixture:v1",
                text_policy="fixture:v1",
                image_weight=0.5,
                library_versions={"fixture": "v1"},
            )
            pin = Pin(id=str(uuid4()), title="Vector fixture", original_key="unused/fixture.png")
            db.add_all([model, pin])
            db.flush()
            values = {
                "pin_id": pin.id,
                "embedder_version": model.version,
                "dimension": 2,
                "content_hash": "1" * 64,
                "embedding": [1, 0],
                "known_at": utcnow(),
            }
            db.execute(insert(PinEmbedding).values(**values))
            db.flush()
            try:
                yield db, model, pin, values
            finally:
                db.rollback()
    finally:
        engine.dispose()


def test_vectors_roundtrip_with_cosine_distance_and_separate_model_dimensions(vectors):
    db, model, pin, values = vectors
    row = db.get(PinEmbedding, (pin.id, model.version, values["content_hash"]))
    assert row.embedding.tolist() == pytest.approx([1, 0])
    distance = db.scalar(
        select(PinEmbedding.embedding.cosine_distance([1, 0])).where(
            PinEmbedding.embedder_version == model.version
        )
    )
    assert distance == pytest.approx(0)
    second = EmbeddingModel(
        version=f"fixture:{uuid4()}",
        dimension=3,
        architecture="toy-3d",
        checkpoint="fixture",
        weights_sha256="0" * 64,
        preprocess_version="fixture:v1",
        text_policy="fixture:v1",
        image_weight=0.5,
        library_versions={"fixture": "v1"},
    )
    db.add(second)
    db.flush()
    db.execute(
        insert(PinEmbedding).values(
            **{**values, "embedder_version": second.version, "dimension": 3, "embedding": [0, 0, 1]}
        )
    )
    assert db.get(PinEmbedding, (pin.id, second.version, values["content_hash"])).dimension == 3


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"embedding": [1, 0, 0]}, "ck_pin_embeddings_matching_dimension"),
        (
            {"dimension": 3, "embedding": [1, 0, 0]},
            "fk_pin_embeddings_embedder_version_embedding_models",
        ),
        ({"embedding": [0, 0]}, "ck_pin_embeddings_unit_vector"),
        ({"embedding": [2, 0]}, "ck_pin_embeddings_unit_vector"),
    ],
)
def test_vectors_reject_mismatched_model_dimensions_and_invalid_norm(vectors, changes, constraint):
    db, _, _, values = vectors
    with pytest.raises(IntegrityError) as error, db.begin_nested():
        db.execute(insert(PinEmbedding).values(**{**values, "content_hash": "2" * 64, **changes}))
    assert error.value.orig.diag.constraint_name == constraint


def test_same_content_and_model_cannot_create_duplicate_vector_rows(vectors):
    db, _, _, values = vectors
    with pytest.raises(IntegrityError) as error, db.begin_nested():
        db.execute(insert(PinEmbedding).values(**values))
    assert error.value.orig.diag.constraint_name == "pk_pin_embeddings"
