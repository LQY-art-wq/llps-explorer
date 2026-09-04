"""Import lifecycle tests use synthetic format inputs, never scientific predictions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.services.imported_results as storage
from app.api.fuzdrop import router
from app.core.config import Settings
from app.schemas.fuzdrop import FuzDropResult
from app.schemas.imported_results import FuzDropImportResponse, ImportedMethodResult
from app.services.fuzdrop_import import import_fuzdrop_result
from app.services.imported_results import (
    ImportedResultError,
    ImportedResultStore,
    InMemoryImportedResultStore,
)

SYNTHETIC_FORMAT_INPUT = {
    "sequence": ">synthetic_format_fixture\nacde",
    "source_declaration": "official_fuzdrop_export",
    "coordinate_system": "one_based_inclusive",
    "pLLPS": 0.65,
    "scores_tsv": (
        "position\tresidue\tpDP\tSbind\n"
        "1\tA\t0.3\t0.2\n2\tC\t0.5\t1.5\n3\tD\t0.9\t0.4\n4\tE\tundefined\t\n"
    ),
    "regions_tsv": "type\tstart\tend\nDroplet-promoting region\t2\t4\n",
}


@pytest.fixture
def native():
    return import_fuzdrop_result(SYNTHETIC_FORMAT_INPUT)


def check_error(error, code, status):
    assert error.value.code == code
    assert error.value.http_status == status
    assert error.value.detail == {"code": code, "message": error.value.message}
    assert SYNTHETIC_FORMAT_INPUT["sequence"] not in str(error.value)
    assert "Traceback" not in str(error.value)


def test_replaceable_store_requires_an_implementation():
    with pytest.raises(TypeError):
        ImportedResultStore()


def test_default_lifetime_metadata_and_repeated_reads_preserve_native_result(native, monkeypatch):
    now = native.imported_at + timedelta(seconds=2)
    monkeypatch.setattr(storage, "_utc_now", lambda: now)
    store = InMemoryImportedResultStore()
    imported = store.put(native)
    assert imported.expires_at == now + timedelta(seconds=3600)
    assert imported.imported_at == native.imported_at
    assert imported.sequence_sha256 == native.sequence_sha256
    assert imported.sequence_length == native.sequence_length
    assert imported.source == native.source
    assert imported.validation_status == "valid"
    assert imported.coordinate_provenance.coordinate_system == native.coordinate_system
    assert (
        imported.coordinate_provenance.coordinate_verification
        == "user_declared_not_independently_verified"
    )
    for _ in range(3):
        found = store.get(
            imported.result_id,
            sequence_sha256=native.sequence_sha256,
            sequence_length=native.sequence_length,
        )
        assert found == imported and found is not imported
        assert found.normalized_result.model_dump() == native.model_dump()
    assert store.get(imported.result_id, sequence_sha256=native.sequence_sha256) == imported
    assert store.get(imported.result_id, sequence_length=4) == imported


def test_put_input_and_each_returned_nested_copy_are_isolated(native):
    store = InMemoryImportedResultStore()
    imported = store.put(native)
    native.residue_propensity[0].__dict__["score"] = 0.99
    native.warnings.append("changed input")
    native.raw_tsv_sha256.clear()
    imported.normalized_result.warnings.append("changed put return")
    imported.normalized_result.regions[0].__dict__["start"] = 0

    found = store.get(imported.result_id)
    assert found.normalized_result.residue_propensity[0].score == 0.3
    assert found.normalized_result.regions[0].start == 2
    assert set(found.normalized_result.raw_tsv_sha256) == {"scores_tsv", "regions_tsv"}
    assert "changed input" not in found.normalized_result.warnings
    assert "changed put return" not in found.normalized_result.warnings
    found.normalized_result.residue_propensity.clear()
    found.normalized_result.regions.clear()
    assert len(store.get(imported.result_id).normalized_result.residue_propensity) == 4
    assert len(store.get(imported.result_id).normalized_result.regions) == 1


def test_expiration_is_exact_monotonic_and_reads_do_not_renew_it(native, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(storage, "monotonic", lambda: clock[0])
    store = InMemoryImportedResultStore(ttl_seconds=10)
    imported = store.put(native)
    clock[0] = 109.999
    # A wall-clock adjustment cannot extend the retained sequence's actual TTL.
    monkeypatch.setattr(storage, "_utc_now", lambda: datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert store.get(imported.result_id).expires_at == imported.expires_at
    clock[0] = 110
    with pytest.raises(ImportedResultError) as error:
        store.get(imported.result_id)
    check_error(error, "EXTERNAL_RESULT_NOT_FOUND", 404)
    with pytest.raises(ImportedResultError) as absent:
        store.get("nonexistent")
    assert error.value.detail == absent.value.detail


def test_expired_entries_release_capacity_without_evicting_live_imports(native, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(storage, "monotonic", lambda: clock[0])
    store = InMemoryImportedResultStore(ttl_seconds=2, max_entries=1)
    original = store.put(native)
    with pytest.raises(ImportedResultError) as error:
        store.put(native)
    check_error(error, "EXTERNAL_RESULT_STORE_FULL", 503)
    assert store.get(original.result_id) == original
    clock[0] = 12
    replacement = store.put(native)
    assert replacement.result_id != original.result_id
    with pytest.raises(ImportedResultError) as error:
        store.get(original.result_id)
    check_error(error, "EXTERNAL_RESULT_NOT_FOUND", 404)
    assert store.get(replacement.result_id) == replacement


@pytest.mark.parametrize(
    "identity",
    [
        {"sequence_sha256": "0" * 64},
        {"sequence_sha256": "invalid"},
        {"sequence_sha256": b"0" * 64},
        {"sequence_length": 3},
        {"sequence_length": True},
        {"sequence_length": 4.0},
        {"sequence_sha256": "0" * 64, "sequence_length": 4},
    ],
)
def test_sequence_binding_rejects_mismatch_without_consuming_reference(native, identity):
    store = InMemoryImportedResultStore()
    imported = store.put(native)
    with pytest.raises(ImportedResultError) as error:
        store.get(imported.result_id, **identity)
    check_error(error, "EXTERNAL_RESULT_SEQUENCE_MISMATCH", 422)
    assert store.get(imported.result_id).result_id == imported.result_id


@pytest.mark.parametrize("result_id", ["", "missing", "../private/result.json", None, [], 123])
def test_missing_ids_have_one_safe_not_found_error(result_id):
    with pytest.raises(ImportedResultError) as error:
        InMemoryImportedResultStore().get(result_id)
    check_error(error, "EXTERNAL_RESULT_NOT_FOUND", 404)
    assert "private" not in str(error.value)


def test_close_is_idempotent_clears_data_and_cannot_be_reopened(native):
    store = InMemoryImportedResultStore()
    imported = store.put(native)
    store.close()
    store.close()
    with pytest.raises(ImportedResultError) as error:
        store.get(imported.result_id)
    check_error(error, "EXTERNAL_RESULT_NOT_FOUND", 404)
    with pytest.raises(ImportedResultError) as error:
        store.put(native)
    check_error(error, "EXTERNAL_RESULT_STORE_FULL", 503)


def test_periodic_purge_releases_idle_expired_payloads_and_preserves_live_data(native, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(storage, "monotonic", lambda: clock[0])
    store = InMemoryImportedResultStore(ttl_seconds=10)
    expired = store.put(native)
    clock[0] = 105
    live = store.put(native)
    assert store.cleanup_interval_seconds == 10
    clock[0] = 110
    store.purge_expired()
    # Inspect retained references: a 404 alone would not prove payload removal.
    assert set(store._entries) == {live.result_id}
    assert expired.result_id not in store._entries
    assert store.get(live.result_id) == live
    assert InMemoryImportedResultStore().cleanup_interval_seconds == 60


@pytest.mark.parametrize(
    "updates",
    [
        {"sequence_sha256": "0" * 64},
        {"sequence_length": 5},
        {"sequence": "ACDF"},
        {"raw_score": 1.1, "calibrated_score": 1.1},
        {"raw_score": float("nan"), "calibrated_score": float("nan")},
        {"label": "N"},
        {"source": "official_remote_service"},
        {"origin_verification": "official_service_response"},
        {"coordinate_verification": "verified_official_contract"},
        {"coordinate_system": "zero_based"},
        {"imported_at": None},
        {"raw_tsv_sha256": {}},
        {"service_version": "invented"},
        {"unexpected": "PRIVATE_PAYLOAD"},
    ],
)
def test_tampered_native_models_are_revalidated_before_storage(native, updates):
    tampered = native.model_copy(deep=True, update=updates)
    with pytest.raises(ImportedResultError) as error:
        InMemoryImportedResultStore().put(tampered)
    check_error(error, "EXTERNAL_RESULT_INVALID", 422)
    assert "PRIVATE_PAYLOAD" not in str(error.value)


@pytest.mark.parametrize(
    "target", ["residue_score", "residue_position", "region_bounds", "region_type"]
)
def test_nested_model_tampering_cannot_bypass_native_validation(native, target):
    if target == "residue_score":
        native.residue_propensity[0].__dict__["score"] = -0.1
    elif target == "residue_position":
        native.residue_propensity[0].__dict__["position"] = 2
    elif target == "region_bounds":
        native.regions[0].__dict__["end"] = 5
    else:
        native.regions[0].__dict__["type"] = "aggregation_hotspot"
    with pytest.raises(ImportedResultError) as error:
        InMemoryImportedResultStore().put(native)
    check_error(error, "EXTERNAL_RESULT_INVALID", 422)


def test_empty_native_result_cannot_be_promoted_to_a_valid_import(native):
    tampered = native.model_copy(
        update={
            "raw_score": None,
            "calibrated_score": None,
            "label": None,
            "label_semantics": None,
            "threshold": None,
            "threshold_operator": None,
            "residue_propensity": None,
            "regions": None,
            "raw_tsv_sha256": {},
        }
    )
    with pytest.raises(ImportedResultError) as error:
        InMemoryImportedResultStore().put(tampered)
    check_error(error, "EXTERNAL_RESULT_INVALID", 422)


def test_global_only_and_explicit_empty_regions_remain_valid_without_inventing_fields():
    common = {
        "sequence": "ACDE",
        "source_declaration": "official_fuzdrop_export",
        "coordinate_system": "one_based_inclusive",
    }
    store = InMemoryImportedResultStore()
    global_only = store.put(import_fuzdrop_result({**common, "pLLPS": 0.2}))
    assert global_only.normalized_result.raw_score == 0.2
    assert global_only.normalized_result.residue_propensity is None
    assert global_only.normalized_result.regions is None
    empty_regions = store.put(
        import_fuzdrop_result({**common, "regions_tsv": "type\tstart\tend\n"})
    )
    assert empty_regions.normalized_result.raw_score is None
    assert empty_regions.normalized_result.regions == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("sequence_sha256", "0" * 64),
        ("sequence_length", 5),
        ("source", "official_remote_service"),
        ("validation_status", "independently_verified"),
        ("result_id", "../private/result.json"),
        (
            "coordinate_provenance",
            {
                "coordinate_system": "one_based_inclusive",
                "coordinate_verification": "verified_official_contract",
            },
        ),
    ],
)
def test_envelope_identity_and_provenance_cannot_be_replaced(native, field, value):
    imported = InMemoryImportedResultStore().put(native)
    with pytest.raises(ValidationError):
        ImportedMethodResult.model_validate(imported.model_copy(update={field: value}))


def test_envelope_requires_matching_import_time_and_positive_utc_lifetime(native):
    imported = InMemoryImportedResultStore().put(native)
    for updates in (
        {"imported_at": imported.imported_at + timedelta(seconds=1)},
        {"expires_at": imported.imported_at},
        {"expires_at": imported.expires_at.replace(tzinfo=None)},
    ):
        with pytest.raises(ValidationError):
            ImportedMethodResult.model_validate(imported.model_copy(update=updates))
    imported.normalized_result.__dict__["sequence_sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        ImportedMethodResult.model_validate(imported)


def test_concurrent_puts_respect_capacity_and_keep_every_accepted_reference(native):
    count, capacity = 12, 4
    barrier = Barrier(count)
    store = InMemoryImportedResultStore(max_entries=capacity)

    def put_one(_):
        barrier.wait(timeout=5)
        try:
            return store.put(native)
        except ImportedResultError as error:
            return error

    with ThreadPoolExecutor(max_workers=count) as workers:
        outcomes = list(workers.map(put_one, range(count)))
    accepted = [item for item in outcomes if isinstance(item, ImportedMethodResult)]
    refused = [item for item in outcomes if isinstance(item, ImportedResultError)]
    assert len(accepted) == capacity and len(refused) == count - capacity
    assert len({item.result_id for item in accepted}) == capacity
    assert all(error.code == "EXTERNAL_RESULT_STORE_FULL" for error in refused)
    with ThreadPoolExecutor(max_workers=count) as workers:
        fetched = list(workers.map(store.get, [item.result_id for item in accepted] * 3))
    assert len(fetched) == capacity * 3
    assert all(item.normalized_result.sequence == native.sequence for item in fetched)


@pytest.mark.parametrize("ttl", [0, -1, float("nan"), float("inf"), True, "3600", None, 1e-10])
def test_invalid_ttl_configuration_is_rejected(ttl):
    with pytest.raises(ValueError):
        InMemoryImportedResultStore(ttl_seconds=ttl)


@pytest.mark.parametrize("capacity", [0, -1, True, 1.0, "128", None])
def test_invalid_capacity_configuration_is_rejected(capacity):
    with pytest.raises(ValueError):
        InMemoryImportedResultStore(max_entries=capacity)


def import_application(store):
    app = FastAPI()
    app.state.settings = Settings(_env_file=None)
    app.state.imported_result_store = store
    app.include_router(router, prefix="/api/v1")
    return app


def test_import_endpoint_preserves_native_response_and_adds_reusable_reference():
    store = InMemoryImportedResultStore()
    with TestClient(import_application(store)) as client:
        response = client.post("/api/v1/methods/fuzdrop/import", json=SYNTHETIC_FORMAT_INPUT)
    assert response.status_code == 200, response.text
    payload = response.json()
    typed = FuzDropImportResponse.model_validate(payload)
    imported = store.get(
        typed.result_id,
        sequence_sha256=typed.sequence_sha256,
        sequence_length=typed.sequence_length,
    )
    old_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"result_id", "expires_at", "validation_status"}
    }
    assert FuzDropResult.model_validate(old_payload) == imported.normalized_result
    assert typed.raw_score == 0.65 and typed.origin_verification.startswith("user_declared")
    assert typed.validation_status == "valid"
    assert typed.expires_at == imported.expires_at
    assert store.get(typed.result_id) == imported


def test_import_endpoint_reports_capacity_without_evicting_previous_result():
    store = InMemoryImportedResultStore(max_entries=1)
    with TestClient(import_application(store)) as client:
        first = client.post("/api/v1/methods/fuzdrop/import", json=SYNTHETIC_FORMAT_INPUT)
        rejected = client.post("/api/v1/methods/fuzdrop/import", json=SYNTHETIC_FORMAT_INPUT)
    assert first.status_code == 200
    assert rejected.status_code == 503
    assert rejected.json()["detail"]["code"] == "EXTERNAL_RESULT_STORE_FULL"
    assert store.get(first.json()["result_id"]).normalized_result.raw_score == 0.65


def test_unexpected_storage_errors_do_not_log_or_return_retained_sequence(caplog):
    class BrokenStore:
        def put(self, result):
            raise RuntimeError("SECRET_STORED_SEQUENCE_" + result.sequence)

    with TestClient(import_application(BrokenStore())) as client:
        response = client.post("/api/v1/methods/fuzdrop/import", json=SYNTHETIC_FORMAT_INPUT)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "EXTERNAL_RESULT_STORE_FULL"
    assert "SECRET_STORED_SEQUENCE" not in response.text + caplog.text
