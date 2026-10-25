"""UPLOAD: evidence portal documents. They enter the pipeline as claims by the organization."""

from __future__ import annotations

from hai_pipeline.config import ConnectorConfig
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument
from hai_pipeline.http import Budget, Fetcher


class UploadConnector:
    code = "UPLOAD"

    async def run(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget
    ) -> ConnectorResult:
        del fetcher, budget  # the upload connector reads blobs the orchestrator already loaded
        result = ConnectorResult(outcome="succeeded")
        if not ctx.pending_uploads:
            result.notes.append("no pending uploads")
            return result
        for up in ctx.pending_uploads:
            content = up.get("content")
            if not isinstance(content, bytes):
                result.notes.append(f"upload {up.get('id')} has no content")
                continue
            result.documents.append(
                FetchedDocument(
                    url=f"upload://{up.get('id')}/{up.get('filename')}",
                    content=content,
                    content_type=str(up.get("content_type") or "application/octet-stream"),
                    publisher_hint=ctx.organization_name,
                    publisher_type_hint=config.publisher_type,
                    title=str(up.get("filename") or "upload"),
                    claim_text=str(up.get("assertion_text") or ""),
                    upload_id=str(up.get("id")),
                    rights="Submitted by the organization through the evidence portal",
                )
            )
        result.notes.append(f"{len(result.documents)} uploads ingested as claims")
        return result
