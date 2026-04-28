"""Thin async HTTP client wrapping GitHub REST API v3."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

import httpx

if TYPE_CHECKING:
    from agentharness.config import Config

_BASE_URL = "https://api.github.com"
_ACCEPT_HEADER = "application/vnd.github+json"


class GitHubApiError(Exception):
    """Raised for 4xx/5xx responses from the GitHub API."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"GitHub API error {status_code}: {message}")


class GitHubClient:
    """Async GitHub REST API v3 client."""

    def __init__(self, token: str, owner: str, repo: str) -> None:
        self.owner = owner
        self.repo = repo
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": _ACCEPT_HEADER,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    @classmethod
    def from_config(cls, config: Config) -> GitHubClient:
        gh = config.github
        return cls(token=gh.token, owner=gh.owner, repo=gh.runs_repo)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _repo_url(self, path: str) -> str:
        return f"/repos/{self.owner}/{self.repo}{path}"

    async def _request(self, method: str, url: str, **kwargs: object) -> dict:
        response = await self._client.request(method, url, **kwargs)
        if response.status_code >= 400:
            try:
                body = response.json()
                detail = body.get("message", response.text)
                if "errors" in body:
                    detail = f"{detail}: {body['errors']}"

            except Exception:
                detail = response.text
            raise GitHubApiError(response.status_code, detail)
        if response.status_code == 204:
            return {}
        return response.json()

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    async def create_issue(
        self, title: str, body: str, labels: list[str]
    ) -> dict:
        return await self._request(
            "POST",
            self._repo_url("/issues"),
            json={"title": title, "body": body, "labels": labels},
        )

    async def get_issue(self, number: int) -> dict:
        return await self._request("GET", self._repo_url(f"/issues/{number}"))

    async def update_issue(
        self,
        number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
    ) -> dict:
        payload: dict = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        return await self._request(
            "PATCH", self._repo_url(f"/issues/{number}"), json=payload
        )

    async def add_labels(self, number: int, labels: list[str]) -> None:
        await self._request(
            "POST",
            self._repo_url(f"/issues/{number}/labels"),
            json={"labels": labels},
        )

    async def remove_label(self, number: int, label: str) -> None:
        encoded = quote(label, safe="")
        await self._request(
            "DELETE", self._repo_url(f"/issues/{number}/labels/{encoded}")
        )

    async def create_comment(self, number: int, body: str) -> dict:
        return await self._request(
            "POST",
            self._repo_url(f"/issues/{number}/comments"),
            json={"body": body},
        )

    async def list_comments(self, number: int) -> list[dict]:
        response = await self._client.get(
            self._repo_url(f"/issues/{number}/comments"),
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            raise GitHubApiError(response.status_code, detail)
        return response.json()

    async def update_comment(self, comment_id: int, body: str) -> None:
        await self._request(
            "PATCH",
            self._repo_url(f"/issues/comments/{comment_id}"),
            json={"body": body},
        )

    async def list_issues(
        self,
        labels: list[str] | None = None,
        state: str = "open",
        sort: str = "created",
        direction: str = "asc",
        per_page: int = 100,
    ) -> list[dict]:
        params: dict = {"state": state, "sort": sort, "direction": direction, "per_page": per_page}
        if labels:
            params["labels"] = ",".join(labels)
        all_results: list[dict] = []
        page = 1
        while True:
            params["page"] = page
            page_results: list[dict] = await self._request(  # type: ignore[assignment]
                "GET", self._repo_url("/issues"), params=params
            )
            all_results.extend(page_results)
            if len(page_results) < per_page:
                break
            page += 1
        if state != "all":
            all_results = [i for i in all_results if i.get("state") == state]
        return all_results

    async def search_issues(
        self, query: str, sort: str = "created", order: str = "asc"
    ) -> list[dict]:
        """Search issues via GitHub Search API. Returns the `items` list."""
        result: dict = await self._request(  # type: ignore[assignment]
            "GET",
            "/search/issues",
            params={"q": query, "sort": sort, "order": order},
        )
        return result.get("items", [])

    async def add_sub_issue(self, parent_number: int, child_number: int) -> None:
        """Link child_number as a sub-issue of parent_number."""
        await self._request(
            "POST",
            self._repo_url(f"/issues/{parent_number}/sub_issues"),
            json={"sub_issue_id": child_number},
        )

    # ------------------------------------------------------------------
    # Refs / branches
    # ------------------------------------------------------------------

    async def get_repo(self) -> dict:
        return await self._request("GET", self._repo_url(""))

    async def get_default_branch(self) -> str:
        repo = await self.get_repo()
        return repo["default_branch"]

    async def get_ref(self, ref: str) -> dict:
        return await self._request("GET", self._repo_url(f"/git/ref/{ref}"))

    async def create_ref(self, ref: str, sha: str) -> dict:
        return await self._request(
            "POST",
            self._repo_url("/git/refs"),
            json={"ref": ref, "sha": sha},
        )

    # ------------------------------------------------------------------
    # Contents
    # ------------------------------------------------------------------

    async def get_content(self, path: str, ref: str) -> dict:
        return await self._request(
            "GET",
            self._repo_url(f"/contents/{path}"),
            params={"ref": ref},
        )

    async def put_content(
        self,
        path: str,
        message: str,
        content: str,
        sha: str | None,
        branch: str,
    ) -> dict:
        payload: dict = {
            "message": message,
            "content": content,
            "branch": branch,
        }
        if sha is not None:
            payload["sha"] = sha
        return await self._request(
            "PUT",
            self._repo_url(f"/contents/{path}"),
            json=payload,
        )

    # ------------------------------------------------------------------
    # Labels (idempotent create)
    # ------------------------------------------------------------------

    async def ensure_label(self, name: str, color: str = "ededed") -> None:
        """Create label if it does not exist; no-op if it already does."""
        try:
            await self._request("GET", self._repo_url(f"/labels/{name}"))
        except GitHubApiError as exc:
            if exc.status_code != 404:
                raise
            await self._request(
                "POST", self._repo_url("/labels"), json={"name": name, "color": color}
            )

    async def ensure_labels(self, names: list[str], color: str = "ededed") -> None:
        """Create any labels in *names* that do not exist — one list call total."""
        page = 1
        existing: set[str] = set()
        while True:
            batch: list[dict] = await self._request(  # type: ignore[assignment]
                "GET",
                self._repo_url("/labels"),
                params={"per_page": 100, "page": page},
            )
            for label in batch:
                existing.add(label["name"])
            if len(batch) < 100:
                break
            page += 1

        for name in names:
            if name not in existing:
                try:
                    await self._request(
                        "POST",
                        self._repo_url("/labels"),
                        json={"name": name, "color": color},
                    )
                except GitHubApiError as exc:
                    if exc.status_code != 422:
                        raise

    # ------------------------------------------------------------------
    # Pull requests
    # ------------------------------------------------------------------

    async def create_pull_request(
        self, title: str, body: str, head: str, base: str
    ) -> dict:
        return await self._request(
            "POST",
            self._repo_url("/pulls"),
            json={"title": title, "body": body, "head": head, "base": base},
        )
