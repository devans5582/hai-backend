"""Calibration harness: run the real job chain for a set of organizations and compare with expected ranges.

``python -m tests.calibration.harness`` creates a throwaway database, runs every
organization in ``ground_truth.yaml`` through acquisition, classification, the
snapshot, evaluation and the rules engine, and prints the stored score next to
the range Humaital expects. Nothing here feeds a score: the ranges are read only
to print the comparison.

HTTP responses are cached on disk (``var/calibration/http-cache``) so a rerun
after a lexicon or scoring change replays the same evidence. A cache miss goes
to the network with the pipeline's own User-Agent and per-host pacing.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from sqlalchemy import create_engine, text

from hai_core.assessments import AssessmentRequest, create_assessment
from hai_core.auth import Principal
from hai_core.db.engine import Database
from hai_core.db.migrate import migrate
from hai_core.db.store import Store
from hai_core.manifest import role_codes
from hai_core.seed import seed_all
from hai_core.settings import Settings
from hai_engine.llm.heuristic import HeuristicProvider
from hai_ontology.loader import load_manifest
from hai_ontology.meta import Manifest
from hai_worker.main import Worker

REPO = Path(__file__).resolve().parents[2]
GROUND_TRUTH = Path(__file__).with_name("ground_truth.yaml")
DEFAULT_ADMIN_URL = "postgresql://hai:hai@localhost:55441/postgres"
MAX_BODY = 12_500_000
OPERATOR = Principal("service", "calibration", "calibration", frozenset())


class CachingTransport(httpx.AsyncBaseTransport):
    """Replay a stored response when there is one; otherwise fetch, pace and store it."""

    def __init__(self, cache_dir: Path, *, offline: bool = False, min_interval: float = 0.5) -> None:
        self.cache_dir = cache_dir
        self.offline = offline
        self.min_interval = min_interval
        self.inner = httpx.AsyncHTTPTransport(retries=0)
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._errors: dict[str, str] = {}
        self.hits = 0
        self.misses = 0

    def _path(self, request: httpx.Request) -> Path:
        key = hashlib.sha256(f"{request.method} {request.url}".encode()).hexdigest()
        return self.cache_dir / key[:2] / key

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = self._path(request)
        meta_path = path.with_suffix(".json")
        failed = self._errors.get(str(path))
        if failed is not None:
            raise _error(failed, request)
        if meta_path.exists():
            self.hits += 1
            meta = json.loads(meta_path.read_text())
            body = path.with_suffix(".bin").read_bytes()
            return httpx.Response(meta["status"], headers=_wire(meta["headers"]), content=body, request=request)
        if self.offline:
            raise httpx.ConnectError("not in the calibration cache (offline)", request=request)
        self.misses += 1
        host = request.url.host
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self.min_interval - (time.monotonic() - self._last.get(host, 0.0))
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                response = await self.inner.handle_async_request(request)
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_raw():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_BODY:
                        break
                await response.aclose()
            except httpx.HTTPError as exc:
                # A connection failure may be transient: remember it for this run only.
                self._last[host] = time.monotonic()
                self._errors[str(path)] = type(exc).__name__
                raise
            self._last[host] = time.monotonic()
        raw = b"".join(chunks)
        # Header values are bytes on the wire and are not always ASCII; keep them as latin-1 text.
        pairs = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in response.headers.raw]
        headers = [(k, v) for k, v in pairs if k.lower() != "content-length"]
        decoded = httpx.Response(response.status_code, headers=_wire(headers), content=raw, request=request)
        try:
            body = decoded.content
        except httpx.DecodingError:
            body = b""
        kept = [(k, v) for k, v in headers if k.lower() not in ("content-encoding", "transfer-encoding")]
        self._store(path, {"status": response.status_code, "headers": kept, "url": str(request.url)}, body)
        return httpx.Response(response.status_code, headers=_wire(kept), content=body, request=request)

    def _store(self, path: Path, meta: dict[str, Any], body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".bin.tmp")
        tmp.write_bytes(body)
        os.replace(tmp, path.with_suffix(".bin"))
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta))
        os.replace(tmp, path.with_suffix(".json"))


def _wire(headers: list[Any]) -> list[tuple[bytes, bytes]]:
    return [(str(k).encode("latin-1", "replace"), str(v).encode("latin-1", "replace")) for k, v in headers]


def _error(name: str, request: httpx.Request) -> httpx.HTTPError:
    kind = getattr(httpx, name, httpx.ConnectError)
    if isinstance(kind, type) and issubclass(kind, httpx.RequestError):
        return kind(f"cached {name}", request=request)
    return httpx.ConnectError(f"cached {name}", request=request)


@dataclass(frozen=True)
class Target:
    key: str
    name: str
    website: str
    industry: str
    stage: str
    size: str
    low: float
    high: float
    holdout: bool = False


def load_targets(path: Path = GROUND_TRUTH) -> list[Target]:
    data = yaml.safe_load(path.read_text())
    return [Target(**row) for row in data["organizations"]]


def _sqlalchemy(url: str) -> str:
    return "postgresql+psycopg://" + url.split("://", 1)[1]


class Bench:
    """A throwaway database, a worker on the caching transport, and result extraction."""

    def __init__(self, admin_url: str, cache_dir: Path, *, offline: bool, now: datetime, work_dir: Path) -> None:
        self.manifest: Manifest = load_manifest(REPO / "ontology")
        self.name = f"hai_calib_{secrets.token_hex(4)}"
        self.admin = create_engine(_sqlalchemy(admin_url), isolation_level="AUTOCOMMIT")
        with self.admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{self.name}"'))
        base, _, _ = admin_url.rpartition("/")
        self.settings = Settings(
            env="test",
            database_url=f"{base}/{self.name}",
            enforce_db_roles=False,
            blob_store_url=f"file://{work_dir / 'blobs' / self.name}",
            connectors_config=str(REPO / "config" / "connectors.yaml"),
            migrations_dir=str(REPO / "db" / "migrations"),
            llm_provider="heuristic",
            llm_model="ladder-1",
        )
        self.db = Database(self.settings.database_url, allowed_roles=role_codes(self.manifest))
        migrate(self.db, REPO / "db" / "migrations")
        with self.db.engine.begin() as conn:
            user = conn.execute(text("SELECT current_user")).scalar_one()
            conn.execute(text(f'GRANT {", ".join(sorted(role_codes(self.manifest)))} TO "{user}"'))
        with self.db.transaction("calibration", "hai_admin") as conn:
            seed_all(conn, self.manifest, REPO / "config" / "connectors.yaml", actor="calibration")
        self.transport = CachingTransport(cache_dir, offline=offline)
        self.worker = Worker(
            self.settings, self.manifest, transport=self.transport, provider=HeuristicProvider(), now=now
        )

    def close(self) -> None:
        self.worker.ctx.db.dispose()
        self.db.dispose()
        with self.admin.connect() as conn:
            conn.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :n"), {"n": self.name}
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{self.name}"'))
        self.admin.dispose()

    async def run(self, target: Target) -> dict[str, Any]:
        started = time.monotonic()
        with self.db.transaction(OPERATOR.actor, "hai_api") as conn:
            assessment, _ = create_assessment(
                conn,
                Store(conn, actor=OPERATOR.actor, manifest=self.manifest),
                request=AssessmentRequest(
                    organization_name=target.name,
                    website=target.website,
                    stage=target.stage,
                    size=target.size,
                    industry=target.industry,
                ),
                principal=OPERATOR,
                settings=self.settings,
                manifest=self.manifest,
            )
        await self.worker.drain()
        out = self._collect(str(assessment.id))
        out.update(
            key=target.key,
            name=target.name,
            website=target.website,
            low=target.low,
            high=target.high,
            holdout=target.holdout,
            seconds=round(time.monotonic() - started, 1),
        )
        return out

    def _collect(self, aid: str) -> dict[str, Any]:
        with self.db.engine.connect() as conn:
            a = conn.execute(
                text("SELECT lifecycle_state::text, failure_reason FROM hai.assessments WHERE id = :a"), {"a": aid}
            ).one()
            r = conn.execute(
                text(
                    "SELECT hai_score, confidence_pct, effectiveness, outcome_status::text, trace, gate_reasons "
                    "FROM hai.assessment_results WHERE assessment_id = :a ORDER BY created_at DESC LIMIT 1"
                ),
                {"a": aid},
            ).first()
            decisions = conn.execute(
                text(
                    "SELECT criterion_code::text, level, coverage_state::text, confidence FROM hai.criterion_decisions "
                    "WHERE assessment_id = :a ORDER BY criterion_code"
                ),
                {"a": aid},
            ).all()
            pillars = (
                conn.execute(text("SELECT * FROM hai.pillar_scores WHERE assessment_id = :a"), {"a": aid})
                .mappings()
                .all()
            )
            runs = conn.execute(
                text(
                    "SELECT c.code, r.outcome::text, r.error_code, r.items_returned, r.notes FROM hai.connector_runs r "
                    "JOIN hai.connectors c ON c.id = r.connector_id WHERE r.assessment_id = :a ORDER BY r.created_at"
                ),
                {"a": aid},
            ).all()
            docs = conn.execute(
                text(
                    "SELECT c.code, d.canonical_url, d.title, d.published_at, "
                    "(SELECT count(*) FROM hai.evidence_spans s WHERE s.source_document_id = d.id) "
                    "FROM hai.source_documents d JOIN hai.connector_runs r ON r.id = d.connector_run_id "
                    "JOIN hai.connectors c ON c.id = r.connector_id WHERE r.assessment_id = :a ORDER BY d.created_at"
                ),
                {"a": aid},
            ).all()
            links = conn.execute(
                text(
                    "SELECT l.criterion_code::text, l.polarity::text, l.admissibility::text, l.maturity_rung::text, "
                    "l.evidence_class::text, d.canonical_url, s.quote, s.section_heading, l.admissibility_reason "
                    "FROM hai.evidence_links l JOIN hai.evidence_spans s ON s.id = l.span_id "
                    "JOIN hai.source_documents d ON d.id = s.source_document_id "
                    "JOIN hai.connector_runs r ON r.id = d.connector_run_id WHERE r.assessment_id = :a"
                ),
                {"a": aid},
            ).all()
        return {
            "assessment_id": aid,
            "lifecycle": a[0],
            "failure_reason": a[1],
            "score": float(r[0]) if r and r[0] is not None else None,
            "confidence": float(r[1]) if r and r[1] is not None else None,
            "effectiveness": float(r[2]) if r and r[2] is not None else None,
            "outcome": r[3] if r else None,
            "gate_reasons": list(r[5] or []) if r else [],
            "decisions": [
                {"code": d[0], "level": d[1], "coverage": d[2], "confidence": float(d[3])} for d in decisions
            ],
            "pillars": [
                {
                    k: (float(v) if hasattr(v, "is_integer") or type(v).__name__ == "Decimal" else str(v))
                    for k, v in p.items()
                }
                for p in pillars
            ],
            "runs": [{"code": x[0], "outcome": x[1], "error": x[2], "items": x[3], "notes": x[4]} for x in runs],
            "documents": [
                {"connector": x[0], "url": x[1], "title": x[2], "published": str(x[3]) if x[3] else None, "spans": x[4]}
                for x in docs
            ],
            "links": [
                {
                    "code": x[0],
                    "polarity": x[1],
                    "admissibility": x[2],
                    "rung": x[3],
                    "class": x[4],
                    "url": x[5],
                    "quote": x[6],
                    "heading": x[7],
                    "reason": x[8],
                }
                for x in links
            ],
        }


def verdict(row: dict[str, Any]) -> str:
    score = row.get("score")
    if score is None:
        return "N/A"
    if score < row["low"]:
        return f"low {score - row['low']:+.1f}"
    if score > row["high"]:
        return f"high {score - row['high']:+.1f}"
    return "in range"


def summary_line(row: dict[str, Any]) -> str:
    observed = [d for d in row["decisions"] if d["coverage"] not in ("missing", "unavailable", "not_applicable")]
    levels = "".join(str(d["level"] or "-") for d in row["decisions"])
    web = next((r for r in row["runs"] if r["code"] == "WEBSITE"), None)
    score = "N/A" if row["score"] is None else f"{row['score']:5.1f}"
    return (
        f"{row['name']:<14} {score:>6}  [{row['low']:>2.0f}-{row['high']:>2.0f}]  {verdict(row):<12} "
        f"obs {len(observed):>2}/20  conf {row['confidence'] if row['confidence'] is not None else '-':>5}  "
        f"docs {len(row['documents']):>3}  web {web['outcome'] if web else '-':<9} levels {levels}  {row['seconds']}s"
    )


async def main_async(args: argparse.Namespace) -> int:
    targets = load_targets(Path(args.ground_truth))
    if args.only:
        wanted = {k.strip().lower() for k in args.only.split(",")}
        targets = [t for t in targets if t.key in wanted]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.fromisoformat(args.now).replace(tzinfo=UTC)
    bench = Bench(args.admin_url, Path(args.cache), offline=args.offline, now=now, work_dir=out_dir.parent)
    rows: list[dict[str, Any]] = []
    try:
        for target in targets:
            try:
                row = await bench.run(target)
            except Exception as exc:
                print(f"{target.name}: crashed: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            rows.append(row)
            (out_dir / f"{target.key}.json").write_text(json.dumps(row, indent=1, default=str))
            print(summary_line(row), flush=True)
    finally:
        bench.close()
    scored = [r for r in rows if r["score"] is not None]
    inside = [r for r in scored if r["low"] <= r["score"] <= r["high"]]
    print(
        f"\n{len(inside)}/{len(rows)} in range, {len(rows) - len(scored)} without a score; "
        f"cache hits {bench.transport.hits}, network fetches {bench.transport.misses}"
    )
    (out_dir / "summary.json").write_text(
        json.dumps(
            [
                {k: r[k] for k in ("key", "name", "score", "low", "high", "confidence", "outcome", "holdout")}
                | {"verdict": verdict(r)}
                for r in rows
            ],
            indent=1,
        )
    )
    return 0 if len(inside) == len(rows) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin-url", default=os.environ.get("HAI_TEST_DATABASE_URL", DEFAULT_ADMIN_URL))
    parser.add_argument("--ground-truth", default=str(GROUND_TRUTH))
    parser.add_argument("--cache", default=str(REPO / "var" / "calibration" / "http-cache"))
    parser.add_argument("--out", default=str(REPO / "var" / "calibration" / "results"))
    parser.add_argument("--only", default="", help="comma-separated organization keys")
    parser.add_argument("--offline", action="store_true", help="never touch the network; a cache miss fails the fetch")
    parser.add_argument("--now", default=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"))
    raise SystemExit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
