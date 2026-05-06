"""Tests for GitHubClient retry and timeout behaviour."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agentharness.github_client import GitHubApiError, GitHubClient

_TOKEN = "ghp_test"
_OWNER = "owner"
_REPO = "repo"


def _make_client() -> GitHubClient:
    return GitHubClient(token=_TOKEN, owner=_OWNER, repo=_REPO)


def _resp(status: int, json_data: object = None, headers: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_data if json_data is not None else {}
    r.text = ""
    r.headers = MagicMock()
    r.headers.get = lambda key, default=None: (headers or {}).get(key, default)
    return r


# ---------------------------------------------------------------------------
# Timeout configuration
# ---------------------------------------------------------------------------


def test_client_has_explicit_timeout() -> None:
    client = _make_client()
    timeout = client._client.timeout
    assert timeout.connect == 5.0
    assert timeout.read == 15.0
    assert timeout.write == 10.0
    assert timeout.pool == 5.0


# ---------------------------------------------------------------------------
# Retry on 5xx for GET
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_retries_on_503_and_succeeds() -> None:
    """GET retries twice on 503 and returns the third successful response."""
    client = _make_client()
    issue_data = {"number": 1}
    client._client.request = AsyncMock(side_effect=[
        _resp(503, {"message": "unavailable"}),
        _resp(503, {"message": "unavailable"}),
        _resp(200, issue_data),
    ])

    with patch("agentharness.github_client.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        result = await client.get_issue(1)

    assert result == issue_data
    assert client._client.request.call_count == 3
    assert mock_sleep.call_count == 2


@pytest.mark.asyncio
async def test_get_raises_after_exhausting_retries_on_503() -> None:
    """GET raises GitHubApiError after all retries are exhausted."""
    client = _make_client()
    client._client.request = AsyncMock(return_value=_resp(503, {"message": "unavailable"}))

    with patch("agentharness.github_client.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(GitHubApiError) as exc_info:
            await client.get_issue(1)

    assert exc_info.value.status_code == 503
    assert client._client.request.call_count == 3  # 1 original + 2 retries


@pytest.mark.asyncio
async def test_get_retries_on_502_and_504() -> None:
    client = _make_client()
    client._client.request = AsyncMock(side_effect=[
        _resp(502, {"message": "bad gateway"}),
        _resp(504, {"message": "timeout"}),
        _resp(200, {"number": 2}),
    ])

    with patch("agentharness.github_client.asyncio.sleep", new=AsyncMock()):
        result = await client.get_issue(2)

    assert result == {"number": 2}


@pytest.mark.asyncio
async def test_get_retries_on_429_with_retry_after_header() -> None:
    """GET honors Retry-After header (capped at _MAX_RETRY_AFTER) on 429."""
    client = _make_client()
    resp_429 = _resp(429, {"message": "rate limited"}, headers={"Retry-After": "2"})
    client._client.request = AsyncMock(side_effect=[
        resp_429,
        _resp(200, {"number": 3}),
    ])

    with patch("agentharness.github_client.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        result = await client.get_issue(3)

    assert result == {"number": 3}
    mock_sleep.assert_called_once_with(2.0)


@pytest.mark.asyncio
async def test_get_caps_retry_after_at_max() -> None:
    client = _make_client()
    resp_429 = _resp(429, {"message": "rate limited"}, headers={"Retry-After": "999"})
    client._client.request = AsyncMock(side_effect=[
        resp_429,
        _resp(200, {}),
    ])

    with patch("agentharness.github_client.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        await client.get_issue(4)

    mock_sleep.assert_called_once_with(5.0)


# ---------------------------------------------------------------------------
# Retry on network exceptions for GET
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_retries_on_read_timeout() -> None:
    client = _make_client()
    client._client.request = AsyncMock(side_effect=[
        httpx.ReadTimeout("read timeout"),
        httpx.ReadTimeout("read timeout"),
        _resp(200, {"number": 5}),
    ])

    with patch("agentharness.github_client.asyncio.sleep", new=AsyncMock()):
        result = await client.get_issue(5)

    assert result == {"number": 5}
    assert client._client.request.call_count == 3


@pytest.mark.asyncio
async def test_get_reraises_network_error_after_exhausting_retries() -> None:
    client = _make_client()
    client._client.request = AsyncMock(side_effect=httpx.ConnectTimeout("connect timeout"))

    with patch("agentharness.github_client.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(httpx.TimeoutException):
            await client.get_issue(6)

    assert client._client.request.call_count == 3  # 1 + 2 retries


# ---------------------------------------------------------------------------
# Non-idempotent verbs do NOT retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_does_not_retry_on_503() -> None:
    """POST must not retry — avoids duplicate issue creation."""
    client = _make_client()
    client._client.request = AsyncMock(return_value=_resp(503, {"message": "unavailable"}))

    with patch("agentharness.github_client.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        with pytest.raises(GitHubApiError) as exc_info:
            await client.create_issue("title", "body", ["label"])

    assert exc_info.value.status_code == 503
    assert client._client.request.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_post_does_not_retry_on_network_error() -> None:
    client = _make_client()
    client._client.request = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))

    with patch("agentharness.github_client.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        with pytest.raises(httpx.TimeoutException):
            await client.create_issue("title", "body", ["label"])

    assert client._client.request.call_count == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Non-retryable 4xx errors surface immediately (no sleep)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_404_surfaces_immediately_without_retry() -> None:
    client = _make_client()
    client._client.request = AsyncMock(return_value=_resp(404, {"message": "Not Found"}))

    with patch("agentharness.github_client.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        with pytest.raises(GitHubApiError) as exc_info:
            await client.get_issue(99)

    assert exc_info.value.status_code == 404
    assert client._client.request.call_count == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# list_comments uses _request (goes through retry)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_comments_retries_via_request() -> None:
    client = _make_client()
    comments = [{"id": 1, "body": "hello"}]
    client._client.request = AsyncMock(side_effect=[
        _resp(503, {"message": "unavailable"}),
        _resp(200, comments),
    ])

    with patch("agentharness.github_client.asyncio.sleep", new=AsyncMock()):
        result = await client.list_comments(42)

    assert result == comments
    assert client._client.request.call_count == 2
