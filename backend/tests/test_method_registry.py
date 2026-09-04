"""Capability routing and readiness checks without HTTP or scientific execution."""

import asyncio
import time
from pathlib import Path

import pytest

import app.services.method_registry as registry_module
from app.schemas.lreca import LRECAHealth
from app.schemas.seg import SEGHealth
from app.services.method_registry import MethodRegistry


class LocalAdapter:
    def __init__(self, health):
        self.health = health
        self.health_calls = 0

    async def healthcheck(self):
        self.health_calls += 1
        return self.health


class ForbiddenRemoteAdapter:
    async def healthcheck(self):
        raise AssertionError("Manual and blocked adapters must not be invoked by the registry")

    async def analyze(self, sequence):
        raise AssertionError("The registry must not execute analysis")


def ready_seg():
    return SEGHealth(
        status="ready",
        available=True,
        reason=None,
        version="2.17.0",
        application_version="1.0.0",
        parameters={"window": 12, "locut": 2.2, "hicut": 2.5},
    )


def test_registry_separates_support_automatic_import_and_blocked_capabilities():
    async def exercise():
        lreca = LocalAdapter(LRECAHealth(status="ready", loaded=True, device="cpu", message="test"))
        seg = LocalAdapter(ready_seg())
        remote = ForbiddenRemoteAdapter()
        registry = MethodRegistry(
            {"lreca": lreca, "seg": seg, "fuzdrop": remote, "dismeta": remote}
        )
        methods = {entry.id: entry for entry in await registry.list_methods()}
        assert all(entry.method_supported for entry in methods.values())
        assert methods["lreca"].automatic_analysis_available is True
        assert methods["seg"].automatic_analysis_available is True
        assert (
            methods["lreca"].integration_mode
            == methods["seg"].integration_mode
            == "local_automatic"
        )
        assert methods["fuzdrop"].available is True
        assert methods["fuzdrop"].automatic_analysis_available is False
        assert methods["fuzdrop"].manual_import_available is True
        assert methods["fuzdrop"].integration_mode == "manual_import"
        assert methods["fuzdrop"].integration_status == "manual_import_only"
        assert methods["dismeta"].available is False
        assert methods["dismeta"].integration_mode == "integration_blocked"
        assert methods["dismeta"].integration_status == "blocked"
        assert methods["dismeta"].manual_import_available is False
        assert (
            methods["seg"].semantic_types
            == methods["dismeta"].semantic_types
            == ["region_annotation"]
        )
        assert methods["lreca"].semantic_types == [
            "model_prediction",
            "model_attribution",
            "derived_hotspot",
        ]
        assert "residue_propensity" in methods["fuzdrop"].semantic_types
        assert lreca.health_calls == seg.health_calls == 1
        await registry.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("status", ["ready", "running", "success"])
def test_loaded_lreca_remains_automatically_available_while_running(status):
    async def exercise():
        adapter = LocalAdapter(
            LRECAHealth(status=status, loaded=True, device="cpu", message="test")
        )
        registry = MethodRegistry({"lreca": adapter})
        assert (await registry.get("lreca")).automatic_analysis_available is True
        await registry.close()

    asyncio.run(exercise())


def test_not_loaded_lreca_is_not_advertised_as_ready():
    async def exercise():
        adapter = LocalAdapter(LRECAHealth(status="ready", loaded=False, message="test"))
        registry = MethodRegistry({"lreca": adapter})
        descriptor = await registry.get("lreca")
        assert descriptor.available is descriptor.automatic_analysis_available is False
        await registry.close()

    asyncio.run(exercise())


def test_get_checks_only_the_selected_method_and_adapter_lookup_has_no_side_effects():
    async def exercise():
        lreca, seg = ForbiddenRemoteAdapter(), LocalAdapter(ready_seg())
        registry = MethodRegistry({"lreca": lreca, "seg": seg})
        assert registry.adapter_for("lreca") is lreca
        assert registry.adapter_for("other") is None
        assert (await registry.get("seg")).available is True
        with pytest.raises(KeyError):
            await registry.get("unknown")
        await registry.close()

    asyncio.run(exercise())


def test_manual_import_disabled_keeps_fuzdrop_supported_but_unavailable():
    async def exercise():
        registry = MethodRegistry({}, manual_import_enabled=False)
        fuzdrop = await registry.get("fuzdrop")
        assert fuzdrop.method_supported is fuzdrop.manual_import_supported is True
        assert fuzdrop.available is fuzdrop.manual_import_available is False
        assert fuzdrop.automatic_analysis_available is False
        assert fuzdrop.integration_mode == "manual_import"
        assert fuzdrop.reason == "manual_import_disabled"
        await registry.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("kind", ["exception", "invalid_dto", "private_message"])
def test_readiness_failures_and_private_diagnostics_are_sanitized(kind, caplog, recwarn):
    secret = str(Path.cwd() / "private-registry-diagnostic" / "model.bin")

    class BadHealth(LocalAdapter):
        async def healthcheck(self):
            if kind == "exception":
                raise RuntimeError(secret)
            health = ready_seg()
            field = "message" if kind == "private_message" else "version"
            return health.model_copy(update={field: secret})

    async def exercise():
        registry = MethodRegistry({"seg": BadHealth(None)})
        descriptor = await registry.get("seg")
        assert descriptor.available is (kind == "private_message")
        assert "private-registry-diagnostic" not in descriptor.model_dump_json()
        await registry.close()

    asyncio.run(exercise())
    assert "private-registry-diagnostic" not in caplog.text
    assert not any("private-registry-diagnostic" in str(w.message) for w in recwarn)


def test_cancel_resistant_health_does_not_block_requests_or_spawn_duplicate_tasks(monkeypatch):
    monkeypatch.setattr(registry_module, "HEALTH_TIMEOUT_SECONDS", 0.02)

    async def exercise():
        released = asyncio.Event()
        health_calls = 0

        class ResistantHealth:
            async def healthcheck(self):
                nonlocal health_calls
                health_calls += 1
                while not released.is_set():
                    try:
                        await released.wait()
                    except asyncio.CancelledError:
                        continue
                return ready_seg()

        registry = MethodRegistry({"seg": ResistantHealth()})
        started = time.monotonic()
        assert (await registry.get("seg")).available is False
        assert (await registry.get("seg")).available is False
        await registry.close()
        assert time.monotonic() - started < 0.5
        assert health_calls == 1
        released.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not registry._health_tasks

    asyncio.run(exercise())


def test_readiness_checks_are_concurrent_and_failure_does_not_hide_other_methods():
    async def exercise():
        arrivals = 0
        both = asyncio.Event()

        class CoordinatedHealth:
            def __init__(self, reply):
                self.reply = reply

            async def healthcheck(self):
                nonlocal arrivals
                arrivals += 1
                if arrivals == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), 0.5)
                return self.reply

        registry = MethodRegistry(
            {
                "lreca": CoordinatedHealth(LRECAHealth(status="unavailable", message="test")),
                "seg": CoordinatedHealth(ready_seg()),
            }
        )
        methods = {entry.id: entry for entry in await registry.list_methods()}
        assert methods["lreca"].available is False
        assert methods["seg"].available is True
        assert methods["fuzdrop"].available is True
        await registry.close()

    asyncio.run(exercise())
