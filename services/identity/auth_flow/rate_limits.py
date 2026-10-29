
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


class RateLimitDependencyUnavailable(APIException):
    status_code = 503
    default_code = "dependency_unavailable"
    default_detail = "Authentication rate limiting is temporarily unavailable."


class LoginRateLimitExceeded(APIException):
    status_code = 429
    default_code = "rate_limited"
    default_detail = "Too many login attempts. Please try again later."

    def __init__(self, retry_after):
        self.retry_after = max(1, int(retry_after))
        super().__init__(self.default_detail, code=self.default_code)



def enforce_login_ip_limit(ip_address, *, client=None):
    """Allow at most 10 login attempts per IP per minute."""
    ip_digest = hashlib.sha256(
        (ip_address or "unknown").encode("utf-8")
    ).hexdigest()
    key = f"rate-limit:login:ip:{ip_digest}"

    try:
        redis_client = client or get_redis_client()
        count = redis_client.incr(key)

        if count == 1:
            redis_client.expire(key, 60)

        if count > 10:
            ttl = redis_client.ttl(key)
            raise LoginRateLimitExceeded(ttl if ttl > 0 else 60)

    except LoginRateLimitExceeded:
        raise
    except (redis.RedisError, RuntimeError) as exc:
        raise RateLimitDependencyUnavailable() from exc




def record_login_failure(email, *, client=None):
    """Record a failed login in a 15-minute window."""
    email_digest = hashlib.sha256(
        email.strip().lower().encode("utf-8")
    ).hexdigest()
    key = f"rate-limit:login:failures:{email_digest}"

    try:
        redis_client = client or get_redis_client()
        count = redis_client.incr(key)

        if count == 1:
            redis_client.expire(key, 15 * 60)

    except (redis.RedisError, RuntimeError) as exc:
        raise RateLimitDependencyUnavailable() from exc


def clear_login_failures(email, *, client=None):
    """Clear the failed-login counter after a successful login."""
    email_digest = hashlib.sha256(
        email.strip().lower().encode("utf-8")
    ).hexdigest()
    key = f"rate-limit:login:failures:{email_digest}"

    redis_client = client or get_redis_client()

    try:
        redis_client.delete(key)
    except redis.RedisError as exc:
        raise RateLimitDependencyUnavailable() from exc

def check_login_failure_limit(email, *, client=None):
    """Block login when five failures have already occurred in 15 minutes."""
    email_digest = hashlib.sha256(
        email.strip().lower().encode("utf-8")
    ).hexdigest()
    key = f"rate-limit:login:failures:{email_digest}"

    try:
        redis_client = client or get_redis_client()
        count = int(redis_client.get(key) or 0)

        if count >= 5:
            ttl = redis_client.ttl(key)
            raise LoginRateLimitExceeded(
                ttl if ttl > 0 else 15 * 60
            )
    except LoginRateLimitExceeded:
        raise
    except (redis.RedisError, RuntimeError) as exc:
        raise RateLimitDependencyUnavailable() from exc

def enforce_password_reset_limits(username, ip_address, *, client=None, now=None):
    """Limit password reset by normalized username and source IP."""
    current_time = time.time() if now is None else now
    username_digest = hashlib.sha256(
        username.strip().lower().encode("utf-8")
    ).hexdigest()
    ip_digest = hashlib.sha256(
        (ip_address or "unknown").encode("utf-8")
    ).hexdigest()

    redis_client = client or get_redis_client()

    limits = [
        (f"rate-limit:reset:user:{username_digest}", 5, 15 * 60),
        (f"rate-limit:reset:ip:{ip_digest}", 20, 60 * 60),
    ]

    try:
        for key, maximum, window in limits:
            count = redis_client.incr(key)
            if count == 1:
                redis_client.expire(key, window)

            if count > maximum:
                ttl = redis_client.ttl(key)
                raise LoginRateLimitExceeded(ttl if ttl > 0 else window)

    except LoginRateLimitExceeded:
        raise
    except (redis.RedisError, RuntimeError) as exc:
        raise RateLimitDependencyUnavailable() from exc
