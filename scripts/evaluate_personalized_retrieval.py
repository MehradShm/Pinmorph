"""Measure exact/HNSW agreement for real fused and two-item mean query vectors."""

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from time import perf_counter

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.feed.contracts import FeedContext
from app.ml.config import EmbeddingConfig
from app.ml.contracts import Embedding
from app.ml.discovery import compare_lens_retrieval
from app.ml.embeddings import normalize_vector
from app.ml.retrieval import ExactVectorRetriever, PgvectorANNRetriever
from app.ml.vector_store import catalog_vectors
from app.models import utcnow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/reports/phase3a-retrieval.json"))
    args = parser.parse_args()
    engine = make_engine(Settings())
    executed = []
    records = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT pin_embeddings.pin_id,") and "<=>" in statement:
            executed.append((statement, parameters.copy()))

    def measured(call):
        start = perf_counter()
        value = call()
        return value, (perf_counter() - start) * 1000

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with Session(engine) as db:
            now = utcnow()
            context = FeedContext("retrieval-evaluation", "anonymous", now, now)
            catalog = catalog_vectors(db, EmbeddingConfig().version, context)
            if len(catalog) < 2:
                raise ValueError("Backfill at least two real content vectors")
            db.execute(text("SET LOCAL enable_seqscan = off"))
            db.execute(text("SET LOCAL enable_sort = off"))
            for i, item in enumerate(catalog[:8]):
                other = catalog[(i + 1) % len(catalog)]
                mean = Embedding(
                    embedder_version=item.embedding.embedder_version,
                    values=normalize_vector(
                        tuple(
                            a + b
                            for a, b in zip(
                                item.embedding.values,
                                other.embedding.values,
                                strict=True,
                            )
                        )
                    ),
                )
                for kind, query in (("pin", item.embedding), ("two_item_mean", mean)):
                    exact, exact_ms = measured(
                        lambda query=query: ExactVectorRetriever().search(
                            query,
                            catalog,
                            context,
                            10,
                        )
                    )
                    ann, ann_ms = measured(
                        lambda query=query: PgvectorANNRetriever().search(
                            db,
                            query,
                            context,
                            10,
                        )
                    )
                    records.append(
                        {
                            "source_pin_id": item.pin_id,
                            "query_kind": kind,
                            "exact_ms": exact_ms,
                            "ann_ms": ann_ms,
                            "overlap_at_10": compare_lens_retrieval(exact, ann, 10),
                            "exact_ids": [h.pin_id for h in exact],
                            "ann_ids": [h.pin_id for h in ann],
                        }
                    )
            statement, parameters = executed[-1]
            plan = (
                db.connection().exec_driver_sql("EXPLAIN " + statement, parameters).scalars().all()
            )
            if not any("ix_personalized_clip_hnsw" in line for line in plan):
                raise ValueError("The measured ANN query did not use the fused recipe index")
            report = {
                "schema_version": "personalized-retrieval-evaluation:v1",
                "as_of": now.isoformat(),
                "embedding_recipe": EmbeddingConfig().model_dump(mode="json"),
                "corpus_size": len(catalog),
                "query_count": len(records),
                "k": 10,
                "corpus_sha256": hashlib.sha256(
                    json.dumps(
                        [item.model_dump(mode="json") for item in catalog],
                        sort_keys=True,
                    ).encode()
                ).hexdigest(),
                "mean_overlap_at_10": statistics.mean(r["overlap_at_10"] for r in records),
                "median_exact_ms": statistics.median(r["exact_ms"] for r in records),
                "median_ann_ms": statistics.median(r["ann_ms"] for r in records),
                "seqscan_disabled": True,
                "sort_disabled": True,
                "index_plan": [
                    line.split("Order By:")[0] + "Order By: <query vector omitted>"
                    if "Order By:" in line
                    else line
                    for line in plan
                ],
                "limitations": [
                    "Small synthetic demo catalog; agreement is not relevance.",
                    "Exact timing excludes loading; ANN includes SQL round trips.",
                    "Forced index confirms the query path, not a speed advantage.",
                ],
                "queries": records,
            }
            db.rollback()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {
                    key: value
                    for key, value in report.items()
                    if key not in {"queries", "index_plan", "embedding_recipe"}
                }
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
