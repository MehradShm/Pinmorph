"""Explicit, idempotent image/title vector backfill for the existing ready catalog."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.discovery.crop import CropBox, prepare_crop
from app.ml.vector_store import store_content_embedding
from app.models import Pin
from app.storage import make_s3_client


def main():
    settings = Settings()
    engine = make_engine(settings)
    storage = make_s3_client(settings)
    indexed, existing = 0, 0
    try:
        with Session(engine) as db:
            for pin in db.scalars(select(Pin).where(Pin.status == "ready").order_by(Pin.id)):
                response = storage.get_object(Bucket=settings.s3_bucket, Key=pin.original_key)
                try:
                    data = response["Body"].read(settings.upload_max_bytes + 1)
                finally:
                    response["Body"].close()
                pixels = prepare_crop(data, CropBox(), settings).image_bytes
                if store_content_embedding(db, pin, pixels, settings):
                    indexed += 1
                else:
                    existing += 1
                db.commit()
        print(json.dumps({"new_vectors": indexed, "existing_vectors": existing}))
    finally:
        storage.close()
        engine.dispose()


if __name__ == "__main__":
    main()
