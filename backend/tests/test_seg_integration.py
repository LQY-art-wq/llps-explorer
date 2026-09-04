"""Real standard-binary regression tests; never download tools during pytest."""

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.adapters.seg import SEGAdapter
from app.core.config import Settings
from app.schemas.seg import SEGError

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "seg"
CASES = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def executable():
    root = ROOT
    configured = os.environ.get("SEG_TEST_EXECUTABLE_PATH") or os.environ.get("SEG_EXECUTABLE_PATH")
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute() and candidate.parent == Path("."):
            candidate = Path(shutil.which(str(candidate)) or candidate)
    else:
        candidate = (
            root
            / ".tools"
            / "seg"
            / "ncbi-blast-2.17.0+"
            / "bin"
            / ("segmasker.exe" if os.name == "nt" else "segmasker")
        )
        if not candidate.is_file():
            discovered = shutil.which("segmasker")
            if discovered:
                candidate = Path(discovered)
    if not candidate.is_file():
        pytest.skip(
            "Install pinned NCBI segmasker with scripts/setup_seg.py before integration tests"
        )
    return candidate.resolve()


@pytest.fixture(scope="module")
def actual_results(executable):
    async def exercise():
        adapter = SEGAdapter(Settings(_env_file=None, seg_executable_path=executable))
        try:
            await adapter.load()
            health = await adapter.healthcheck()
            results = {
                name: await adapter.analyze(case["sequence"]) for name, case in CASES.items()
            }
            return health, results
        finally:
            await adapter.close()

    return asyncio.run(exercise())


def test_real_seg_executable_discovery_version_and_hash(actual_results, executable):
    health, _ = actual_results
    assert health.available is True and health.status == "ready"
    assert health.version == "2.17.0"
    assert health.application_version == "1.0.0"
    assert health.executable_sha256 == hashlib.sha256(executable.read_bytes()).hexdigest()


@pytest.mark.parametrize("case_name", list(CASES))
def test_real_standard_seg_matches_fixed_region_regression(case_name, actual_results):
    case = CASES[case_name]
    result = actual_results[1][case_name]
    assert [
        {"start": region.start, "end": region.end, "length": region.length}
        for region in result.regions
    ] == case["expected_regions"]
    assert result.region_count == len(case["expected_regions"])
    assert result.longest_region == max((r["length"] for r in case["expected_regions"]), default=0)
    covered = set()
    for region in case["expected_regions"]:
        covered.update(range(region["start"], region["end"] + 1))
    assert result.coverage == len(covered) / len(case["sequence"])
    assert 0 <= result.coverage <= 1
    assert all(
        1 <= region.start <= region.end <= result.sequence_length for region in result.regions
    )
    assert result.annotation_type == "LCR" and result.semantic_type == "region_annotation"
    assert (
        not {"raw_score", "calibrated_score", "label", "probability"} & result.model_dump().keys()
    )


def test_direct_official_binary_output_matches_saved_fixture(executable):
    case = CASES["multiple_regions"]
    response = subprocess.run(
        [
            str(executable),
            "-in",
            "-",
            "-out",
            "-",
            "-infmt",
            "fasta",
            "-outfmt",
            "interval",
            "-window",
            "12",
            "-locut",
            "2.2",
            "-hicut",
            "2.5",
        ],
        input=f">query\n{case['sequence']}\n".encode("ascii"),
        capture_output=True,
        timeout=10,
        env=dict(os.environ, BLAST_USAGE_REPORT="false"),
    )
    assert response.returncode == 0
    assert response.stderr == b""
    reference = (FIXTURES / case["raw_output_file"]).read_bytes()
    # Windows emits CRLF; Unix may emit LF. Coordinate content must remain identical.
    assert response.stdout.splitlines() == reference.splitlines()
    if os.name == "nt":
        assert response.stdout == reference


def test_fasta_header_is_removed_and_predict_regions_uses_the_same_pipeline(executable):
    async def exercise():
        adapter = SEGAdapter(Settings(_env_file=None, seg_executable_path=executable))
        try:
            sequence = CASES["n_terminal"]["sequence"]
            result = await adapter.analyze(
                ">user header with spaces; not a command\n" + sequence.lower() + "\n"
            )
            regions = await adapter.predict_regions(sequence)
            assert regions == result.regions
            assert result.sequence_sha256 == hashlib.sha256(sequence.encode("ascii")).hexdigest()
        finally:
            await adapter.close()

    asyncio.run(exercise())


def test_real_no_lcr_has_valid_zero_statistics(actual_results):
    result = actual_results[1]["mixed_high_complexity"]
    assert result.regions == []
    assert result.coverage == 0
    assert result.region_count == result.longest_region == 0


def test_executable_disappearance_is_reported_unavailable_after_initial_load(executable, tmp_path):
    async def exercise():
        adapter = SEGAdapter(Settings(_env_file=None, seg_executable_path=executable))
        try:
            await adapter.load()
            adapter.process.configured_executable = tmp_path / "removed" / "segmasker"
            health = await adapter.healthcheck()
            assert health.available is False
            assert health.reason == "SEG_EXECUTABLE_NOT_FOUND"
            with pytest.raises(SEGError) as caught:
                await adapter.analyze("Q" * 40)
            assert caught.value.detail["code"] == "SEG_EXECUTABLE_NOT_FOUND"
        finally:
            await adapter.close()

    asyncio.run(exercise())
