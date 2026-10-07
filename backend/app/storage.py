import boto3
from botocore.config import Config

from app.config import Settings


def make_s3_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name="us-east-1",
        config=Config(
            connect_timeout=settings.health_timeout_seconds,
            read_timeout=settings.health_timeout_seconds,
            retries={"max_attempts": 0},
            s3={"addressing_style": "path"},
        ),
    )
