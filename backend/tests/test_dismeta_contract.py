"""MODE F boundary and synthetic normalized-contract tests, not DisMeta predictions."""

import asyncio
import hashlib

import httpx
import pytest
from pydantic import ValidationError

from app.adapters.dismeta import DisMetaAdapter
from app.core.config import Settings
from app.schemas.analysis import AnalysisStatus
from app.schemas.dismeta import (
    DisMetaHealth,
    DisMetaRegion,
    DisMetaResult,
    DisMetaUnavailableResult,
)
from app.services.sequence_validation import SequenceValidationError


@pytest.fixture(autouse=True)
def deny_external_transports(monkeypatch):
    attempts = []

    def deny(*args, **kwargs):
        attempts.append("request")
        raise AssertionError("DisMeta UNKNOWN mode must not contact an external service")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny)
    yield
    assert attempts == []


def contract(regions, length=20, **updates):
    """Numbers below are synthetic contract cases, never official result fixtures."""
    values = {
        "sequence_length": length,
        "sequence_sha256": "0" * 64,
        "regions": [{"start": a, "end": b} for a, b in regions],
        "runtime_ms": 0.0,
    }
    values.update(updates)
    return DisMetaResult(**values)


def test_unavailable_lifecycle_validates_input_without_producing_idr_data():
    async def exercise():
        adapter = DisMetaAdapter(Settings(_env_file=None))
        await adapter.load()
        assert adapter.status == AnalysisStatus.UNAVAILABLE
        health = await adapter.healthcheck()
        assert health.available is False and health.integration_mode == "unknown"
        assert health.audit_mode == "F" and health.decision == "INTEGRATION_BLOCKED"
        assert health.manual_import_supported is False
        result = await adapter.analyze("\n>private user label\n ac d e\n")
        assert result.sequence_length == 4
        assert result.sequence_sha256 == hashlib.sha256(b"ACDE").hexdigest()
        assert result.error.code == "DISMETA_UNAVAILABLE"
        assert (
            result.regions
            is result.coverage
            is result.region_count
            is result.longest_region
            is None
        )
        assert await adapter.predict_regions("ACDE") is None
        dumped = result.model_dump_json()
        assert "private user label" not in dumped and "ACDE" not in dumped
        for field in ("raw_score", "probability", "label", "residue_disorder_score", "threshold"):
            assert field not in DisMetaUnavailableResult.model_fields
        await adapter.close()
        assert adapter.status == AnalysisStatus.UNAVAILABLE

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "sequence,code",
    [
        ("", "EMPTY_SEQUENCE"),
        (" \n", "EMPTY_SEQUENCE"),
        ("ACDX", "INVALID_AMINO_ACID"),
        ("ACD;exit", "INVALID_AMINO_ACID"),
        (">one\nACD\n>two\nEFG", "MULTIPLE_FASTA_RECORDS"),
    ],
)
def test_unavailable_adapter_still_reuses_unified_sequence_validation(sequence, code):
    adapter = DisMetaAdapter(Settings(_env_file=None))
    with pytest.raises(SequenceValidationError) as captured:
        asyncio.run(adapter.analyze(sequence))
    assert captured.value.detail["code"] == code


@pytest.mark.parametrize(
    "regions,length,covered,count,longest",
    [
        ([], 20, 0, 0, 0),
        ([(1, 20)], 20, 20, 1, 20),
        ([(1, 1)], 20, 1, 1, 1),
        ([(2, 8), (6, 12)], 20, 11, 2, 7),
        ([(2, 8), (2, 8)], 20, 7, 2, 7),
        ([(8, 10), (1, 2), (2, 4)], 20, 7, 3, 3),
        ([(2, 12), (3, 5)], 20, 11, 2, 11),
        ([(1, 5), (6, 10)], 20, 10, 2, 5),
    ],
)
def test_contract_union_statistics_preserve_input_regions(regions, length, covered, count, longest):
    result = contract(regions, length)
    assert result.coverage == covered / length
    assert result.region_count == count
    assert result.longest_region == longest
    assert [(row.start, row.end) for row in result.regions] == regions
    assert all(row.length == row.end - row.start + 1 for row in result.regions)
    assert DisMetaResult.model_validate(result.model_dump()) == result


@pytest.mark.parametrize("region", [(0, 2), (-1, 3), (4, 2), (1, 21), (1.5, 3), (True, 3)])
def test_contract_rejects_invalid_or_out_of_sequence_coordinates(region):
    with pytest.raises(ValidationError):
        contract([region])


@pytest.mark.parametrize("length", [0, -1, 1.5, True])
def test_contract_rejects_invalid_sequence_length(length):
    with pytest.raises(ValidationError):
        contract([], length)


@pytest.mark.parametrize("length", [3, 0, True, 2.0])
def test_serialized_region_length_is_validated(length):
    with pytest.raises(ValidationError):
        DisMetaRegion.model_validate({"start": 1, "end": 2, "length": length})


@pytest.mark.parametrize(
    "field,value",
    [
        ("coverage", 0.9),
        ("region_count", 2),
        ("longest_region", 8),
        ("raw_score", 0.5),
        ("label", "P"),
        ("residue_disorder_score", []),
        ("threshold", 0.5),
        ("runtime_ms", float("nan")),
    ],
)
def test_contract_rejects_forged_statistics_and_unsupported_scientific_fields(field, value):
    with pytest.raises(ValidationError):
        contract([(1, 5)], **{field: value})


@pytest.mark.parametrize(
    "updates",
    [
        {"regions": []},
        {"coverage": 0},
        {"longest_region": 0},
        {"region_count": 0},
        {"status": "success"},
        {"available": True},
        {"version": "2014"},
        {"integration_mode": "manual_import"},
        {"manual_import_supported": True},
        {"sequence_length": 10},
        {"sequence_sha256": "0" * 64},
    ],
)
def test_blocked_contract_cannot_masquerade_as_success_or_missing_metadata(updates):
    with pytest.raises(ValidationError):
        DisMetaUnavailableResult(**updates)


def test_health_cannot_claim_readiness():
    with pytest.raises(ValidationError):
        DisMetaHealth(available=True)
