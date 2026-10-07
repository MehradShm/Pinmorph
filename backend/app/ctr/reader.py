"""Strict local TSV reader; no downloads, training, catalog import or source relabeling."""

import csv
import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.ctr.contracts import DisplayedNews, Impression, News


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_time(value: str, source_timezone: str) -> datetime:
    naive = datetime.strptime(value, "%m/%d/%Y %I:%M:%S %p")
    zone = ZoneInfo(source_timezone)
    first, second = naive.replace(tzinfo=zone, fold=0), naive.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise ValueError("Ambiguous or nonexistent source time; declare an unambiguous policy")
    if first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive:
        raise ValueError("Nonexistent source time")
    return first.astimezone(UTC)


def rows(path: Path, columns: int) -> Iterator[tuple[int, list[str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for number, row in enumerate(csv.reader(stream, delimiter="\t", quoting=csv.QUOTE_NONE), 1):
            if len(row) != columns:
                raise ValueError(f"{path.name}:{number}: expected {columns} TSV columns")
            yield number, row


def read_news(path: Path) -> dict[str, News]:
    result = {}
    # Official examples contain eight fields; the prose's 'seven' is a documentation typo.
    for number, row in rows(path, 8):
        news_id, category, subcategory, title, abstract, _url, title_entities, abstract_entities = (
            row
        )
        if news_id in result:
            raise ValueError(f"{path.name}:{number}: duplicate news ID")
        for entities in (title_entities, abstract_entities):
            if not isinstance(json.loads(entities), list):
                raise ValueError(f"{path.name}:{number}: entities must be JSON arrays")
        result[news_id] = News(
            news_id=news_id,
            category=category,
            subcategory=subcategory,
            title=title,
            abstract=abstract,
        )
    return result


def read_behaviors(path: Path, partition: str, source_timezone: str) -> Iterator[Impression]:
    if not partition or ":" in partition:
        raise ValueError("Source partition must be nonempty and cannot contain ':'")
    seen = set()
    for number, row in rows(path, 5):
        raw_id, user_id, timestamp, history, candidates = row
        if not raw_id.isdigit() or raw_id in seen:
            raise ValueError(f"{path.name}:{number}: invalid or duplicate impression ID")
        seen.add(raw_id)
        displayed = []
        for token in candidates.split():
            news_id, separator, label = token.rpartition("-")
            if not separator:
                displayed.append(DisplayedNews(news_id=token, clicked=None))
            elif label in {"0", "1"}:
                displayed.append(DisplayedNews(news_id=news_id, clicked=int(label)))
            else:
                raise ValueError(f"{path.name}:{number}: click labels must be 0 or 1")
        history_ids = tuple(history.split())
        # Validate IDs without deduplicating or inventing times for the source history.
        for item in history_ids:
            DisplayedNews(news_id=item, clicked=None)
        yield Impression(
            impression_id=f"{partition}:{raw_id}",
            user_id=user_id,
            occurred_at=source_time(timestamp, source_timezone),
            history=history_ids,
            displayed=tuple(displayed),
            source_partition=partition,
        )


def inspect_partition(root: Path, partition: str, source_timezone: str) -> dict:
    hashes = {name: file_sha256(root / name) for name in ("news.tsv", "behaviors.tsv")}
    news = read_news(root / "news.tsv")
    counts = dict(
        impressions=0,
        displayed=0,
        clicked=0,
        nonclicked=0,
        hidden_labels=0,
        cold_start_impressions=0,
        missing_history_references=0,
    )
    earliest = latest = None
    for impression in read_behaviors(root / "behaviors.tsv", partition, source_timezone):
        counts["impressions"] += 1
        counts["cold_start_impressions"] += not impression.history
        counts["missing_history_references"] += sum(item not in news for item in impression.history)
        earliest = min(earliest or impression.occurred_at, impression.occurred_at)
        latest = max(latest or impression.occurred_at, impression.occurred_at)
        for item in impression.displayed:
            if item.news_id not in news:
                raise ValueError("Displayed news is missing from that partition's catalog")
            counts["displayed"] += 1
            key = (
                "hidden_labels"
                if item.clicked is None
                else "clicked"
                if item.clicked
                else "nonclicked"
            )
            counts[key] += 1
    if hashes != {name: file_sha256(root / name) for name in hashes}:
        raise ValueError("Input changed during inventory; retry against stable local files")
    return {
        "partition": partition,
        "news": len(news),
        "counts": counts,
        "earliest": earliest.isoformat() if earliest else None,
        "latest": latest.isoformat() if latest else None,
        "files_sha256": hashes,
    }
