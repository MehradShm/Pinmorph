import hashlib
import json

from app.experiments.config import Arm, Experiment


def assign_arm(user_id: str, experiment: Experiment) -> Arm:
    payload = json.dumps(
        [user_id, experiment.name, experiment.salt, experiment.version],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    bucket = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 10_000
    boundary = 0
    for arm in experiment.arms:
        boundary += arm.buckets
        if bucket < boundary:
            return arm
    raise ValueError("Experiment does not cover every bucket")
