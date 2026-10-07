"""Import locally supplied H&M data, or an explicitly synthetic demonstration catalog."""

import argparse
import csv
import hashlib
import io
import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic, sleep
from uuid import NAMESPACE_URL, uuid5

from PIL import Image, ImageDraw
from redis import Redis
from rq import Queue
from rq.job import Job
from rq.serializers import JSONSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.media import enqueue_pin, validate_image
from app.models import ImportedInteraction, ImportRun, Pin, User
from app.storage import make_s3_client

IMPORTER_VERSION = "phase1-v1"


def parse_reference_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Reference time must include a UTC offset") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_rows(path: Path, required: set[str]):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f"{path.name} must contain {sorted(required)}")
        yield from reader


def article_id(value: str) -> str:
    if not value.isdigit() or len(value) > 10:
        raise ValueError("H&M article IDs must be numeric and at most 10 digits")
    return value.zfill(10)


@dataclass
class Purchase:
    row_number: int
    customer_id: str
    article_id: str
    original_time: datetime
    metadata: dict


@dataclass
class SeedPlan:
    manifest: dict
    articles: dict[str, dict]
    images: dict[str, Path | bytes]
    customers: list[str]
    purchases: list[Purchase]
    availability: dict[str, datetime]

    @property
    def run_id(self) -> str:
        return hashlib.sha256(json.dumps(self.manifest, sort_keys=True).encode()).hexdigest()

    def entity_id(self, kind: str, source_id: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"pinmorph:{self.run_id}:{kind}:{source_id}"))


def chronological_cutoffs(times: list[datetime], offset: timedelta) -> dict:
    days = sorted(set(times))
    if len(days) < 3:
        return {
            "status": "insufficient_unique_days",
            "train_end_exclusive": None,
            "validation_end_exclusive": None,
            "test_end_inclusive": None,
        }
    train = max(1, min(int(len(days) * 0.8), len(days) - 2))
    validation = max(train + 1, min(int(len(days) * 0.9), len(days) - 1))
    return {
        "status": "proposed_only",
        "policy": "80_10_10_unique_days_keep_ties_together",
        "train_end_exclusive": (days[train] + offset).isoformat(),
        "validation_end_exclusive": (days[validation] + offset).isoformat(),
        "test_end_inclusive": (days[-1] + offset).isoformat(),
    }


