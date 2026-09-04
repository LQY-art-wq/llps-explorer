"""Check that this container owns a fresh, runnable RQ worker registration."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from typing import Protocol

from redis import Redis
from rq import Worker

RUNNABLE_STATES = frozenset({"started", "idle", "busy"})
MAX_FUTURE_CLOCK_SKEW_SECONDS = 30


class RegisteredWorker(Protocol):
    hostname: str | None
    last_heartbeat: datetime | None
    worker_ttl: int

    def get_state(self) -> str: ...

    def queue_names(self) -> list[str]: ...


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def registration_is_healthy(
    worker: RegisteredWorker,
    *,
    hostname: str,
    queue_name: str,
    now: datetime,
) -> bool:
    """Reject another container, wrong queue, suspended state, or stale registration."""

    heartbeat = worker.last_heartbeat
    if (
        worker.hostname != hostname
        or queue_name not in worker.queue_names()
        or worker.get_state() not in RUNNABLE_STATES
        or heartbeat is None
    ):
        return False
    age = (_aware_utc(now) - _aware_utc(heartbeat)).total_seconds()
    return -MAX_FUTURE_CLOCK_SKEW_SECONDS <= age <= worker.worker_ttl + 60


def main() -> int:
    connection: Redis | None = None
    try:
        connection = Redis.from_url(
            os.environ["REDIS_URL"],
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        queue_name = os.environ.get("ANALYSIS_QUEUE_NAME", "analysis")
        if not connection.ping():
            return 1
        now = datetime.now(timezone.utc)
        hostname = socket.gethostname()
        workers = Worker.all(connection=connection)
        return 0 if any(
            registration_is_healthy(
                worker,
                hostname=hostname,
                queue_name=queue_name,
                now=now,
            )
            for worker in workers
        ) else 1
    # A health probe is a fail-closed boundary around Redis/RQ; it must never
    # print connection details or a traceback into Docker health logs.
    except Exception:  # noqa: BLE001
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
