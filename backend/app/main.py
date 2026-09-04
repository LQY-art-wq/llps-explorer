import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.adapters.dismeta import DisMetaAdapter
from app.adapters.fuzdrop_remote import FuzDropRemoteAdapter
from app.adapters.lreca import LRECAAdapter
from app.adapters.lreca_remote import RemoteLRECAAdapter
from app.adapters.seg import SEGAdapter
from app.adapters.seg_queued import QueuedSEGAdapter
from app.api.analysis import router as analysis_router
from app.api.config import router as config_router
from app.api.dismeta import router as dismeta_router
from app.api.fuzdrop import router as fuzdrop_router
from app.api.health import ops_router as health_ops_router
from app.api.health import router as health_router
from app.api.lreca import router as lreca_router
from app.api.methods import router as methods_router
from app.api.seg import router as seg_router
from app.api.seg import safe_seg_failure
from app.api.system import router as system_router
from app.api.system import version_router
from app.core.config import Settings, get_settings
from app.core.observability import ProductionHTTPMiddleware, configure_logging
from app.persistence.database import create_database_engine
from app.persistence.migrations import upgrade_database
from app.services.analysis_jobs import AnalysisJobService
from app.services.analysis_queue import queue_from_settings
from app.services.ensemble import EnsembleCalculator
from app.services.lreca_errors import (
    LRECAAnalysisError,
    LRECATimeoutError,
    LRECAUnavailableError,
)
from app.services.method_registry import MethodRegistry
from app.services.orchestrator import AnalysisOrchestrator
from app.services.persistent_repositories import (
    SQLAnalysisJobRepository,
    SQLImportedResultStore,
)
from app.services.rate_limits import NoopRateLimiter, RatePolicy, RedisRateLimiter

logger = logging.getLogger(__name__)


def create_lreca_adapter(settings: Settings):
    """Keep local development intact while production uses the internal service."""

    if settings.lreca_service_url is None:
        return LRECAAdapter(settings)
    return RemoteLRECAAdapter(
        settings.lreca_service_url,
        request_timeout_seconds=settings.lreca_service_timeout_seconds,
        connect_timeout_seconds=settings.lreca_service_connect_timeout_seconds,
        expected_checkpoint_sha256=settings.lreca_checkpoint_sha256,
    )


