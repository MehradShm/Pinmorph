"""Fixed-model, chronological evaluation on identical eligible candidate sets."""

import hashlib
import json
import statistics
from collections import defaultdict

from app.feed.contracts import Candidate, FeedContext
from app.ml.baselines import PopularityRanker, RecencyRanker
from app.ml.config import RerankingConfig
from app.ml.evaluation import catalog_coverage, ndcg_at_k, recall_at_k
from app.ml.ranking import DiversityReranker, LogisticRegressionRanker
from app.ml.training import split_name
from app.models import Pin


def evaluate_ranker(artifact, interactions, catalog, features, *, k=10, owners=None):
    if k <= 0:
        raise ValueError("k must be positive")
    if features.version != artifact.training.feature_schema_version:
        raise ValueError("Evaluation feature schema does not match artifact")
    if any(
        item.embedding.embedder_version != artifact.training.embedding_version for item in catalog
    ):
        raise ValueError("Evaluation catalog uses the wrong embedding space")
    targets = defaultdict(set)
    for event in interactions:
        if (
            event.provenance in artifact.training.source_weights
            and event.action in {"save", "purchase_proxy"}
            and split_name(event.occurred_at, artifact.training.cutoffs) == "test"
        ):
            targets[(event.user_id, event.occurred_at)].add(event.pin_id)
    methods = {
        "recency": RecencyRanker(),
        "popularity": PopularityRanker(),
        "logreg": LogisticRegressionRanker(artifact),
    }
    records, eligible_union, missing_targets = [], set(), 0
    for (user_id, as_of), requested in sorted(targets.items()):
        eligible = [
            item for item in catalog if item.available_at <= as_of and item.known_at <= as_of
        ]
        relevant = requested & {item.pin_id for item in eligible}
        missing_targets += len(requested - relevant)
        if not relevant:
            continue
        context = FeedContext("evaluation", user_id, as_of, as_of, limit=k)
        user = features.user_embedding(user_id, as_of)
        candidates = [
            Candidate(
                Pin(id=item.pin_id, owner_id=(owners or {}).get(item.pin_id)),
                ("candidate:offline-full-eligible:v1",),
                features.build(user_id, item.pin_id, as_of),
            )
            for item in eligible
        ]
        ids = sorted(item.pin_id for item in eligible)
        eligible_union.update(ids)
        rankings = {name: ranker.rank(candidates, context) for name, ranker in methods.items()}
        rankings["similarity"] = sorted(
            rankings["logreg"],
            key=lambda r: (-r.candidate.features["similarity"], r.candidate.pin.id),
        )
        rankings["logreg_diversity"] = DiversityReranker(
            RerankingConfig(), {item.pin_id: item.embedding for item in eligible}
        ).rerank(rankings["logreg"], context)
        rankings["personalized_policy"] = DiversityReranker(
            RerankingConfig(), {item.pin_id: item.embedding for item in eligible}
        ).rerank(rankings["logreg"] if user else rankings["popularity"], context)
        outputs = {}
        for name, rows in rankings.items():
            predictions = [row.candidate.pin.id for row in rows[:k]]
            outputs[name] = {
                "ids": predictions,
                "recall_at_k": recall_at_k(predictions, relevant, k),
                "ndcg_at_k": ndcg_at_k(predictions, relevant, k),
            }
        records.append(
            {
                "user_id": user_id,
                "as_of": as_of.isoformat(),
                "cohort": "warm" if user else "cold",
                "eligible_count": len(ids),
                "candidate_sha256": hashlib.sha256(json.dumps(ids).encode()).hexdigest(),
                "relevant_ids": sorted(relevant),
                "methods": outputs,
            }
        )
    if not records:
        raise ValueError("No eligible final-test targets; evaluation cannot fabricate quality")
    method_names = records[0]["methods"].keys()

    def aggregate(rows):
        return {
            name: {
                "query_count": len(rows),
                "recall_at_k": statistics.mean(r["methods"][name]["recall_at_k"] for r in rows),
                "ndcg_at_k": statistics.mean(r["methods"][name]["ndcg_at_k"] for r in rows),
                "catalog_coverage": catalog_coverage(
                    [r["methods"][name]["ids"] for r in rows],
                    eligible_union,
                ),
            }
            for name in method_names
        }

    return {
        "schema_version": "implicit-evaluation:v1",
        "model_version": artifact.version,
        "training_manifest": artifact.training.model_dump(mode="json"),
        "candidate_policy": "full_eligible_catalog_same_candidates_all_rankers",
        "target_policy": artifact.training.positive_policy,
        "history_policy": artifact.training.evaluation_policy,
        "k": k,
        "query_count": len(records),
        "excluded_unavailable_targets": missing_targets,
        "eligible_catalog_size": len(eligible_union),
        "methods": aggregate(records),
        "cohorts": {
            cohort: aggregate(rows)
            for cohort in ("warm", "cold")
            if (rows := [r for r in records if r["cohort"] == cohort])
        },
        "queries": records,
        "limitations": [
            "Implicit sampled-unobserved task; scores and metrics are not CTR.",
            "Full-catalog offline ranking measures ranking separately from shortlist recall.",
            "Earlier evaluation interactions update history; the model remains fixed.",
        ],
    }
