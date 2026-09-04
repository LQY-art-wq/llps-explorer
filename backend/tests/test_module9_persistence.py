"""Persistent lifecycle, ownership, recovery, and export acceptance for Module 9."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from test_lreca_api import BoundaryStub, boundary_result
from test_orchestrator import service_fixture
from test_seg_api import PROVENANCE

import app.api.analysis as analysis_api
import app.services.persistent_repositories as persistent_repositories
from app.api.analysis import router as analysis_router
from app.api.config import router as config_router
from app.api.fuzdrop import router as fuzdrop_router
from app.core.config import Settings
from app.persistence.database import (
    AnalysisJobRow,
    ImportedResultRow,
    JobImportRow,
    create_database_engine,
)
from app.persistence.migrations import upgrade_database
from app.schemas.lreca import LRECAResult
from app.schemas.orchestration import (
    AnalysisJob,
    AnalysisRequest,
    MethodExecution,
    SequenceMetadata,
)
from app.schemas.seg import SEGResult
from app.services.analysis_jobs import AnalysisJobService, AnalysisServiceError
from app.services.exports import (
    attachment_header,
    fasta_export,
    regions_csv,
    residues_csv,
    safe_stem,
    summary_csv,
)
from app.services.fuzdrop_import import import_fuzdrop_result
from app.services.imported_results import ImportedResultError
from app.services.persistent_repositories import (
    SQLAnalysisJobRepository,
    SQLImportedResultStore,
)

SEQUENCE = "ACDE"
OWNER_A_TOKEN = "A" * 43
OWNER_B_TOKEN = "B" * 43
OWNER_A = hashlib.sha256(OWNER_A_TOKEN.encode("ascii")).hexdigest()
OWNER_B = hashlib.sha256(OWNER_B_TOKEN.encode("ascii")).hexdigest()
OWNER_C = hashlib.sha256(b"third-owner").hexdigest()


@pytest.fixture
def engine(tmp_path):
    database = create_database_engine(f"sqlite:///{(tmp_path / 'module9.db').as_posix()}")
    upgrade_database(database)
    yield database
    database.dispose()


def lreca_result(sequence: str = SEQUENCE) -> LRECAResult:
    payload = boundary_result(sequence).model_dump(mode="json", warnings=False)
    region = {"start": 2, "end": 3, "score": 0.8, "is_primary": True}
    payload.update(
        {
            "attribution_status": "success",
            "attribution_target_class_index": 1,
            "attribution_target_label": "P",
            "residue_attribution": [
                {"position": index, "aa": aa, "score": index / 10}
                for index, aa in enumerate(sequence, start=1)
            ],
            "top_residues": [{"rank": 1, "position": 4, "aa": "E", "score": 0.4}],
            "kde": {
                "status": "success",
                "values": [0.1, 0.5, 0.7, 0.2],
                "values_semantics": "fixture density",
                "prominence": 0.1,
                "regions": [region],
            },
            "critical_regions": [region],
        }
    )
    return LRECAResult.model_validate(payload)


def seg_result(sequence: str = SEQUENCE) -> SEGResult:
    return SEGResult(
        sequence_length=len(sequence),
        sequence_sha256=hashlib.sha256(sequence.encode("ascii")).hexdigest(),
        regions=[{"start": 3, "end": 4}],
        runtime_ms=1.5,
        **PROVENANCE,
    )


def fuzdrop_result(sequence: str = SEQUENCE):
    return import_fuzdrop_result(
        {
            "sequence": sequence,
            "source_declaration": "official_fuzdrop_export",
            "coordinate_system": "one_based_inclusive",
            "pLLPS": 0.68,
            "scores_tsv": (
                "position\tresidue\tpDP\tSbind\n"
                "1\tA\t0.1\t0.2\n2\tC\t0.2\t0.3\n3\tD\t0.3\t0.4\n4\tE\t0.4\t0.5\n"
            ),
            "regions_tsv": "type\tstart\tend\nDroplet-promoting region\t2\t4\n",
        }
    )


def analysis_job(
    job_id: str,
    *,
    sequence: str = SEQUENCE,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
    running: bool = False,
) -> AnalysisJob:
    created = created_at or datetime.now(timezone.utc)
    expires = expires_at or created + timedelta(days=7)
    digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
    if running:
        methods = {
            "lreca": MethodExecution(
                method="lreca", status="running", integration_mode="local_automatic"
            )
        }
        status = "running"
        completed_at = None
    else:
        methods = {
            "lreca": MethodExecution(
                method="lreca",
                status="success",
                integration_mode="local_automatic",
                result=lreca_result(sequence),
            ),
            "fuzdrop": MethodExecution(
                method="fuzdrop",
                status="success",
                integration_mode="manual_import",
                result=fuzdrop_result(sequence),
            ),
            "seg": MethodExecution(
                method="seg",
                status="success",
                integration_mode="local_automatic",
                result=seg_result(sequence),
            ),
            "dismeta": MethodExecution(
                method="dismeta",
                status="unavailable",
                integration_mode="integration_blocked",
                reason="integration_blocked",
            ),
        }
        status = "partial_success"
        completed_at = created
    return AnalysisJob(
        job_id=job_id,
        created_at=created,
        updated_at=created,
        completed_at=completed_at,
        expires_at=expires,
        status=status,
        sequence=SequenceMetadata(name="蛋白 ../ unsafe", length=len(sequence), sha256=digest),
        normalized_sequence=sequence,
        selected_methods=list(methods),
        methods=methods,
    )


def test_repository_survives_reinitialization_with_all_native_results(tmp_path):
    path = tmp_path / "restart.db"
    first_engine = create_database_engine(f"sqlite:///{path.as_posix()}")
    upgrade_database(first_engine)
    first = SQLAnalysisJobRepository(first_engine)
    expected = analysis_job("analysis_restart")
    first.create_job(expected, owner_id=OWNER_A)
    first_engine.dispose()

    second_engine = create_database_engine(f"sqlite:///{path.as_posix()}")
    upgrade_database(second_engine)
    restored = SQLAnalysisJobRepository(second_engine).get_job(
        expected.job_id, owner_id=OWNER_A
    )
    second_engine.dispose()
    assert restored == expected
    assert restored.methods["lreca"].result.residue_attribution[3].position == 4
    assert restored.methods["seg"].result.regions[0].start == 3
    assert restored.methods["fuzdrop"].result.regions[0].end == 4
    assert restored.methods["dismeta"].status == "unavailable"
    assert restored.result_schema_version == "1.0"


def test_running_job_recovery_is_interrupted_not_completed(engine):
    repository = SQLAnalysisJobRepository(engine)
    job = analysis_job("analysis_running", running=True)
    repository.create_job(job, owner_id=OWNER_A)
    assert repository.recover_interrupted_jobs() == 1
    restored = repository.get_job(job.job_id, owner_id=OWNER_A)
    assert restored.status == "interrupted"
    assert restored.completed_at is not None
    assert restored.methods["lreca"].status == "failed"
    assert restored.methods["lreca"].error.code == "ANALYSIS_INTERRUPTED"
    assert restored.methods["lreca"].reason == "service_restart"


def test_deleting_running_job_cancels_cleanly_without_recreating_row(engine):
    async def scenario():
        started = asyncio.Event()

        class BlockingLRECA(BoundaryStub):
            async def analyze(self, sequence, *, include_attribution=True, include_kde=True):
                started.set()
                await asyncio.Event().wait()

        template, _, _, _ = await service_fixture(lreca=BlockingLRECA())
        repository = SQLAnalysisJobRepository(engine)
        service = AnalysisJobService(orchestrator=template.orchestrator, store=repository)
        job = await service.submit(
            AnalysisRequest(sequence=SEQUENCE, selected_methods=["lreca"]),
            owner_id=OWNER_A,
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        task = service._job_tasks[job.job_id]
        service.delete(job.job_id, owner_id=OWNER_A)
        await asyncio.wait_for(asyncio.shield(task), timeout=1)
        assert task.done() and not task.cancelled() and task.exception() is None
        with pytest.raises(AnalysisServiceError) as error:
            repository.get_job(job.job_id, owner_id=OWNER_A)
        assert error.value.code == "ANALYSIS_JOB_NOT_FOUND"
        await service.close()

    asyncio.run(scenario())


def test_update_persists_without_extending_fixed_retention(engine):
    repository = SQLAnalysisJobRepository(engine)
    original = analysis_job("analysis_update")
    repository.create_job(original, owner_id=OWNER_A)
    updated = original.model_copy(
        update={
            "updated_at": original.updated_at + timedelta(seconds=1),
            "warnings": ["persisted update"],
        },
        deep=True,
    )
    repository.update_job(updated)
    restored = repository.get_job(original.job_id, owner_id=OWNER_A)
    assert restored.warnings == ["persisted update"]
    assert restored.expires_at == original.expires_at


def test_global_capacity_cannot_be_bypassed_by_rotating_owners(engine):
    repository = SQLAnalysisJobRepository(engine, max_jobs=2)
    repository.create_job(analysis_job("analysis_capacity_a"), owner_id=OWNER_A)
    repository.create_job(analysis_job("analysis_capacity_b"), owner_id=OWNER_B)
    with pytest.raises(AnalysisServiceError) as job_error:
        repository.create_job(analysis_job("analysis_capacity_c"), owner_id=OWNER_C)
    assert job_error.value.code == "ANALYSIS_CAPACITY_EXCEEDED"

    imported_store = SQLImportedResultStore(engine, ttl_seconds=86400, max_entries=2)
    imported_store.put(fuzdrop_result(), OWNER_A)
    imported_store.put(fuzdrop_result(), OWNER_B)
    with pytest.raises(ImportedResultError) as import_error:
        imported_store.put(fuzdrop_result(), OWNER_C)
    assert import_error.value.code == "EXTERNAL_RESULT_STORE_FULL"


def test_concurrent_global_capacity_never_exceeds_configured_limits(engine):
    repository = SQLAnalysisJobRepository(engine, max_jobs=4)

    def create_job(index: int) -> str:
        try:
            repository.create_job(
                analysis_job(f"analysis_capacity_race_{index}"),
                owner_id=(OWNER_A, OWNER_B, OWNER_C)[index % 3],
            )
        except AnalysisServiceError as error:
            return error.code
        return "created"

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(create_job, range(12)))
    assert outcomes.count("created") == 4
    assert outcomes.count("ANALYSIS_CAPACITY_EXCEEDED") == 8

    imported_store = SQLImportedResultStore(engine, ttl_seconds=86400, max_entries=3)

    def create_import(index: int) -> str:
        try:
            imported_store.put(fuzdrop_result(), (OWNER_A, OWNER_B, OWNER_C)[index % 3])
        except ImportedResultError as error:
            return error.code
        return "created"

    with ThreadPoolExecutor(max_workers=8) as executor:
        import_outcomes = list(executor.map(create_import, range(9)))
    assert import_outcomes.count("created") == 3
    assert import_outcomes.count("EXTERNAL_RESULT_STORE_FULL") == 6
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(AnalysisJobRow)) == 4
        assert session.scalar(select(func.count()).select_from(ImportedResultRow)) == 3


def test_cleanup_history_order_pagination_filters_and_ownership(engine):
    repository = SQLAnalysisJobRepository(engine)
    now = datetime.now(timezone.utc)
    expired = analysis_job(
        "analysis_expired",
        created_at=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )
    older = analysis_job("analysis_older", created_at=now - timedelta(minutes=2))
    newer = analysis_job("analysis_newer", created_at=now - timedelta(minutes=1))
    repository.create_job(older, owner_id=OWNER_A)
    repository.create_job(newer, owner_id=OWNER_A)
    repository.create_job(analysis_job("analysis_other"), owner_id=OWNER_B)
    # Insert the already-expired row last so create-time capacity cleanup cannot
    # remove it before the explicit cleanup assertion below.
    repository.create_job(expired, owner_id=OWNER_A)
    assert repository.cleanup_expired_jobs() == 1
    page = repository.list_jobs(owner_id=OWNER_A, limit=1, offset=0, method="seg")
    assert page.total == 2
    assert [item.job_id for item in page.items] == ["analysis_newer"]
    assert repository.list_jobs(
        owner_id=OWNER_A, limit=5, status="partial_success"
    ).total == 2
    with pytest.raises(AnalysisServiceError):
        repository.get_job(expired.job_id, owner_id=OWNER_A)


def test_expired_get_physically_deletes_job_association_and_orphan_import(engine):
    imported_store = SQLImportedResultStore(engine, ttl_seconds=86400)
    imported = imported_store.put(fuzdrop_result(), OWNER_A)
    repository = SQLAnalysisJobRepository(engine)
    expired = analysis_job(
        "analysis_expired_get",
        created_at=datetime.now(timezone.utc) - timedelta(days=2),
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    repository.create_job(expired, owner_id=OWNER_A, import_result_ids=(imported.result_id,))
    with pytest.raises(AnalysisServiceError) as error:
        repository.get_job(expired.job_id, owner_id=OWNER_A)
    assert error.value.code == "ANALYSIS_JOB_NOT_FOUND"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(AnalysisJobRow)) == 0
        assert session.scalar(select(func.count()).select_from(JobImportRow)) == 0
        assert session.scalar(select(func.count()).select_from(ImportedResultRow)) == 0


def test_expired_import_get_commits_delete_and_cascades_association(engine):
    imported_store = SQLImportedResultStore(engine, ttl_seconds=86400)
    imported = imported_store.put(fuzdrop_result(), OWNER_A)
    repository = SQLAnalysisJobRepository(engine)
    job = analysis_job("analysis_live_with_expired_import")
    repository.create_job(job, owner_id=OWNER_A, import_result_ids=(imported.result_id,))
    with Session(engine) as session, session.begin():
        session.execute(
            update(ImportedResultRow)
            .where(ImportedResultRow.result_id == imported.result_id)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
    with pytest.raises(ImportedResultError) as error:
        imported_store.get(imported.result_id, owner_id=OWNER_A)
    assert error.value.code == "EXTERNAL_RESULT_NOT_FOUND"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ImportedResultRow)) == 0
        assert session.scalar(select(func.count()).select_from(JobImportRow)) == 0
        assert session.scalar(select(func.count()).select_from(AnalysisJobRow)) == 1


def test_cleanup_deletes_expired_active_jobs_but_keeps_live_jobs(engine):
    repository = SQLAnalysisJobRepository(engine)
    now = datetime.now(timezone.utc)
    expired_active = analysis_job(
        "analysis_expired_active",
        created_at=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
        running=True,
    )
    live = analysis_job("analysis_live", created_at=now)
    repository.create_job(live, owner_id=OWNER_A)
    repository.create_job(expired_active, owner_id=OWNER_A)
    assert repository.cleanup_expired_jobs(now=now) == 1
    with pytest.raises(AnalysisServiceError):
        repository.get_job(expired_active.job_id, owner_id=OWNER_A)
    assert repository.get_job(live.job_id, owner_id=OWNER_A).job_id == live.job_id


def test_sqlite_repository_concurrent_create_update_and_owner_lists(engine):
    repository = SQLAnalysisJobRepository(engine, max_jobs=64)
    owners = (OWNER_A, OWNER_B)

    def persist(index: int) -> tuple[str, str]:
        owner = owners[index % len(owners)]
        job = analysis_job(f"analysis_concurrent_{index:02d}")
        repository.create_job(job, owner_id=owner)
        repository.update_job(
            job.model_copy(update={"warnings": [f"updated-{index}"]}, deep=True)
        )
        # Exercise reads while other workers are committing without sharing a Session.
        repository.list_jobs(owner_id=owner, limit=64)
        return job.job_id, owner

    with ThreadPoolExecutor(max_workers=4) as executor:
        persisted = list(executor.map(persist, range(16)))

    for owner in owners:
        other_owner = OWNER_B if owner == OWNER_A else OWNER_A
        expected = {job_id for job_id, job_owner in persisted if job_owner == owner}
        page = repository.list_jobs(owner_id=owner, limit=64)
        actual = {item.job_id for item in page.items}
        assert page.total == len(expected) == 8
        assert actual == expected
        assert len(actual) == len(page.items)
        for job_id in expected:
            restored = repository.get_job(job_id, owner_id=owner)
            index = int(job_id.rsplit("_", 1)[1])
            assert restored.warnings == [f"updated-{index}"]
            with pytest.raises(AnalysisServiceError):
                repository.get_job(job_id, owner_id=other_owner)


def test_production_configuration_cannot_disable_job_ownership():
    with pytest.raises(ValueError, match="DEV_DISABLE_JOB_OWNERSHIP"):
        Settings(
            _env_file=None,
            environment="production",
            dev_disable_job_ownership=True,
            database_url="sqlite://",
        )


def test_import_persists_and_job_delete_respects_shared_references(engine):
    store = SQLImportedResultStore(engine, ttl_seconds=86400)
    imported = store.put(fuzdrop_result(), OWNER_A)
    repository = SQLAnalysisJobRepository(engine)
    first = analysis_job("analysis_import_one")
    second = analysis_job("analysis_import_two")
    repository.create_job(first, owner_id=OWNER_A, import_result_ids=(imported.result_id,))
    repository.create_job(second, owner_id=OWNER_A, import_result_ids=(imported.result_id,))
    assert repository.delete_job(first.job_id, owner_id=OWNER_A)
    assert store.get(imported.result_id, owner_id=OWNER_A).normalized_result.raw_score == 0.68
    assert repository.delete_job(second.job_id, owner_id=OWNER_A)
    with pytest.raises(ImportedResultError):
        store.get(imported.result_id, owner_id=OWNER_A)


@pytest.mark.parametrize("second_delete_path", ["explicit", "expired_get", "cleanup"])
def test_concurrent_job_deletion_serializes_orphan_cleanup(
    engine, monkeypatch, second_delete_path
):
    """All job deletion paths commit the last shared-import orphan exactly once."""
    imported_store = SQLImportedResultStore(engine, ttl_seconds=86400)
    imported = imported_store.put(fuzdrop_result(), OWNER_A)
    repository = SQLAnalysisJobRepository(engine)
    now = datetime.now(timezone.utc)
    first = analysis_job(f"analysis_delete_first_{second_delete_path}")
    second = analysis_job(
        f"analysis_delete_second_{second_delete_path}",
        created_at=now - timedelta(days=2) if second_delete_path != "explicit" else now,
        expires_at=now - timedelta(days=1) if second_delete_path != "explicit" else None,
    )
    repository.create_job(first, owner_id=OWNER_A, import_result_ids=(imported.result_id,))
    repository.create_job(second, owner_id=OWNER_A, import_result_ids=(imported.result_id,))

    original_delete = persistent_repositories._delete_job_and_orphan_imports
    counter_lock = threading.Lock()
    active_helpers = 0
    max_active_helpers = 0

    def observed_delete(session, row):
        nonlocal active_helpers, max_active_helpers
        with counter_lock:
            active_helpers += 1
            max_active_helpers = max(max_active_helpers, active_helpers)
        try:
            # Widen the historical race window so this test also proves that the
            # orphan check itself sits inside the shared mutation boundary.
            time.sleep(0.02)
            return original_delete(session, row)
        finally:
            with counter_lock:
                active_helpers -= 1

    monkeypatch.setattr(
        persistent_repositories, "_delete_job_and_orphan_imports", observed_delete
    )
    start = threading.Barrier(2)

    def delete_first():
        start.wait()
        return repository.delete_job(first.job_id, owner_id=OWNER_A)

    def delete_second():
        start.wait()
        if second_delete_path == "explicit":
            return repository.delete_job(second.job_id, owner_id=OWNER_A)
        if second_delete_path == "expired_get":
            with pytest.raises(AnalysisServiceError) as error:
                repository.get_job(second.job_id, owner_id=OWNER_A)
            assert error.value.code == "ANALYSIS_JOB_NOT_FOUND"
            return True
        return repository.cleanup_expired_jobs(now=now) == 1

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [executor.submit(delete_first), executor.submit(delete_second)]
        assert [future.result() for future in outcomes] == [True, True]

    assert max_active_helpers == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(AnalysisJobRow)) == 0
        assert session.scalar(select(func.count()).select_from(JobImportRow)) == 0
        assert session.scalar(select(func.count()).select_from(ImportedResultRow)) == 0


def test_exports_preserve_coordinates_missing_semantics_and_safe_names():
    job = analysis_job("analysis_export")
    rows = list(csv.DictReader(io.StringIO(residues_csv(job).decode("utf-8"))))
    assert [(row["Position"], row["AA"]) for row in rows] == [
        ("1", "A"),
        ("2", "C"),
        ("3", "D"),
        ("4", "E"),
    ]
    assert rows[0]["LRECA_Critical_Region"] == "false"
    assert rows[1]["LRECA_Critical_Region"] == "true"
    assert rows[2]["SEG_LCR"] == "true"
    assert rows[0]["DisMeta_IDR_Status"] == "Unavailable"
    regions = list(csv.DictReader(io.StringIO(regions_csv(job).decode("utf-8"))))
    assert {row["Method"] for row in regions} == {"LRECA", "FuzDrop", "SEG"}
    assert regions[0]["Region_Type"] == "Primary KDE hotspot"
    assert safe_stem("../ a/b\\c : * ?") == "abc"
    assert "/" not in safe_stem("../蛋白/名称")


def test_summary_csv_neutralizes_spreadsheet_formula_sequence_names():
    job = analysis_job("analysis_formula").model_copy(
        update={
            "sequence": analysis_job("analysis_formula").sequence.model_copy(
                update={"name": "=HYPERLINK(\"https://invalid.example\")"}
            )
        },
        deep=True,
    )
    row = next(csv.DictReader(io.StringIO(summary_csv(job).decode("utf-8"))))
    assert row["Sequence_Name"].startswith("'=")


@pytest.mark.parametrize(
    ("execution", "expected"),
    [
        (
            MethodExecution(
                method="dismeta", status="queued", integration_mode="integration_blocked"
            ),
            "Queued",
        ),
        (
            MethodExecution(
                method="dismeta", status="running", integration_mode="integration_blocked"
            ),
            "Running",
        ),
        (
            MethodExecution(
                method="dismeta",
                status="failed",
                integration_mode="integration_blocked",
                error={"code": "METHOD_EXECUTION_FAILED", "message": "Failed safely."},
            ),
            "Failed",
        ),
        (
            MethodExecution(
                method="dismeta",
                status="failed",
                integration_mode="integration_blocked",
                reason="service_restart",
                error={
                    "code": "ANALYSIS_INTERRUPTED",
                    "message": "Interrupted by restart.",
                },
            ),
            "Interrupted",
        ),
        (
            MethodExecution(
                method="dismeta", status="unavailable", integration_mode="integration_blocked"
            ),
            "Unavailable",
        ),
    ],
)
def test_residue_csv_reports_actual_dismeta_execution_state(execution, expected):
    job = analysis_job("analysis_dismeta_state")
    job = job.model_copy(
        update={"methods": {**job.methods, "dismeta": execution}}, deep=True
    )
    rows = list(csv.DictReader(io.StringIO(residues_csv(job).decode("utf-8"))))
    assert {row["DisMeta_IDR_Status"] for row in rows} == {expected}


def test_missing_region_fields_export_blank_not_false():
    job = analysis_job("analysis_missing")
    methods = {
        "fuzdrop": MethodExecution(
            method="fuzdrop",
            status="success",
            integration_mode="manual_import",
            result=import_fuzdrop_result(
                {
                    "sequence": SEQUENCE,
                    "source_declaration": "official_fuzdrop_export",
                    "coordinate_system": "one_based_inclusive",
                    "pLLPS": 0.4,
                }
            ),
        )
    }
    global_only = job.model_copy(
        update={"selected_methods": ["fuzdrop"], "methods": methods, "status": "success"}, deep=True
    )
    rows = list(csv.DictReader(io.StringIO(residues_csv(global_only).decode("utf-8"))))
    assert rows[0]["FuzDrop_Region"] == ""
    assert rows[0]["LRECA_Critical_Region"] == ""
    assert rows[0]["SEG_LCR"] == ""


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("normal_name", "normal_name"),
        (None, "protein"),
        ("蛋白", "蛋白"),
        ("with space", "with_space"),
        ("a/b\\c", "abc"),
        ("../", "protein"),
        ("a:*?<>|b", "ab"),
    ],
)
def test_export_filename_sanitization(name, expected):
    job = analysis_job("analysis_filename").model_copy(
        update={
            "sequence": analysis_job("analysis_filename").sequence.model_copy(
                update={"name": name}
            )
        },
        deep=True,
    )
    assert safe_stem(name) == expected
    disposition = attachment_header(job, "_result.json")
    assert "../" not in disposition and "\\" not in disposition


class RepositoryService:
    ownership_enforced = True

    def __init__(self, repository):
        self.repository = repository

    def get(self, job_id, *, owner_id):
        return self.repository.get_job(job_id, owner_id=owner_id)

    def list(self, **kwargs):
        return self.repository.list_jobs(**kwargs)

    def delete(self, job_id, *, owner_id):
        if not self.repository.delete_job(job_id, owner_id=owner_id):
            raise AnalysisServiceError("ANALYSIS_JOB_NOT_FOUND", "missing", 404)


def api_client(engine) -> TestClient:
    application = FastAPI()
    application.state.settings = Settings(
        _env_file=None, database_url="sqlite://", analysis_retention_days=7
    )
    application.state.analysis_service = RepositoryService(SQLAnalysisJobRepository(engine))
    application.include_router(config_router, prefix="/api/v1")
    application.include_router(analysis_router, prefix="/api/v1")
    return TestClient(application)


def test_api_ownership_history_exports_and_delete_do_not_leak(engine):
    repository = SQLAnalysisJobRepository(engine)
    job = analysis_job("analysis_private")
    repository.create_job(job, owner_id=OWNER_A)
    with api_client(engine) as client:
        a = {"X-Analysis-Session": OWNER_A_TOKEN}
        b = {"X-Analysis-Session": OWNER_B_TOKEN}
        assert client.get(f"/api/v1/analysis/{job.job_id}", headers=a).json()[
            "normalized_sequence"
        ] == SEQUENCE
        assert "X-Analysis-Session" not in client.get(
            f"/api/v1/analysis/{job.job_id}", headers=a
        ).headers
        history = client.get("/api/v1/analysis/history", headers=a)
        assert history.json()["total"] == 1
        assert all(secret not in history.text for secret in (SEQUENCE, OWNER_A_TOKEN, OWNER_A))
        assert client.get("/api/v1/analysis/history", headers=b).json()["total"] == 0
        assert client.get("/api/v1/config/public").json() == {"analysis_retention_days": 7}
        media_types = {
            "json": "application/json",
            "summary.csv": "text/csv",
            "residues.csv": "text/csv",
            "regions.csv": "text/csv",
            "fasta": "text/plain",
        }
        for suffix in ("json", "summary.csv", "residues.csv", "regions.csv", "fasta"):
            allowed = client.get(f"/api/v1/analysis/{job.job_id}/export/{suffix}", headers=a)
            denied = client.get(f"/api/v1/analysis/{job.job_id}/export/{suffix}", headers=b)
            assert allowed.status_code == 200
            assert allowed.headers["content-type"].startswith(media_types[suffix])
            assert "attachment" in allowed.headers["content-disposition"]
            assert denied.status_code == 404
            assert SEQUENCE not in denied.text
        exported = client.get(f"/api/v1/analysis/{job.job_id}/export/json", headers=a)
        assert json.loads(exported.content)["analysis"]["methods"]["lreca"]["result"][
            "raw_score"
        ] == 0.25
        assert client.delete(f"/api/v1/analysis/{job.job_id}", headers=b).status_code == 404
        assert client.delete(f"/api/v1/analysis/{job.job_id}", headers=a).status_code == 204
        assert client.get(f"/api/v1/analysis/{job.job_id}", headers=a).status_code == 404


def test_nonterminal_jobs_cannot_be_exported(engine):
    repository = SQLAnalysisJobRepository(engine)
    job = analysis_job("analysis_not_ready", running=True)
    repository.create_job(job, owner_id=OWNER_A)
    with api_client(engine) as client:
        headers = {"X-Analysis-Session": OWNER_A_TOKEN}
        for suffix in ("json", "summary.csv", "residues.csv", "regions.csv", "fasta"):
            response = client.get(
                f"/api/v1/analysis/{job.job_id}/export/{suffix}", headers=headers
            )
            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "ANALYSIS_NOT_READY_FOR_EXPORT"
            assert SEQUENCE not in response.text


def test_all_export_builders_run_outside_async_event_loop(engine, monkeypatch):
    repository = SQLAnalysisJobRepository(engine)
    job = analysis_job("analysis_threaded_export")
    repository.create_job(job, owner_id=OWNER_A)
    application = FastAPI()
    application.state.settings = Settings(_env_file=None, database_url="sqlite://")
    application.state.analysis_service = RepositoryService(repository)
    application.include_router(analysis_router, prefix="/api/v1")
    worker_threads = []
    suffixes = {
        "json_export": "json",
        "summary_csv": "summary.csv",
        "residues_csv": "residues.csv",
        "regions_csv": "regions.csv",
        "fasta_export": "fasta",
    }
    for name in suffixes:
        original = getattr(analysis_api, name)

        def wrapped(value, *, _original=original):
            worker_threads.append(threading.get_ident())
            return _original(value)

        monkeypatch.setattr(analysis_api, name, wrapped)

    async def scenario():
        event_loop_thread = threading.get_ident()
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-Analysis-Session": OWNER_A_TOKEN},
        ) as client:
            for suffix in suffixes.values():
                response = await client.get(
                    f"/api/v1/analysis/{job.job_id}/export/{suffix}"
                )
                assert response.status_code == 200
        return event_loop_thread

    event_loop_thread = asyncio.run(scenario())
    assert len(worker_threads) == len(suffixes)
    assert all(worker != event_loop_thread for worker in worker_threads)


def test_fuzdrop_import_is_persistent_and_session_owned(engine):
    store = SQLImportedResultStore(engine, ttl_seconds=86400)
    application = FastAPI()
    application.state.settings = Settings(_env_file=None, database_url="sqlite://")
    application.state.imported_result_store = store
    application.state.fuzdrop_adapter = None
    application.include_router(fuzdrop_router, prefix="/api/v1")
    payload = {
        "sequence": SEQUENCE,
        "source_declaration": "official_fuzdrop_export",
        "coordinate_system": "one_based_inclusive",
        "pLLPS": 0.68,
    }
    with TestClient(application) as client:
        response = client.post(
            "/api/v1/methods/fuzdrop/import",
            headers={"X-Analysis-Session": OWNER_A_TOKEN},
            json=payload,
        )
    assert response.status_code == 200
    assert "X-Analysis-Session" not in response.headers
    assert "httponly" in response.headers["set-cookie"].lower()
    result_id = response.json()["result_id"]
    reopened = SQLImportedResultStore(engine, ttl_seconds=86400)
    assert reopened.get(result_id, owner_id=OWNER_A).normalized_result.raw_score == 0.68
    with pytest.raises(ImportedResultError):
        reopened.get(result_id, owner_id=OWNER_B)


def test_fuzdrop_import_respects_configured_sequence_limit(engine):
    application = FastAPI()
    application.state.settings = Settings(
        _env_file=None,
        database_url="sqlite://",
        analysis_max_sequence_length=3,
    )
    application.state.imported_result_store = SQLImportedResultStore(engine, ttl_seconds=86400)
    application.state.fuzdrop_adapter = None
    application.include_router(fuzdrop_router, prefix="/api/v1")
    with TestClient(application) as client:
        response = client.post(
            "/api/v1/methods/fuzdrop/import",
            headers={"X-Analysis-Session": OWNER_A_TOKEN},
            json={
                "sequence": SEQUENCE,
                "source_declaration": "official_fuzdrop_export",
                "coordinate_system": "one_based_inclusive",
                "pLLPS": 0.68,
            },
        )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "ANALYSIS_SEQUENCE_TOO_LONG"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ImportedResultRow)) == 0


def test_fasta_wraps_at_sixty_and_5000_residue_csv_is_complete():
    sequence = "A" * 5000
    created = datetime.now(timezone.utc)
    digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
    job = AnalysisJob(
        job_id="analysis_long",
        created_at=created,
        updated_at=created,
        completed_at=created,
        expires_at=created + timedelta(days=7),
        status="success",
        sequence=SequenceMetadata(name=None, length=len(sequence), sha256=digest),
        normalized_sequence=sequence,
        selected_methods=["seg"],
        methods={
            "seg": MethodExecution(
                method="seg",
                status="success",
                integration_mode="local_automatic",
                result=seg_result(sequence),
            )
        },
    )
    fasta_lines = fasta_export(job).decode("utf-8").splitlines()
    assert all(len(line) == 60 for line in fasta_lines[1:-1])
    csv_rows = list(csv.reader(io.StringIO(residues_csv(job).decode("utf-8"))))
    assert len(csv_rows) == 5001
    assert csv_rows[-1][:2] == ["5000", "A"]
