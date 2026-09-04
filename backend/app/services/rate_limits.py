"""Anonymous-session and client-address rate limiting backed by Redis in production."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import math
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

_COUNTER_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


@dataclass(frozen=True)
class RatePolicy:
    limit: int
    window_seconds: int


class NoopRateLimiter:
    async def check(self, *, action: str, owner_id: str, client_address: str) -> int | None:
        return None

    async def ping(self) -> bool:
        return True

    def close(self) -> None:
        return None


class RedisRateLimiter:
    """Fixed-window limiter whose Redis keys contain only keyed digests."""

    def __init__(
        self,
        client: Any,
        *,
        secret: str,
        policies: dict[str, RatePolicy],
        ip_multiplier: int = 4,
        namespace: str = "llps:rate",
    ) -> None:
        if len(secret) < 32:
            raise ValueError("SESSION_SECRET must contain at least 32 characters")
        self._client = client
        self._secret = secret.encode("utf-8")
        self._policies = dict(policies)
        self._ip_multiplier = max(1, ip_multiplier)
        self._namespace = namespace

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        secret: str,
        policies: dict[str, RatePolicy],
        ip_multiplier: int = 4,
    ) -> RedisRateLimiter:
        from redis import Redis

        client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            health_check_interval=30,
        )
        return cls(
            client,
            secret=secret,
            policies=policies,
            ip_multiplier=ip_multiplier,
        )

    def _digest(self, category: str, value: str) -> str:
        return hmac.new(
            self._secret,
            f"{category}:{value}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def _check_sync(self, action: str, owner_id: str, client_address: str) -> int | None:
        policy = self._policies.get(action)
        if policy is None:
            return None
        now = int(time.time())
        window = now // policy.window_seconds
        retry_after = policy.window_seconds - (now % policy.window_seconds)
        session_key = (
            f"{self._namespace}:{action}:session:{self._digest('session', owner_id)}:{window}"
        )
        address_key = (
            f"{self._namespace}:{action}:address:"
            f"{self._digest('address', client_address)}:{window}"
        )
        session_count = int(
            self._client.eval(_COUNTER_SCRIPT, 1, session_key, policy.window_seconds + 1)
        )
        address_count = int(
            self._client.eval(_COUNTER_SCRIPT, 1, address_key, policy.window_seconds + 1)
        )
        if session_count > policy.limit or address_count > policy.limit * self._ip_multiplier:
            return max(1, math.ceil(retry_after))
        return None

    async def check(self, *, action: str, owner_id: str, client_address: str) -> int | None:
        return await asyncio.to_thread(self._check_sync, action, owner_id, client_address)

    async def ping(self) -> bool:
        try:
            return bool(await asyncio.to_thread(self._client.ping))
        except Exception:
            return False

    def close(self) -> None:
        self._client.close()


def client_address(request: Request) -> str:
    settings = request.app.state.settings
    if getattr(settings, "trust_proxy_headers", False):
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    return request.client.host if request.client is not None else "unknown"


async def enforce_rate_limit(request: Request, owner_id: str, action: str) -> None:
    limiter = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        return
    retry_after = await limiter.check(
        action=action,
        owner_id=owner_id,
        client_address=client_address(request),
    )
    if retry_after is None:
        return
    request_id = getattr(request.state, "request_id", None)
    detail: dict[str, Any] = {
        "code": "RATE_LIMITED",
        "message": "Too many requests. Retry after the indicated interval.",
        "retry_after_seconds": retry_after,
    }
    if request_id:
        detail["request_id"] = request_id
    raise HTTPException(
        status_code=429,
        detail=detail,
        headers={"Retry-After": str(retry_after)},
    )
