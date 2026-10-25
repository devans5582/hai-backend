"""Near-duplicate clustering with 64-bit SimHash so syndicated copies count once (IC-09)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_TOKEN = re.compile(r"[a-z0-9]+")
SHINGLE_SIZE = 3
DEFAULT_MAX_DISTANCE = 12


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def simhash64(text: str, shingle_size: int = SHINGLE_SIZE) -> int:
    """64-bit SimHash over word shingles."""
    tokens = _tokens(text)
    if not tokens:
        return 0
    if len(tokens) < shingle_size:
        shingles = [" ".join(tokens)]
    else:
        shingles = [" ".join(tokens[i : i + shingle_size]) for i in range(len(tokens) - shingle_size + 1)]
    weights = [0] * 64
    for sh in shingles:
        h = int.from_bytes(hashlib.blake2b(sh.encode("utf-8"), digest_size=8).digest(), "big")
        for bit in range(64):
            weights[bit] += 1 if (h >> bit) & 1 else -1
    value = 0
    for bit in range(64):
        if weights[bit] > 0:
            value |= 1 << bit
    return value


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def exact_text_hash(text: str) -> str:
    return hashlib.sha256(" ".join(_tokens(text)).encode("utf-8")).hexdigest()


@dataclass
class Cluster:
    key: str
    method: str  # exact_hash | simhash
    simhash: int
    members: list[str]


class Clusterer:
    """Assigns documents to clusters: identical token streams first, then SimHash within ``max_distance``."""

    def __init__(self, max_distance: int = DEFAULT_MAX_DISTANCE) -> None:
        self.max_distance = max_distance
        self.clusters: list[Cluster] = []
        self._exact: dict[str, Cluster] = {}

    def assign(self, doc_id: str, text: str) -> Cluster:
        exact = exact_text_hash(text)
        if exact in self._exact:
            c = self._exact[exact]
            c.members.append(doc_id)
            return c
        sh = simhash64(text)
        for c in self.clusters:
            if hamming(c.simhash, sh) <= self.max_distance:
                c.members.append(doc_id)
                c.method = "simhash"
                self._exact[exact] = c
                return c
        c = Cluster(key=f"simhash:{sh:016x}", method="exact_hash", simhash=sh, members=[doc_id])
        self.clusters.append(c)
        self._exact[exact] = c
        return c
