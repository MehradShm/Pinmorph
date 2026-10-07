"""Reproducible CLIP crop / exact / HNSW agreement and elapsed latency report."""

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.discovery.crop import CropBox, prepare_crop
from app.feed.contracts import FeedContext
from app.ml.discovery import ClipCropEmbedder, compare_lens_retrieval
from app.ml.retrieval import ExactVectorRetriever, PgvectorANNRetriever
from app.ml.vector_store import CLIP_VERSION, catalog_vectors, runtime_info
from app.models import Pin, User, utcnow
from app.storage import make_s3_client


def measured(call):
    started = perf_counter()
    result = call()
    return result, (perf_counter() - started) * 1000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/reports/phase4-lens.json"))
    parser.add_argument("--queries", type=int, default=8)
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()
    if args.queries <= 0 or args.k <= 0:
        raise SystemExit("Query count and k must be positive")
    settings = Settings()
    engine = make_engine(settings)
    storage = make_s3_client(settings)
    user_id = str(uuid4())
    records = []
    executed_ann = []

    def capture_ann(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT pin_embeddings.pin_id,") and "<=>" in statement:
            executed_ann.append((statement, parameters.copy()))

    event.listen(engine, "before_cursor_execute", capture_ann)
    try:
        with Session(engine) as db:
            db.add(User(id=user_id, display_name="Lens evaluation fixture"))
            db.flush()
            now = utcnow()
            ctx = FeedContext(str(uuid4()), user_id, now, now, surface="lens")
            items = catalog_vectors(db, CLIP_VERSION, ctx)
            if not items:
                raise RuntimeError("Backfill the real catalog before evaluating")
            corpus = sorted(item.pin_id for item in items)
            encoder = ClipCropEmbedder(settings)
            # Force the indexed path on a tiny catalog; report this explicitly.
            db.execute(text("SET LOCAL enable_seqscan = off"))
            db.execute(text("SET LOCAL enable_sort = off"))
            for pin_id in corpus[: args.queries]:
                pin = db.get(Pin, pin_id)
                response = storage.get_object(Bucket=settings.s3_bucket, Key=pin.original_key)
                try:
                    data = response["Body"].read(settings.upload_max_bytes + 1)
                finally:
                    response["Body"].close()
                for box in (CropBox(), CropBox(left=0.2, top=0.2, right=0.8, bottom=0.8)):
                    crop = prepare_crop(data, box, settings)
                    embedding, encode_ms = measured(lambda crop=crop: encoder.embed_crop(crop))
                    exact, exact_ms = measured(
                        lambda embedding=embedding: ExactVectorRetriever().search(
                            embedding, items, ctx, args.k
                        )
                    )
                    ann, ann_ms = measured(
                        lambda embedding=embedding: PgvectorANNRetriever().search(
                            db, embedding, ctx, args.k
                        )
                    )
                    records.append(
                        {
                            "source_pin_id": pin_id,
                            "crop_sha256": crop.crop_sha256,
                            "crop_box": box.model_dump(),
                            "encoder_ms": encode_ms,
                            "exact_ms": exact_ms,
                            "ann_ms": ann_ms,
                            "overlap_at_k": compare_lens_retrieval(exact, ann, args.k),
                            "exact_ids": [h.pin_id for h in exact],
                            "ann_ids": [h.pin_id for h in ann],
                        }
                    )
            statement, parameters = executed_ann[-1]
            plan = (
                db.connection().exec_driver_sql("EXPLAIN " + statement, parameters).scalars().all()
            )
            if not any("ix_lens_clip_hnsw" in line for line in plan):
                raise RuntimeError("Evaluation did not use the required HNSW index")
            report = {
                "schema_version": "lens-evaluation:v1",
                "evaluated_at": now.isoformat(),
                "runtime": runtime_info(settings),
                "corpus_size": len(items),
                "corpus_sha256": hashlib.sha256(json.dumps(corpus).encode()).hexdigest(),
                "k": args.k,
                "query_count": len(records),
                "seqscan_disabled": True,
                "sort_disabled": True,
                "index_plan": [
                    line.split("Order By:")[0] + "Order By: <query vector omitted>"
                    if "Order By:" in line
                    else line
                    for line in plan
                ],
                "mean_overlap_at_k": statistics.mean(r["overlap_at_k"] for r in records),
                "median_exact_ms": statistics.median(r["exact_ms"] for r in records),
                "median_ann_ms": statistics.median(r["ann_ms"] for r in records),
                "median_encoder_ms": statistics.median(r["encoder_ms"] for r in records),
                "limitations": [
                    "Small synthetic demo catalog; agreement is not relevance.",
                    "Exact times exclude vector loading; ANN times include SQL round trips.",
                    "No speed advantage or production quality inferred from this corpus.",
                ],
                "queries": records,
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n")
            db.rollback()  # Evaluation creates no users, requests, views or actions.
        print(
            json.dumps(
                {k: v for k, v in report.items() if k not in {"queries", "runtime", "index_plan"}}
            )
        )
    finally:
        storage.close()
        engine.dispose()


if __name__ == "__main__":
    main()