def build_hm_plan(
    root: Path,
    seed: int,
    reference_time: datetime,
    max_items: int,
    max_users: int,
    shift_to_reference: bool = False,
) -> SeedPlan:
    files = {
        name: root / name for name in ("articles.csv", "customers.csv", "transactions_train.csv")
    }
    for path in files.values():
        if not path.is_file():
            raise ValueError(f"Missing input: {path}")
    all_articles = {}
    all_images = {}
    missing_images = 0
    for row in csv_rows(files["articles.csv"], {"article_id", "prod_name"}):
        item = article_id(row["article_id"])
        if item in all_articles:
            raise ValueError(f"Duplicate article ID: {item}")
        image = root / "images" / item[:3] / f"{item}.jpg"
        if not image.is_file():
            missing_images += 1
            continue
        all_articles[item], all_images[item] = row, image
    selected = sorted(all_articles)
    random.Random(seed).shuffle(selected)
    selected = sorted(selected[:max_items])
    if not selected:
        raise ValueError("No product images found in images/<first-three-digits>/<article-id>.jpg")
    articles = {item: all_articles[item] for item in selected}
    images = {item: all_images[item] for item in selected}
    customer_ids = {row["customer_id"] for row in csv_rows(files["customers.csv"], {"customer_id"})}
    purchases = []
    earliest = {}
    latest_source_time = None
    skipped_unknown_customers = 0
    # Stream the large transaction file; retain only purchases for the selected catalog.
    for row_number, row in enumerate(
        csv_rows(files["transactions_train.csv"], {"t_dat", "customer_id", "article_id"}), start=2
    ):
        item = article_id(row["article_id"])
        if item not in articles:
            continue
        original_time = datetime.strptime(row["t_dat"], "%Y-%m-%d").replace(tzinfo=UTC)
        if not shift_to_reference and original_time > reference_time:
            continue
        earliest[item] = min(earliest.get(item, original_time), original_time)
        latest_source_time = max(latest_source_time or original_time, original_time)
        if row["customer_id"] not in customer_ids:
            skipped_unknown_customers += 1
            continue
        purchases.append(
            Purchase(
                row_number,
                row["customer_id"],
                item,
                original_time,
                {"price": row.get("price"), "sales_channel_id": row.get("sales_channel_id")},
            )
        )
    selected_customers = sorted({purchase.customer_id for purchase in purchases})
    random.Random(seed + 1).shuffle(selected_customers)
    selected_customers = sorted(selected_customers[:max_users])
    selected_customer_set = set(selected_customers)
    purchases = [
        purchase for purchase in purchases if purchase.customer_id in selected_customer_set
    ]
    # A single global offset preserves chronology across item availability and interactions.
    latest = latest_source_time or reference_time
    offset = reference_time - latest if shift_to_reference else timedelta(0)
    availability = {item: earliest.get(item, reference_time - offset) + offset for item in selected}
    image_hashes = {}
    settings = Settings()
    for item, path in images.items():
        data = path.read_bytes()
        validate_image(data, settings)
        image_hashes[item] = hashlib.sha256(data).hexdigest()
    manifest = {
        "importer_version": IMPORTER_VERSION,
        "dataset": "hm",
        "random_seed": seed,
        "reference_time": reference_time.isoformat(),
        "source_files_sha256": {name: sha256_file(path) for name, path in files.items()},
        "selected_images_sha256": image_hashes,
        "article_ids": selected,
        "customer_ids": selected_customers,
        "sampling_policy": "shuffle_sorted_image_backed_articles_then_matching_customers_v1",
        "limits": {"items": max_items, "users": max_users},
        "counts": {
            "items": len(selected),
            "users": len(selected_customers),
            "purchases": len(purchases),
            "articles_missing_images": missing_images,
            "purchases_unknown_customers": skipped_unknown_customers,
        },
        "label_provenance": "imported_purchase_proxy",
        "timestamp_granularity": "day_utc_keep_ties_together",
        "time_offset_seconds": offset.total_seconds(),
        "item_availability_policy": "earliest_source_purchase_proxy_else_reference_time",
        "cutoffs": chronological_cutoffs([p.original_time for p in purchases], offset),
        "feature_definitions": None,
        "negative_sampling_policy": None,
        "notes": "Imported purchases are historical proxies, never observed app saves/impressions.",
    }
    return SeedPlan(manifest, articles, images, selected_customers, purchases, availability)