def create_app(
    settings: Settings | None = None,
    *,
    lreca_adapter: LRECAAdapter | None = None,
    fuzdrop_adapter: FuzDropRemoteAdapter | None = None,
    seg_adapter: SEGAdapter | None = None,
    dismeta_adapter: DisMetaAdapter | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(
        service="llps-backend",
        level=settings.log_level,
        structured=settings.environment == "production" or settings.structured_logging,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        # Construction is deferred until startup; importing the API never loads Torch.
        adapter = lreca_adapter if lreca_adapter is not None else create_lreca_adapter(settings)
        fuzdrop = fuzdrop_adapter if fuzdrop_adapter is not None else FuzDropRemoteAdapter(settings)
        seg = None
        dismeta = None
        imported_store = None
        registry = None
        analysis_service = None
        database_engine = None
        analysis_queue = None
        rate_limiter = NoopRateLimiter()
        application.state.lreca_adapter = adapter
        application.state.fuzdrop_adapter = fuzdrop
        application.state.seg_adapter = seg
        application.state.seg_startup_error_code = "SEG_UNAVAILABLE"
        application.state.seg_startup_error_status = 503
        application.state.dismeta_adapter = dismeta
        application.state.rate_limiter = rate_limiter
        try:
            database_engine = create_database_engine(settings.database_url)
            application.state.database_engine = database_engine
            if settings.environment != "production" or settings.run_migrations_on_startup:
                upgrade_database(database_engine)
            if settings.analysis_queue_backend == "rq":
                analysis_queue = queue_from_settings(settings)
                application.state.analysis_queue = analysis_queue
                if not analysis_queue.ping():
                    raise RuntimeError("Analysis queue readiness check failed.")
            if settings.environment == "production":
                assert settings.redis_url is not None
                rate_limiter = RedisRateLimiter.from_url(
                    settings.redis_url,
                    secret=settings.session_secret.get_secret_value(),
                    policies={
                        "analysis_submit": RatePolicy(
                            settings.rate_limit_analysis_requests,
                            settings.rate_limit_window_seconds,
                        ),
                        "fuzdrop_import": RatePolicy(
                            settings.rate_limit_import_requests,
                            settings.rate_limit_window_seconds,
                        ),
                        "analysis_delete": RatePolicy(
                            settings.rate_limit_delete_requests,
                            settings.rate_limit_window_seconds,
                        ),
                        "analysis_export": RatePolicy(
                            settings.rate_limit_export_requests,
                            settings.rate_limit_window_seconds,
                        ),
                    },
                    ip_multiplier=settings.rate_limit_ip_multiplier,
                )
                if not await rate_limiter.ping():
                    raise RuntimeError("Production rate-limit storage is unavailable.")
                application.state.rate_limiter = rate_limiter
            try:
                await adapter.load()
            except (LRECAUnavailableError, LRECATimeoutError, LRECAAnalysisError):
                logger.exception("LRECA startup failed; analysis requests will report unavailable.")
            try:
                await fuzdrop.load()
            except Exception:
                logger.exception("FuzDrop initialization failed; local methods remain available.")
                # None activates the API's local, audited MODE C unavailable fallback.
                application.state.fuzdrop_adapter = None
            try:
                if seg_adapter is not None:
                    seg = seg_adapter
                elif analysis_queue is not None:
                    seg = QueuedSEGAdapter(settings, analysis_queue)
                else:
                    seg = SEGAdapter(settings)
                application.state.seg_adapter = seg
                await seg.load()
            except Exception as error:
                logger.warning("SEG initialization failed (%s).", type(error).__name__)
                if not isinstance(seg, QueuedSEGAdapter):
                    application.state.seg_adapter = None
                code, status_code = safe_seg_failure(error)
                application.state.seg_startup_error_code = code
                application.state.seg_startup_error_status = status_code
            try:
                dismeta = (
                    dismeta_adapter if dismeta_adapter is not None else DisMetaAdapter(settings)
                )
                application.state.dismeta_adapter = dismeta
                await dismeta.load()
            except Exception as error:
                logger.warning("DisMeta initialization unavailable (%s).", type(error).__name__)
                application.state.dismeta_adapter = None
            retention_seconds = settings.analysis_retention_days * 86400
            imported_store = SQLImportedResultStore(
                database_engine,
                ttl_seconds=retention_seconds,
                max_entries=settings.external_result_max_entries,
            )
            registry = MethodRegistry(
                {
                    "lreca": application.state.lreca_adapter,
                    "fuzdrop": application.state.fuzdrop_adapter,
                    "seg": application.state.seg_adapter,
                    "dismeta": application.state.dismeta_adapter,
                },
                manual_import_enabled=settings.fuzdrop_manual_import_enabled,
            )
            analysis_service = AnalysisJobService(
                orchestrator=AnalysisOrchestrator(
                    registry,
                    imported_store,
                    ensemble=EnsembleCalculator(settings.ensemble_threshold),
                    method_timeout_seconds=settings.analysis_method_timeout_seconds,
                    job_timeout_seconds=settings.analysis_job_timeout_seconds,
                ),
                ttl_seconds=retention_seconds,
                max_jobs=settings.analysis_max_jobs,
                max_concurrent_jobs=settings.analysis_max_concurrent_jobs,
                max_sequence_length=settings.analysis_max_sequence_length,
                store=SQLAnalysisJobRepository(
                    database_engine,
                    max_jobs=settings.analysis_max_jobs,
                    max_active_jobs=(
                        settings.analysis_queue_max_jobs
                        if settings.analysis_queue_backend == "rq"
                        else None
                    ),
                    max_active_jobs_per_owner=(
                        settings.analysis_owner_active_job_limit
                        if settings.analysis_queue_backend == "rq"
                        else None
                    ),
                ),
                cleanup_interval_seconds=settings.analysis_cleanup_interval_seconds,
                queue=analysis_queue,
            )
            application.state.imported_result_store = imported_store
            application.state.method_registry = registry
            application.state.analysis_service = analysis_service
            await analysis_service.start()
            yield
        finally:
            try:
                try:
                    if analysis_service is not None:
                        await analysis_service.close()
                except Exception as error:
                    logger.warning("Analysis shutdown failed (%s).", type(error).__name__)
                finally:
                    try:
                        if registry is not None:
                            await registry.close()
                    except Exception as error:
                        logger.warning(
                            "Method registry shutdown failed (%s).", type(error).__name__
                        )
                    finally:
                        if imported_store is not None:
                            imported_store.close()
                        if analysis_service is None and analysis_queue is not None:
                            analysis_queue.close()
                        rate_limiter.close()
                        if database_engine is not None:
                            database_engine.dispose()
            finally:
                try:
                    if dismeta is not None:
                        await dismeta.close()
                except Exception as error:
                    logger.warning("DisMeta shutdown failed (%s).", type(error).__name__)
                finally:
                    try:
                        if seg is not None:
                            await seg.close()
                    except Exception as error:
                        logger.warning("SEG shutdown failed (%s).", type(error).__name__)
                    finally:
                        try:
                            await fuzdrop.close()
                        except Exception:
                            logger.exception(
                                "FuzDrop shutdown failed; continuing local model cleanup."
                            )
                        finally:
                            await adapter.close()

    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Human-specific LRECA inference and official FuzDrop manual-result import. "
            "Automatic FuzDrop submission is unavailable. "
            "SEG provides independent low-complexity region annotation. "
            "DisMeta integration is blocked pending a verified contract. "
            "Capability-routed jobs support independent results "
            "and experimental weighted scores. Persistent history and export are Module 9."
        ),
        lifespan=lifespan,
    )
    application.state.lreca_adapter = lreca_adapter
    application.state.fuzdrop_adapter = fuzdrop_adapter
    application.state.seg_adapter = seg_adapter
    application.state.dismeta_adapter = dismeta_adapter
    application.state.settings = settings
    application.state.analysis_service = None
    application.state.analysis_queue = None
    application.state.database_engine = None
    application.state.rate_limiter = NoopRateLimiter()
    application.state.imported_result_store = None
    application.state.method_registry = MethodRegistry(
        {
            "lreca": lreca_adapter,
            "fuzdrop": fuzdrop_adapter,
            "seg": seg_adapter,
            "dismeta": dismeta_adapter,
        },
        manual_import_enabled=settings.fuzdrop_manual_import_enabled,
    )
    allowed_origins = [
        item.strip() for item in settings.cors_allowed_origins.split(",") if item.strip()
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Analysis-Session", "X-Request-ID"],
    )
    application.add_middleware(ProductionHTTPMiddleware)
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(health_ops_router, prefix="/api/v1", include_in_schema=False)
    application.include_router(health_ops_router, include_in_schema=False)
    application.include_router(config_router, prefix="/api/v1")
    application.include_router(system_router, prefix="/api/v1", include_in_schema=False)
    application.include_router(version_router, prefix="/api/v1", include_in_schema=False)
    application.include_router(lreca_router, prefix="/api/v1")
    application.include_router(fuzdrop_router, prefix="/api/v1")
    application.include_router(seg_router, prefix="/api/v1")
    application.include_router(dismeta_router, prefix="/api/v1")
    application.include_router(methods_router, prefix="/api/v1")
    application.include_router(analysis_router, prefix="/api/v1")
    return application


app = create_app()
