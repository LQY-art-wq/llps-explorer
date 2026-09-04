"""Process safety and lifecycle tests; fake children are explicitly Python test helpers."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

from app.adapters.seg import SEGAdapter
from app.core.config import Settings
from app.schemas.seg import SEGError, SEGParameters
from app.services.seg_process import (
    SEGExecutable,
    SEGProcess,
    parse_seg_version,
    resolve_seg_executable,
)
from app.services.sequence_validation import SequenceValidationError


def test_package_version_is_separate_from_the_internal_application_version():
    fixture = Path(__file__).parent / "fixtures" / "seg" / "version.txt"
    assert parse_seg_version(fixture.read_bytes()) == ("2.17.0", "1.0.0")


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"segmasker: 1.0.0\n",
        b"other-program: 1.0.0\n Package: blast 2.17.0, build test\n",
        b"segmasker: 1.0.0\n Package: blast 2.16.0, build test\n",
        b"segmasker: 9.9.9\n Package: blast 2.17.0, build test\n",
        b"\xff\xfe",
    ],
)
def test_invalid_or_unpinned_version_output_is_unavailable(raw):
    with pytest.raises(SEGError) as caught:
        parse_seg_version(raw)
    assert caught.value.detail["code"] == "SEG_INVALID_OUTPUT"
    assert caught.value.status_code == 503


def test_executable_discovery_uses_configured_path_and_path_lookup(tmp_path, monkeypatch):
    executable = tmp_path / "folder with spaces" / "segmasker"
    executable.parent.mkdir()
    executable.write_text("test fixture; never executed", encoding="utf-8")
    executable.chmod(0o700)
    assert resolve_seg_executable(executable) == executable.resolve()
    looked_up = []

    def find(name):
        looked_up.append(name)
        return str(executable)

    monkeypatch.setattr("app.services.seg_process.shutil.which", find)
    assert resolve_seg_executable(Path("segmasker")) == executable.resolve()
    assert looked_up == ["segmasker"]


def test_missing_executable_has_safe_unavailable_error(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.seg_process.shutil.which", lambda _: None)
    for configured in (Path("segmasker"), tmp_path / "missing" / "segmasker"):
        with pytest.raises(SEGError) as caught:
            resolve_seg_executable(configured)
        assert caught.value.detail["code"] == "SEG_EXECUTABLE_NOT_FOUND"
        assert caught.value.status_code == 503
        assert str(tmp_path) not in str(caught.value.detail)


def test_annotation_uses_fixed_fasta_header_stdin_and_separate_arguments(tmp_path, monkeypatch):
    executable = tmp_path / "seg fixture with spaces"
    executable.write_bytes(b"not an executable; unit test only")
    stat = executable.stat()
    runner = SEGProcess(executable, 10)
    runner.metadata = SEGExecutable(
        executable, "2.17.0", "1.0.0", "a" * 64, (stat.st_size, stat.st_mtime_ns)
    )
    calls = []

    async def record(arguments, *, stdin=None):
        calls.append((arguments, stdin))
        return b">query\n"

    monkeypatch.setattr(runner, "_run", record)
    sequence = "ACDEFGHIKLMNPQRSTVWY"
    raw, metadata = asyncio.run(runner.annotate(sequence, SEGParameters()))
    arguments, stdin = calls[0]
    assert arguments == [
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
    ]
    assert stdin == f">query\n{sequence}\n".encode("ascii")
    assert sequence not in " ".join(arguments)
    assert raw == b">query\n" and metadata is runner.metadata


@pytest.fixture
def observed_children(monkeypatch):
    original = asyncio.create_subprocess_exec
    children = []
    options_seen = []

    async def observe(*args, **kwargs):
        options_seen.append(kwargs)
        child = await original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", observe)
    yield children, options_seen
    assert all(child.returncode is not None for child in children)


def test_real_child_stdin_and_privacy_opt_out_without_shell(observed_children, monkeypatch):
    monkeypatch.setenv("BLAST_USAGE_REPORT", "true")

    async def exercise():
        runner = SEGProcess(Path(sys.executable), 5)
        output = await runner._run(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
            stdin=b"explicit Python process fixture",
        )
        await runner.close()
        return output

    assert asyncio.run(exercise()) == b"explicit Python process fixture"
    _, options = observed_children
    assert all("shell" not in item for item in options)
    assert all(item["env"]["BLAST_USAGE_REPORT"] == "false" for item in options)
    assert os.environ["BLAST_USAGE_REPORT"] == "true"


def test_nonzero_exit_does_not_publish_or_log_stderr(observed_children, caplog):
    async def exercise():
        runner = SEGProcess(Path(sys.executable), 5)
        try:
            await runner._run(
                [sys.executable, "-c", "import sys; sys.stderr.write('PRIVATE_QUERY'); sys.exit(7)"]
            )
        finally:
            await runner.close()

    with pytest.raises(SEGError) as caught:
        asyncio.run(exercise())
    assert caught.value.detail["code"] == "SEG_EXECUTION_FAILED"
    assert "PRIVATE_QUERY" not in str(caught.value.detail)
    assert "PRIVATE_QUERY" not in caplog.text


def test_timeout_kills_and_reaps_the_actual_child(observed_children):
    async def exercise():
        runner = SEGProcess(Path(sys.executable), 0.1)
        try:
            await runner._run([sys.executable, "-c", "import time; time.sleep(30)"])
        finally:
            assert not runner._active
            await runner.close()

    with pytest.raises(SEGError) as caught:
        asyncio.run(exercise())
    assert caught.value.detail["code"] == "SEG_TIMEOUT"
    assert caught.value.status_code == 504


async def wait_until_active(runner, count):
    async def ready():
        while len(runner._active) < count:
            await asyncio.sleep(0.005)

    await asyncio.wait_for(ready(), timeout=5)


def test_request_cancellation_kills_and_reaps_the_actual_child(observed_children):
    async def exercise():
        runner = SEGProcess(Path(sys.executable), 10)
        task = asyncio.create_task(
            runner._run([sys.executable, "-c", "import time; time.sleep(30)"])
        )
        await wait_until_active(runner, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not runner._active
        await runner.close()

    asyncio.run(exercise())


def test_close_reaps_all_of_its_active_children(observed_children):
    async def exercise():
        runner = SEGProcess(Path(sys.executable), 10)
        tasks = [
            asyncio.create_task(runner._run([sys.executable, "-c", "import time; time.sleep(30)"]))
            for _ in range(2)
        ]
        await wait_until_active(runner, 2)
        await runner.close()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, SEGError) for result in results)
        assert not runner._active
        with pytest.raises(SEGError):
            await runner._run([sys.executable, "--version"])

    asyncio.run(exercise())


@pytest.mark.parametrize("sequence", ["", "  ", "ACDX", "ACD;E", ">a\nACD\n>b\nEFG"])
def test_shared_validation_rejects_invalid_sequence_before_any_process(sequence, monkeypatch):
    adapter = SEGAdapter(Settings(_env_file=None))
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("An invalid sequence must not reach the process")

    monkeypatch.setattr(adapter.process, "annotate", forbidden)
    with pytest.raises(SequenceValidationError):
        asyncio.run(adapter.analyze(sequence))
    assert not calls
