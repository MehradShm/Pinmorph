from botocore.exceptions import ClientError

from app.config import Settings
from app.storage import make_s3_client


def main() -> None:
    settings = Settings()
    client = make_s3_client(settings)
    try:
        try:
            client.head_bucket(Bucket=settings.s3_bucket)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {"404", "NoSuchBucket"}:
                raise
            client.create_bucket(Bucket=settings.s3_bucket)
        print(f"Object storage bucket ready: {settings.s3_bucket}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
