"""GITHUB: repositories of the organization's verified GitHub handle only. Never guessed from a slug."""

from __future__ import annotations

from typing import Any

from hai_ontology.terms import compile_term
from hai_pipeline.config import ConnectorConfig
from hai_pipeline.connectors.base import ConnectorContext, ConnectorResult, FetchedDocument
from hai_pipeline.extraction import parse_date
from hai_pipeline.http import Budget, BudgetExhausted, Fetcher


class GitHubConnector:
    code = "GITHUB"

    async def run(
        self, ctx: ConnectorContext, fetcher: Fetcher, config: ConnectorConfig, budget: Budget
    ) -> ConnectorResult:
        result = ConnectorResult(outcome="succeeded")
        if bool(config.opt("requires_verified_handle", True)) and not ctx.github_handle:
            result.notes.append("no verified GitHub handle for the organization; nothing fetched")
            return result
        handle = ctx.github_handle or ""
        api = str(config.opt("api_url", "https://api.github.com")).rstrip("/")
        headers = {"Accept": "application/vnd.github+json"}
        token = ctx.api_tokens.get("GITHUB")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"{api}/orgs/{handle}/repos?per_page=100&sort=updated"
        result.attempted_urls.append(url)
        fetched, data = await fetcher.get_json(url, budget=budget, headers=headers)
        if not fetched.ok or not isinstance(data, list):
            result.outcome = fetched.outcome if fetched.outcome != "succeeded" else "failed"
            result.error_code = fetched.error_code or "bad_json"
            return result
        patterns = [compile_term(str(t)) for t in config.opt("repo_terms", [])]
        chosen: list[dict[str, Any]] = []
        for repo in data:
            if not isinstance(repo, dict):
                continue
            probe = " ".join(
                [
                    str(repo.get("name", "")).replace("-", " "),
                    str(repo.get("description") or ""),
                    " ".join(repo.get("topics") or []),
                ]
            )
            if any(p.search(probe) for p in patterns):
                chosen.append(repo)
        for repo in chosen[: int(config.opt("max_repos", 3))]:
            readme_url = f"{api}/repos/{handle}/{repo.get('name')}/readme"
            try:
                readme = await fetcher.fetch(
                    readme_url, budget=budget, headers={**headers, "Accept": "application/vnd.github.raw+json"}
                )
            except BudgetExhausted as exc:
                result.notes.append(str(exc))
                break
            result.attempted_urls.append(readme_url)
            if not readme.ok:
                continue
            result.documents.append(
                FetchedDocument(
                    url=str(repo.get("html_url") or readme_url),
                    content=readme.content,
                    content_type="text/plain; charset=utf-8",
                    publisher_hint=f"GitHub: {handle}",
                    publisher_type_hint=config.publisher_type,
                    published_at=parse_date(str(repo.get("pushed_at") or "")),
                    title=f"{repo.get('full_name')}: {repo.get('description') or 'repository README'}",
                    rights=str((repo.get("license") or {}).get("spdx_id") or "") or None,
                )
            )
        result.notes.append(f"{len(data)} repositories, {len(chosen)} matched governance terms")
        return result
