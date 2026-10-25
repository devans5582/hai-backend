"""Content-addressed blob store.

Bytes are stored under their SHA-256 at ``<root>/<aa>/<bb>/<sha256>``. The
default is ``file://`` under ``var/blobs``; any fsspec URL (``s3://``, ``gcs://``)
works the same way, which keeps the store cloud agnostic. Reads verify the hash
so a tampered blob is detected.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fsspec

from hai_core.errors import IntegrityViolationError, NotFoundError


@dataclass(frozen=True)
class BlobRef:
    sha256: str
    uri: str
    size: int


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BlobStore:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        if base_url.startswith("file://"):
            root = Path(base_url[len("file://") :]).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            self.fs: Any = fsspec.filesystem("file")
            self.root = str(root)
            self.scheme = "file"
        else:
            self.fs, self.root = fsspec.core.url_to_fs(base_url)
            self.scheme = base_url.split("://", 1)[0]

    def _path(self, sha: str) -> str:
        return f"{self.root.rstrip('/')}/{sha[:2]}/{sha[2:4]}/{sha}"

    def uri_for(self, sha: str) -> str:
        if self.scheme == "file":
            return f"file://{self._path(sha)}"
        return f"{self.scheme}://{self._path(sha)}"

    def _sha_from(self, uri_or_sha: str) -> str:
        sha = uri_or_sha.rsplit("/", 1)[-1]
        if len(sha) != 64:
            raise NotFoundError(f"not a blob reference: {uri_or_sha}")
        return sha

    def put(self, data: bytes) -> BlobRef:
        sha = sha256_hex(data)
        path = self._path(sha)
        if not self.fs.exists(path):
            self.fs.makedirs(path.rsplit("/", 1)[0], exist_ok=True)
            with self.fs.open(path, "wb") as fh:
                fh.write(data)
        return BlobRef(sha, self.uri_for(sha), len(data))

    def put_text(self, text: str) -> BlobRef:
        return self.put(text.encode("utf-8"))

    def exists(self, uri_or_sha: str) -> bool:
        return bool(self.fs.exists(self._path(self._sha_from(uri_or_sha))))

    def get(self, uri_or_sha: str) -> bytes:
        sha = self._sha_from(uri_or_sha)
        path = self._path(sha)
        if not self.fs.exists(path):
            raise NotFoundError(f"blob {sha} not found")
        with self.fs.open(path, "rb") as fh:
            data: bytes = fh.read()
        if sha256_hex(data) != sha:
            raise IntegrityViolationError(f"blob {sha} does not match its hash: tampered or corrupt")
        return data

    def get_text(self, uri_or_sha: str) -> str:
        return self.get(uri_or_sha).decode("utf-8")
