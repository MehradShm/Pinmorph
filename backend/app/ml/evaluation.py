import math


def recall_at_k(predicted: list[str], relevant: set[str], k: int) -> float | None:
    """Unique predictions in first k; hits/all relevant. Empty targets return None; k > 0."""
    if k <= 0:
        raise ValueError("k must be positive")
    return len(set(predicted[:k]) & relevant) / len(relevant) if relevant else None


def ndcg_at_k(predicted: list[str], relevant: set[str], k: int) -> float | None:
    """Binary gain, log2(rank+1) discount, ideal min(k, relevant count); duplicate gain once."""
    if k <= 0:
        raise ValueError("k must be positive")
    if not relevant:
        return None
    seen = set()
    gain = 0.0
    for position, pin_id in enumerate(predicted[:k], 1):
        if pin_id in relevant and pin_id not in seen:
            gain += 1 / math.log2(position + 1)
        seen.add(pin_id)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return gain / ideal


def catalog_coverage(predicted: list[list[str]], eligible_catalog: set[str]) -> float | None:
    """Unique eligible recommended pins / eligible catalog size; empty catalog returns None."""
    seen = {pin_id for page in predicted for pin_id in page}
    if not seen <= eligible_catalog:
        raise ValueError("Prediction outside eligible catalog")
    return len(seen) / len(eligible_catalog) if eligible_catalog else None
