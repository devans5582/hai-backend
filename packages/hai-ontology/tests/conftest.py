from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hai_ontology.loader import find_repo_root, load_manifest
from hai_ontology.meta import Manifest

REPO = find_repo_root(Path(__file__))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO


@pytest.fixture(scope="session")
def manifest() -> Manifest:
    return load_manifest(REPO / "ontology")


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    """A writable copy of the shipped manifest for breaking things."""
    dst = tmp_path / "ontology"
    shutil.copytree(REPO / "ontology", dst)
    return dst
