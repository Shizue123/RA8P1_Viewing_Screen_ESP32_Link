from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict, deque

from fastapi import Request


def build_script_signature(
    secret: str,
    request_id: str,
    script_id: str,
    intent_type: str,
    checksum: str,
    timestamp: int,
    target_device_id: str,
) -> str:
    canonical = "\n".join(
        [
            secret,
            request_id,
            script_id,
            intent_type,
            str(timestamp),
            checksum,
            target_device_id,
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def extract_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class ApiRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_sec: int) -> bool:
        if limit <= 0 or window_sec <= 0:
            return True

        now = time.monotonic()
        cutoff = now - float(window_sec)
        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
        return True