def build_demo_plan(seed: int, reference_time: datetime, max_items: int = 32) -> SeedPlan:
    """Small illustrations, generated locally; no downloaded/licensed product content."""
    randomizer = random.Random(seed)
    colors = [
        ("Sage", "#92a18a"),
        ("Terracotta", "#b98168"),
        ("Midnight", "#414950"),
        ("Oat", "#c9bca5"),
        ("Lilac", "#afa0b8"),
        ("Forest", "#50664c"),
        ("Rose", "#c49b96"),
        ("Sky", "#91acb6"),
    ]
    articles, images, availability = {}, {}, {}
    kinds = ["Everyday knit", "Relaxed trousers", "Weekend tote", "Soft layer"]
    for index in range(min(max_items, 32)):
        item = str(index + 1).zfill(10)
        color_name, color = colors[index % len(colors)]
        kind = index % 4
        height = randomizer.choice([920, 1050, 1200, 1320])
        image = Image.new(
            "RGB", (900, height), randomizer.choice(["#e8e4da", "#eeebe3", "#dddcd4"])
        )
        draw = ImageDraw.Draw(image)
        cy = height // 2
        draw.ellipse((155, height - 140, 745, height - 85), fill="#d0cbbf")
        if kind in {0, 3}:
            draw.polygon(
                [
                    (310, cy - 300),
                    (205, cy - 260),
                    (120, cy - 80),
                    (235, cy - 30),
                    (280, cy - 110),
                    (270, cy + 290),
                    (630, cy + 290),
                    (620, cy - 110),
                    (665, cy - 30),
                    (780, cy - 80),
                    (695, cy - 260),
                    (590, cy - 300),
                    (540, cy - 255),
                    (360, cy - 255),
                ],
                fill=color,
            )
            draw.arc((350, cy - 310, 550, cy - 220), 0, 180, fill="#686759", width=9)
            if kind == 3:
                draw.line((450, cy - 240, 450, cy + 285), fill="#e4ddd1", width=5)
                for y in range(cy - 180, cy + 250, 85):
                    draw.ellipse((439, y, 456, y + 17), fill="#d6cab8")
        elif kind == 1:
            draw.polygon(
                [
                    (295, cy - 325),
                    (605, cy - 325),
                    (635, cy + 335),
                    (480, cy + 335),
                    (450, cy - 30),
                    (420, cy + 335),
                    (265, cy + 335),
                ],
                fill=color,
            )
            draw.line((300, cy - 295, 600, cy - 295), fill="#77786c", width=5)
        else:
            draw.arc((300, cy - 340, 600, cy + 10), 180, 360, fill=color, width=35)
            draw.rounded_rectangle((225, cy - 170, 675, cy + 320), radius=40, fill=color)
            draw.line((265, cy - 125, 635, cy - 125), fill="#d5c9b7", width=5)
        output = io.BytesIO()
        image.save(output, "JPEG", quality=90)
        images[item] = output.getvalue()
        articles[item] = {
            "prod_name": f"{color_name} {kinds[kind].lower()}",
            "detail_desc": "A locally generated demo illustration for exploring Pinmorph.",
        }
        availability[item] = reference_time - timedelta(days=index)
    manifest = {
        "importer_version": IMPORTER_VERSION,
        "dataset": "synthetic_demo",
        "random_seed": seed,
        "reference_time": reference_time.isoformat(),
        "article_ids": sorted(articles),
        "selected_images_sha256": {
            item: hashlib.sha256(data).hexdigest() for item, data in images.items()
        },
        "counts": {"items": len(articles), "users": 0, "purchases": 0},
        "label_provenance": "synthetic_demo",
        "time_offset_seconds": 0,
        "cutoffs": {"status": "no_interactions"},
        "notes": "Synthetic catalog illustrations. This is not an H&M dataset import.",
    }
    return SeedPlan(manifest, articles, images, [], [], availability)


def active_job(pin: Pin, queue: Queue) -> bool:
    if not pin.media_job_id:
        return False
    from rq.exceptions import NoSuchJobError

    try:
        job = Job.fetch(pin.media_job_id, connection=queue.connection, serializer=JSONSerializer)
        return job.is_queued or job.is_started or job.is_scheduled or job.is_deferred
    except NoSuchJobError:
        return False


