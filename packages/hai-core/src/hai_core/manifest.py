"""The running manifest, and the guard that refuses to start on generated-code drift."""

from __future__ import annotations

from functools import lru_cache

from hai_core.errors import ConfigurationError
from hai_core.generated import MANIFEST_HASH
from hai_ontology.loader import load_manifest
from hai_ontology.meta import Manifest


@lru_cache(maxsize=1)
def get_manifest(ontology_dir: str | None = None) -> Manifest:
    return load_manifest(ontology_dir)


def verify_generated_code(manifest: Manifest) -> None:
    """Raise unless the generated code was produced from exactly this manifest."""
    if manifest.hash != MANIFEST_HASH:
        raise ConfigurationError(
            "generated code does not match the manifest: run hai-ontology codegen",
            details={"manifest_hash": manifest.hash, "generated_hash": MANIFEST_HASH},
        )


def role_codes(manifest: Manifest) -> frozenset[str]:
    return frozenset(r.code for r in manifest.ontology.roles)
