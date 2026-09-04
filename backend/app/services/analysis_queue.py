"""Redis-backed dispatch boundary for durable analysis execution.

The database remains the source of truth.  RQ receives only the opaque job id;
protein sequences and imported results are loaded by the worker from SQL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue, Retry, Worker
from rq.exceptions import DuplicateJobError
from rq.serializers import JSONSerializer

if TYPE_CHECKING:
    from app.core.config import Settings


class AnalysisQueueError(RuntimeError):
    """A safe queue error that never embeds a Redis URL or request payload."""


class AnalysisQueue(Protocol):
    def enqueue(self, job_id: str) -> None: ...
    def ping(self) -> bool: ...
    def depth(self) -> int: ...
    def worker_count(self) -> int: ...
    def close(self) -> None: ...


class RQAnalysisQueue:
    """Small RQ adapter with deterministic, duplicate-safe dispatch ids."""

    def __init__(
        self,
        redis_url: str,
        *,
        queue_name: str = "analysis",
        job_timeout_seconds: int = 240,
        queued_ttl_seconds: int = 3600,
        result_ttl_seconds: int = 0,
        failure_ttl_seconds: int = 86400,
        retry_max: int = 2,
        retry_interval_seconds: int = 10,
        connection: Redis | None = None,
        queue: Queue | None = None,
    ) -> None:
        self.redis = (
            connection
            if connection is not None
            else Redis.from_url(
                redis_url,
                decode_responses=False,
                socket_connect_timeout=3,
                socket_timeout=3,
                health_check_interval=30,
            )
        )
        self.queue = (
            queue
            if queue is not None
            else Queue(
                name=queue_name,
                connection=self.redis,
                serializer=JSONSerializer,
            )
        )
        self.job_timeout_seconds = job_timeout_seconds
        self.queued_ttl_seconds = queued_ttl_seconds
        self.result_ttl_seconds = result_ttl_seconds
        self.failure_ttl_seconds = failure_ttl_seconds
        self.retry_max = retry_max
        self.retry_interval_seconds = retry_interval_seconds

    @staticmethod
    def rq_job_id(job_id: str) -> str:
        return f"analysis-job-{job_id}"

    def enqueue(self, job_id: str) -> None:
        """Enqueue exactly one string argument and tolerate an existing dispatch."""
        try:
            self.queue.enqueue_call(
                "app.worker.execute_analysis_job",
                args=(job_id,),
                kwargs=None,
                timeout=self.job_timeout_seconds,
                ttl=self.queued_ttl_seconds,
                result_ttl=self.result_ttl_seconds,
                failure_ttl=self.failure_ttl_seconds,
                retry=Retry(
                    max=self.retry_max,
                    interval=self.retry_interval_seconds,
                ),
                job_id=self.rq_job_id(job_id),
                description=f"analysis job {job_id}",
                unique=True,
            )
        except DuplicateJobError:
            # A deterministic RQ id makes HTTP retries and SQL recovery scans
            # idempotent.  The existing RQ dispatch remains authoritative.
            return
        except (RedisError, OSError, TimeoutError) as error:
            raise AnalysisQueueError("Analysis queue is unavailable.") from error

    def ping(self) -> bool:
        try:
            return bool(self.redis.ping())
        except (RedisError, OSError, TimeoutError):
            return False

    def depth(self) -> int:
        try:
            return int(len(self.queue))
        except (RedisError, OSError, TimeoutError) as error:
            raise AnalysisQueueError("Analysis queue is unavailable.") from error

    def worker_count(self) -> int:
        try:
            return int(Worker.count(queue=self.queue))
        except (RedisError, OSError, TimeoutError) as error:
            raise AnalysisQueueError("Analysis queue is unavailable.") from error

    def close(self) -> None:
        try:
            self.redis.close()
        except (RedisError, OSError):
            pass


def queue_from_settings(settings: Settings) -> RQAnalysisQueue:
    """Build the shared web/worker dispatcher without exposing its URL."""
    if settings.redis_url is None:
        raise AnalysisQueueError("Analysis queue configuration is unavailable.")
    return RQAnalysisQueue(
        settings.redis_url,
        queue_name=settings.analysis_queue_name,
        job_timeout_seconds=int(settings.analysis_job_timeout_seconds) + 60,
        queued_ttl_seconds=settings.analysis_queue_ttl_seconds,
        retry_max=settings.analysis_queue_retry_max,
        retry_interval_seconds=settings.analysis_queue_retry_interval_seconds,
    )
