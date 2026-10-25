"""Application state and request dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import Connection

from hai_api.auth import Principal
from hai_core.blobstore import BlobStore
from hai_core.db.engine import Database
from hai_core.db.store import Store
from hai_core.errors import NotFoundError
from hai_core.generated.models import Assessment
from hai_core.manifest import role_codes
from hai_core.queue import JobQueue
from hai_core.settings import Settings
from hai_engine.certification import CertificationService
from hai_engine.decision import DecisionService
from hai_ontology.meta import Manifest


@dataclass
class AppState:
    settings: Settings
    manifest: Manifest
    db: Database
    blobs: BlobStore
    queue: JobQueue
    decisions: DecisionService
    certification: CertificationService

    @classmethod
    def build(cls, settings: Settings, manifest: Manifest) -> AppState:
        db = Database(
            settings.database_url, enforce_roles=settings.enforce_db_roles, allowed_roles=role_codes(manifest)
        )
        return cls(
            settings=settings,
            manifest=manifest,
            db=db,
            blobs=BlobStore(settings.blob_store_url),
            queue=JobQueue(),
            decisions=DecisionService(manifest),
            certification=CertificationService(manifest.methodology, settings.cert_signing_key.get_secret_value()),
        )

    @contextmanager
    def tx(self, principal: Principal, role: str | None = None) -> Iterator[tuple[Connection, Store]]:
        """A transaction as the principal, under the role that matches its kind."""
        chosen = role or ("hai_reviewer" if principal.is_reviewer else "hai_api")
        with self.db.transaction(principal.actor, chosen) as conn:
            yield conn, Store(conn, actor=principal.actor, manifest=self.manifest)

    @contextmanager
    def read(self, principal: Principal) -> Iterator[tuple[Connection, Store]]:
        with self.db.connect() as conn:
            yield conn, Store(conn, actor=principal.actor, manifest=self.manifest, audit=False)


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.hai
    return state


State = Annotated[AppState, Depends(get_state)]


def load_assessment(store: Store, assessment_id: UUID) -> Assessment:
    found = store.get(Assessment, assessment_id)
    if found is None:
        raise NotFoundError(f"assessment {assessment_id} not found")
    return found
