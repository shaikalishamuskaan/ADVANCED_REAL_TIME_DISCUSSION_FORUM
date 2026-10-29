
import hashlib
import math
import os
import time

import redis
from django.conf import settings
from rest_framework.exceptions import APIException


class RateLimitExceeded(APIException):
    status_code = 429
    default_code = "rate_limited"
    default_detail = "Too many registration attempts. Please try again later."

    def __init__(self, retry_after):
        self.retry_after = max(1, int(retry_after))
        super().__init__(self.default_detail, code=self.default_code)


def get_redis_client():
    """Create a Redis client using the configured application URL."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        raise RuntimeError("REDIS_URL is not configured.")

    return redis.Redis.from_url(redis_url, decode_responses=True)


def enforce_registration_limit(ip_address, *, client=None, now=None):
    """Allow at most five registration attempts per IP in a rolling hour."""
    if not ip_address:
        ip_address = "unknown"

    current_time = time.time() if now is None else now
    window_seconds = 60 * 60
    window_id = int(current_time // window_seconds)

    # Avoid putting raw IP addresses into Redis key names.
    ip_digest = hashlib.sha256(ip_address.encode("utf-8")).hexdigest()
    key = f"rate-limit:register:{ip_digest}:{window_id}"

    redis_client = client or get_redis_client()

    # INCR is atomic, so concurrent requests cannot bypass the counter.
    count = redis_client.incr(key)

    if count == 1:
        redis_client.expire(key, window_seconds)

    if count > 5:
        ttl = redis_client.ttl(key)
        raise RateLimitExceeded(ttl if ttl > 0 else window_seconds)
