"""The worker survives temporary infrastructure errors and releases its pool."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from hai_core.settings import Settings
from hai_ontology.meta import Manifest
from hai_worker.main import Worker


async def test_worker_retries_infrastructure_errors_and_disposes(
    manifest: Manifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = Worker(Settings(env="test", worker_poll_seconds=0.001), manifest)
    tick, dispose = Mock(), Mock()
    monkeypatch.setattr(worker, "schedule_monitoring_tick", tick)
    monkeypatch.setattr(worker.ctx.db, "dispose", dispose)
    attempts = 0

    async def run_once() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("database restarted")
        worker.stop()

    monkeypatch.setattr(worker, "run_once", run_once)
    await worker.run_forever()
    assert attempts == 2 and tick.call_count == 2
    dispose.assert_called_once()