def import_plan(plan: SeedPlan, settings: Settings | None = None) -> dict:
    settings = settings or Settings()
    engine = make_engine(settings)
    storage = make_s3_client(settings)
    connection = Redis.from_url(
        settings.redis_url.get_secret_value(), socket_connect_timeout=2, socket_timeout=5
    )
    queue = Queue("default", connection=connection, serializer=JSONSerializer)
    run_id = plan.run_id
    dataset = plan.manifest["dataset"]
    try:
        with Session(engine) as db:
            if not db.get(ImportRun, run_id):
                db.add(ImportRun(id=run_id, dataset=dataset, manifest=plan.manifest))
                db.commit()
            for customer in plan.customers:
                user_id = plan.entity_id("customer", customer)
                if not db.get(User, user_id):
                    # Imported identities cannot log in; never invent passwords or email addresses.
                    db.add(
                        User(
                            id=user_id,
                            display_name=f"H&M customer {customer[:8]}",
                            source_key=f"{dataset}:{run_id}:{customer}",
                        )
                    )
            db.commit()
            for item, article in plan.articles.items():
                pin_id = plan.entity_id("article", item)
                pin = db.get(Pin, pin_id)
                if pin and pin.status == "ready":
                    continue
                if pin and active_job(pin, queue):
                    continue
                image = plan.images[item]
                data = image.read_bytes() if isinstance(image, Path) else image
                if (
                    hashlib.sha256(data).hexdigest()
                    != plan.manifest["selected_images_sha256"][item]
                ):
                    raise ValueError("Image changed after import planning; rebuild the manifest")
                key = f"pins/{pin_id}/original"
                storage.put_object(
                    Bucket=settings.s3_bucket,
                    Key=key,
                    Body=data,
                    ContentType="application/octet-stream",
                )
                if not pin:
                    pin = Pin(
                        id=pin_id,
                        title=article["prod_name"][:200],
                        description=article.get("detail_desc", "")[:2000],
                        source_key=f"{dataset}:{run_id}:{item}",
                        import_run_id=run_id,
                        provenance=dataset,
                        source_metadata=article,
                        original_key=key,
                        available_at=plan.availability[item],
                        created_at=plan.availability[item],
                    )
                    db.add(pin)
                    db.commit()
                enqueue_pin(db, queue, pin, f"import-{run_id}")
            existing = set(
                db.scalars(
                    select(ImportedInteraction.source_key).where(
                        ImportedInteraction.import_run_id == run_id
                    )
                )
            )
            offset = timedelta(seconds=plan.manifest["time_offset_seconds"])
            for index, purchase in enumerate(plan.purchases):
                source_key = f"{dataset}:{run_id}:transaction:{purchase.row_number}"
                if source_key in existing:
                    continue
                db.add(
                    ImportedInteraction(
                        id=plan.entity_id("purchase", str(purchase.row_number)),
                        source_key=source_key,
                        import_run_id=run_id,
                        user_id=plan.entity_id("customer", purchase.customer_id),
                        pin_id=plan.entity_id("article", purchase.article_id),
                        event_time=purchase.original_time + offset,
                        original_event_time=purchase.original_time,
                        source_metadata=purchase.metadata,
                    )
                )
                if index % 1000 == 999:
                    db.commit()
            db.commit()
        return {
            "run_id": run_id,
            "dataset": dataset,
            "counts": plan.manifest["counts"],
            "media_processing": "asynchronous",
            "writes_performed": True,
        }
    finally:
        connection.close()
        storage.close()
        engine.dispose()


def wait_for_media(run_id: str, seconds: int) -> dict:
    engine = make_engine(Settings())
    deadline = monotonic() + seconds
    try:
        while True:
            with Session(engine) as db:
                statuses = list(db.scalars(select(Pin.status).where(Pin.import_run_id == run_id)))
            counts = {status: statuses.count(status) for status in set(statuses)}
            if all(status == "ready" for status in statuses):
                return counts
            if monotonic() >= deadline:
                raise TimeoutError(f"Media not ready before timeout: {counts}; inspect worker logs")
            sleep(0.5)
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset-dir", type=Path, help="Local licensed H&M dataset folder")
    source.add_argument("--demo", action="store_true", help="Generate a synthetic catalog instead")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs; no service writes")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--reference-time", type=parse_reference_time, required=True)
    parser.add_argument("--max-items", type=int, default=2000)
    parser.add_argument("--max-users", type=int, default=2000)
    parser.add_argument("--shift-to-reference", action="store_true")
    parser.add_argument("--manifest-out", type=Path, help="Write the reproducible manifest as JSON")
    parser.add_argument("--wait", type=int, default=0, help="Seconds to wait for image processing")
    args = parser.parse_args()
    if args.max_items < 1 or args.max_users < 1 or args.wait < 0:
        parser.error("Limits must be positive and wait must be nonnegative")
    if args.demo and args.shift_to_reference:
        parser.error("--shift-to-reference applies only to H&M history")
    try:
        plan = (
            build_demo_plan(args.seed, args.reference_time, args.max_items)
            if args.demo
            else build_hm_plan(
                args.dataset_dir,
                args.seed,
                args.reference_time,
                args.max_items,
                args.max_users,
                args.shift_to_reference,
            )
        )
        manifest = {**plan.manifest, "run_id": plan.run_id}
        if args.manifest_out:
            args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
            args.manifest_out.write_text(json.dumps(manifest, indent=2) + "\n")
        if args.dry_run:
            print(json.dumps({**manifest, "writes_performed": False}, indent=2))
        else:
            result = import_plan(plan)
            if args.wait:
                result["media_status"] = wait_for_media(plan.run_id, args.wait)
            print(json.dumps(result, indent=2))
    except (ValueError, OSError, TimeoutError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
