"""Unit tests for agentharness.github_client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from agentharness.github_client import GitHubApiError, GitHubClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOKEN = "ghp_test_token"
_OWNER = "test-owner"
_REPO = "test-repo"


def _make_client() -> GitHubClient:
    return GitHubClient(token=_TOKEN, owner=_OWNER, repo=_REPO)


def _mock_response(status_code: int = 200, json_data: object = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = ""
    return resp


# ---------------------------------------------------------------------------
# GitHubApiError
# ---------------------------------------------------------------------------


def test_github_api_error_attributes() -> None:
    err = GitHubApiError(422, "Validation Failed")
    assert err.status_code == 422
    assert err.message == "Validation Failed"
    assert "422" in str(err)
    assert "Validation Failed" in str(err)


# ---------------------------------------------------------------------------
# create_issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_issue_sends_correct_request() -> None:
    client = _make_client()
    issue_data = {"number": 42, "title": "My Issue", "body": "body text"}

    mock_response = _mock_response(201, issue_data)
    client._client.request = AsyncMock(return_value=mock_response)

    result = await client.create_issue(
        title="My Issue", body="body text", labels=["bug", "feat:analyzing"]
    )

    # Verify the call
    client._client.request.assert_called_once()
    call_args = client._client.request.call_args

    assert call_args.args[0] == "POST"
    assert call_args.args[1] == f"/repos/{_OWNER}/{_REPO}/issues"
    assert call_args.kwargs["json"] == {
        "title": "My Issue",
        "body": "body text",
        "labels": ["bug", "feat:analyzing"],
    }

    # Verify the response is returned as-is
    assert result == issue_data


@pytest.mark.asyncio
async def test_create_issue_correct_headers() -> None:
    """Verify that the underlying AsyncClient is configured with correct headers."""
    client = _make_client()
    headers = dict(client._client.headers)

    assert "bearer ghp_test_token" in headers.get("authorization", "").lower()
    assert headers.get("accept") == "application/vnd.github+json"


# ---------------------------------------------------------------------------
# search_issues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_issues_returns_items() -> None:
    client = _make_client()
    items = [{"number": 1}, {"number": 2}]
    mock_response = _mock_response(200, {"total_count": 2, "items": items})
    client._client.request = AsyncMock(return_value=mock_response)

    result = await client.search_issues("is:open label:feat:analyzing")

    assert result == items

    call_args = client._client.request.call_args
    assert call_args.args[0] == "GET"
    assert call_args.args[1] == "/search/issues"
    params = call_args.kwargs["params"]
    assert params["q"] == "is:open label:feat:analyzing"
    assert params["sort"] == "created"
    assert params["order"] == "asc"


@pytest.mark.asyncio
async def test_search_issues_custom_sort() -> None:
    client = _make_client()
    mock_response = _mock_response(200, {"items": []})
    client._client.request = AsyncMock(return_value=mock_response)

    await client.search_issues("repo:owner/repo", sort="updated", order="desc")

    params = client._client.request.call_args.kwargs["params"]
    assert params["sort"] == "updated"
    assert params["order"] == "desc"


# ---------------------------------------------------------------------------
# GitHubApiError raised on 4xx/5xx
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raises_github_api_error_on_422() -> None:
    client = _make_client()
    mock_response = _mock_response(422, {"message": "Validation Failed"})
    client._client.request = AsyncMock(return_value=mock_response)

    with pytest.raises(GitHubApiError) as exc_info:
        await client.create_issue(title="x", body="y", labels=[])

    assert exc_info.value.status_code == 422
    assert "Validation Failed" in exc_info.value.message


@pytest.mark.asyncio
async def test_raises_github_api_error_on_404() -> None:
    client = _make_client()
    mock_response = _mock_response(404, {"message": "Not Found"})
    client._client.request = AsyncMock(return_value=mock_response)

    with pytest.raises(GitHubApiError) as exc_info:
        await client.get_issue(999)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_raises_github_api_error_on_500() -> None:
    client = _make_client()
    mock_response = _mock_response(500, {"message": "Internal Server Error"})
    client._client.request = AsyncMock(return_value=mock_response)

    with pytest.raises(GitHubApiError) as exc_info:
        await client.get_issue(1)

    assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# ensure_label
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_label_is_noop_when_label_exists() -> None:
    """When GET /labels/{name} returns 200, no POST should be made."""
    client = _make_client()
    get_response = _mock_response(200, {"name": "bug", "color": "d73a4a"})
    client._client.request = AsyncMock(return_value=get_response)

    await client.ensure_label("bug")

    # Only one call: the GET
    assert client._client.request.call_count == 1
    call_args = client._client.request.call_args
    assert call_args.args[0] == "GET"


@pytest.mark.asyncio
async def test_ensure_label_creates_label_when_not_found() -> None:
    """When GET /labels/{name} returns 404, POST /labels should be called."""
    client = _make_client()

    not_found = _mock_response(404, {"message": "Not Found"})
    created = _mock_response(201, {"name": "new-label", "color": "ededed"})

    call_count = 0

    async def mock_request(method: str, url: str, **kwargs: object):
        nonlocal call_count
        call_count += 1
        if method == "GET":
            return not_found
        return created

    client._client.request = mock_request

    await client.ensure_label("new-label")

    assert call_count == 2


@pytest.mark.asyncio
async def test_ensure_label_reraises_non_404_error() -> None:
    """When GET /labels/{name} returns a non-404 error, it should propagate."""
    client = _make_client()
    server_error = _mock_response(500, {"message": "Internal Server Error"})
    client._client.request = AsyncMock(return_value=server_error)

    with pytest.raises(GitHubApiError) as exc_info:
        await client.ensure_label("any-label")

    assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_context_manager() -> None:
    """Verify GitHubClient works as an async context manager."""
    client = _make_client()
    client._client.aclose = AsyncMock()

    async with client as ctx:
        assert ctx is client

    client._client.aclose.assert_called_once()


# ---------------------------------------------------------------------------
# from_config classmethod
# ---------------------------------------------------------------------------


def test_from_config() -> None:
    config = MagicMock()
    config.github.token = "tok"
    config.github.owner = "myorg"
    config.github.runs_repo = "runs"

    client = GitHubClient.from_config(config)

    assert client.owner == "myorg"
    assert client.repo == "runs"


# ---------------------------------------------------------------------------
# Other methods – smoke tests for correct URL / payload construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_issue_builds_partial_payload() -> None:
    client = _make_client()
    mock_response = _mock_response(200, {"number": 1})
    client._client.request = AsyncMock(return_value=mock_response)

    await client.update_issue(1, state="closed")

    payload = client._client.request.call_args.kwargs["json"]
    assert payload == {"state": "closed"}
    assert "title" not in payload
    assert "body" not in payload


@pytest.mark.asyncio
async def test_add_labels_sends_correct_payload() -> None:
    client = _make_client()
    mock_response = _mock_response(200, [])
    client._client.request = AsyncMock(return_value=mock_response)

    await client.add_labels(7, ["label-a", "label-b"])

    call_args = client._client.request.call_args
    assert call_args.args[0] == "POST"
    assert "/issues/7/labels" in call_args.args[1]
    assert call_args.kwargs["json"] == {"labels": ["label-a", "label-b"]}


@pytest.mark.asyncio
async def test_remove_label_sends_delete() -> None:
    client = _make_client()
    mock_response = _mock_response(204)
    client._client.request = AsyncMock(return_value=mock_response)

    await client.remove_label(7, "state:queued")

    call_args = client._client.request.call_args
    assert call_args.args[0] == "DELETE"
    assert "/issues/7/labels/" in call_args.args[1]


@pytest.mark.asyncio
async def test_create_comment_posts_to_correct_url() -> None:
    client = _make_client()
    mock_response = _mock_response(201, {"id": 99, "body": "hello"})
    client._client.request = AsyncMock(return_value=mock_response)

    result = await client.create_comment(5, "hello")

    call_args = client._client.request.call_args
    assert call_args.args[0] == "POST"
    assert "/issues/5/comments" in call_args.args[1]
    assert result == {"id": 99, "body": "hello"}


@pytest.mark.asyncio
async def test_create_pull_request_payload() -> None:
    client = _make_client()
    pr_data = {"number": 10, "html_url": "https://github.com/..."}
    mock_response = _mock_response(201, pr_data)
    client._client.request = AsyncMock(return_value=mock_response)

    result = await client.create_pull_request(
        title="My PR", body="description", head="feat-123", base="main"
    )

    payload = client._client.request.call_args.kwargs["json"]
    assert payload == {
        "title": "My PR",
        "body": "description",
        "head": "feat-123",
        "base": "main",
    }
    assert result == pr_data


@pytest.mark.asyncio
async def test_put_content_omits_sha_when_none() -> None:
    client = _make_client()
    mock_response = _mock_response(201, {"content": {}, "commit": {}})
    client._client.request = AsyncMock(return_value=mock_response)

    await client.put_content(
        path="README.md",
        message="initial commit",
        content="SGVsbG8=",
        sha=None,
        branch="feat-abc",
    )

    payload = client._client.request.call_args.kwargs["json"]
    assert "sha" not in payload
    assert payload["branch"] == "feat-abc"


@pytest.mark.asyncio
async def test_put_content_includes_sha_when_provided() -> None:
    client = _make_client()
    mock_response = _mock_response(200, {"content": {}, "commit": {}})
    client._client.request = AsyncMock(return_value=mock_response)

    await client.put_content(
        path="README.md",
        message="update",
        content="SGVsbG8=",
        sha="abc123",
        branch="feat-abc",
    )

    payload = client._client.request.call_args.kwargs["json"]
    assert payload["sha"] == "abc123"


@pytest.mark.asyncio
async def test_add_sub_issue_posts_sub_issue_id() -> None:
    client = _make_client()
    mock_response = _mock_response(201, {})
    client._client.request = AsyncMock(return_value=mock_response)

    await client.add_sub_issue(parent_number=1, child_number=2)

    call_args = client._client.request.call_args
    assert call_args.args[0] == "POST"
    assert "/issues/1/sub_issues" in call_args.args[1]
    assert call_args.kwargs["json"] == {"sub_issue_id": 2}


@pytest.mark.asyncio
async def test_get_ref_calls_correct_url() -> None:
    client = _make_client()
    ref_data = {"object": {"sha": "deadbeef"}}
    mock_response = _mock_response(200, ref_data)
    client._client.request = AsyncMock(return_value=mock_response)

    result = await client.get_ref("heads/main")

    call_args = client._client.request.call_args
    assert call_args.args[0] == "GET"
    assert "/git/ref/heads/main" in call_args.args[1]
    assert result == ref_data


@pytest.mark.asyncio
async def test_create_ref_sends_correct_payload() -> None:
    client = _make_client()
    mock_response = _mock_response(201, {"ref": "refs/heads/feat-x"})
    client._client.request = AsyncMock(return_value=mock_response)

    await client.create_ref("refs/heads/feat-x", "deadbeef")

    payload = client._client.request.call_args.kwargs["json"]
    assert payload == {"ref": "refs/heads/feat-x", "sha": "deadbeef"}


# ---------------------------------------------------------------------------
# create_pull_request with labels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_pull_request_without_labels_makes_one_call() -> None:
    """When labels is None, only POST /pulls is called."""
    client = _make_client()
    with patch.object(
        client, "_request", new=AsyncMock(return_value={"number": 1, "html_url": "u"})
    ) as mock_request:
        result = await client.create_pull_request(
            title="t", body="b", head="feat", base="main"
        )
    assert result == {"number": 1, "html_url": "u"}
    assert mock_request.await_count == 1
    method, url = mock_request.call_args[0][:2]
    assert method == "POST"
    assert url.endswith("/pulls")
    await client.close()


@pytest.mark.asyncio
async def test_create_pull_request_with_empty_labels_makes_one_call() -> None:
    """Empty list labels=[] is treated like None — no second call."""
    client = _make_client()
    with patch.object(
        client, "_request", new=AsyncMock(return_value={"number": 1})
    ) as mock_request:
        await client.create_pull_request(
            title="t", body="b", head="feat", base="main", labels=[]
        )
    assert mock_request.await_count == 1
    await client.close()


@pytest.mark.asyncio
async def test_create_pull_request_with_labels_applies_them_via_issues_endpoint() -> None:
    """When labels is non-empty, a second POST /issues/{n}/labels call is made."""
    client = _make_client()
    responses = [
        {"number": 42, "html_url": "https://example/pr/42"},  # POST /pulls
        [{"name": "agent"}],                                   # POST /issues/42/labels
    ]
    with patch.object(
        client, "_request", new=AsyncMock(side_effect=responses)
    ) as mock_request:
        result = await client.create_pull_request(
            title="t", body="b", head="feat", base="main", labels=["agent"]
        )
    assert result == {"number": 42, "html_url": "https://example/pr/42"}
    assert mock_request.await_count == 2
    second_method, second_url = mock_request.await_args_list[1].args[:2]
    assert second_method == "POST"
    assert second_url.endswith("/issues/42/labels")
    second_kwargs = mock_request.await_args_list[1].kwargs
    assert second_kwargs["json"] == {"labels": ["agent"]}
    await client.close()


@pytest.mark.asyncio
async def test_create_pull_request_reraises_when_label_apply_fails() -> None:
    """If label application fails, the error propagates (no rollback)."""
    client = _make_client()
    responses = [
        {"number": 99, "html_url": "u"},
        RuntimeError("rate limited"),
    ]

    async def _side_effect(*args, **kwargs):
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    with patch.object(client, "_request", new=AsyncMock(side_effect=_side_effect)):
        with pytest.raises(RuntimeError, match="rate limited"):
            await client.create_pull_request(
                title="t", body="b", head="feat", base="main", labels=["agent"]
            )
    await client.close()


# ---------------------------------------------------------------------------
# list_sub_issues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sub_issues_returns_list_of_dicts() -> None:
    """GET /issues/{n}/sub_issues returns a list of issue dicts."""
    client = _make_client()
    sub_issues = [{"number": 2, "title": "child A"}, {"number": 3, "title": "child B"}]
    with patch.object(
        client, "_request", new=AsyncMock(return_value=sub_issues)
    ) as mock_request:
        result = await client.list_sub_issues(1)

    assert result == sub_issues
    method, url = mock_request.call_args.args[:2]
    assert method == "GET"
    assert url.endswith("/issues/1/sub_issues")
    await client.close()


@pytest.mark.asyncio
async def test_list_sub_issues_returns_empty_list_when_none() -> None:
    """When the API returns an empty array, list_sub_issues returns []."""
    client = _make_client()
    with patch.object(client, "_request", new=AsyncMock(return_value=[])):
        result = await client.list_sub_issues(99)

    assert result == []
    await client.close()


# ---------------------------------------------------------------------------
# get_parent_issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_parent_issue_returns_parent_when_field_present() -> None:
    """When the issue response includes parent_issue, return it."""
    client = _make_client()
    parent_data = {"number": 10, "title": "Epic issue"}
    issue_response = {"number": 42, "title": "child", "parent_issue": parent_data}
    with patch.object(client, "_request", new=AsyncMock(return_value=issue_response)):
        result = await client.get_parent_issue(42)

    assert result == parent_data
    await client.close()


@pytest.mark.asyncio
async def test_get_parent_issue_returns_none_when_field_absent() -> None:
    """When parent_issue is not in the response, return None."""
    client = _make_client()
    issue_response = {"number": 5, "title": "standalone issue"}
    with patch.object(client, "_request", new=AsyncMock(return_value=issue_response)):
        result = await client.get_parent_issue(5)

    assert result is None
    await client.close()


@pytest.mark.asyncio
async def test_get_parent_issue_returns_none_when_field_is_null() -> None:
    """When parent_issue is explicitly null/None, return None."""
    client = _make_client()
    issue_response = {"number": 7, "title": "no parent", "parent_issue": None}
    with patch.object(client, "_request", new=AsyncMock(return_value=issue_response)):
        result = await client.get_parent_issue(7)

    assert result is None
    await client.close()


# ---------------------------------------------------------------------------
# create_pull_request with draft=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_pull_request_with_draft_true_includes_draft_in_payload() -> None:
    """draft=True should add 'draft': true to the POST /pulls payload."""
    client = _make_client()
    pr_data = {"number": 55, "html_url": "https://github.com/pr/55", "draft": True}
    with patch.object(
        client, "_request", new=AsyncMock(return_value=pr_data)
    ) as mock_request:
        result = await client.create_pull_request(
            title="Draft PR", body="WIP", head="feat-x", base="main", draft=True
        )

    assert result == pr_data
    payload = mock_request.call_args.kwargs["json"]
    assert payload["draft"] is True
    await client.close()


@pytest.mark.asyncio
async def test_create_pull_request_default_draft_false_omits_draft_field() -> None:
    """When draft is not passed (default False), 'draft' should NOT appear in payload."""
    client = _make_client()
    pr_data = {"number": 56, "html_url": "https://github.com/pr/56"}
    with patch.object(
        client, "_request", new=AsyncMock(return_value=pr_data)
    ) as mock_request:
        await client.create_pull_request(
            title="Normal PR", body="desc", head="feat-y", base="main"
        )

    payload = mock_request.call_args.kwargs["json"]
    assert "draft" not in payload
    await client.close()


# ---------------------------------------------------------------------------
# update_pull_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_pull_request_with_body_and_draft() -> None:
    """PATCH /pulls/{n} should include only provided fields."""
    client = _make_client()
    updated_pr = {"number": 10, "body": "new body", "draft": False}
    with patch.object(
        client, "_request", new=AsyncMock(return_value=updated_pr)
    ) as mock_request:
        result = await client.update_pull_request(10, body="new body", draft=False)

    assert result == updated_pr
    method, url = mock_request.call_args.args[:2]
    assert method == "PATCH"
    assert url.endswith("/pulls/10")
    payload = mock_request.call_args.kwargs["json"]
    assert payload == {"body": "new body", "draft": False}
    await client.close()


@pytest.mark.asyncio
async def test_update_pull_request_with_only_draft() -> None:
    """When only draft is supplied, payload contains only 'draft'."""
    client = _make_client()
    with patch.object(
        client, "_request", new=AsyncMock(return_value={"number": 11})
    ) as mock_request:
        await client.update_pull_request(11, draft=True)

    payload = mock_request.call_args.kwargs["json"]
    assert payload == {"draft": True}
    assert "body" not in payload
    await client.close()


@pytest.mark.asyncio
async def test_update_pull_request_with_only_body() -> None:
    """When only body is supplied, payload contains only 'body'."""
    client = _make_client()
    with patch.object(
        client, "_request", new=AsyncMock(return_value={"number": 12})
    ) as mock_request:
        await client.update_pull_request(12, body="updated description")

    payload = mock_request.call_args.kwargs["json"]
    assert payload == {"body": "updated description"}
    assert "draft" not in payload
    await client.close()


# ---------------------------------------------------------------------------
# mark_pr_ready
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_pr_ready_calls_update_pull_request_with_draft_false() -> None:
    """mark_pr_ready should delegate to update_pull_request(number, draft=False)."""
    client = _make_client()
    ready_pr = {"number": 20, "draft": False}
    with patch.object(
        client, "update_pull_request", new=AsyncMock(return_value=ready_pr)
    ) as mock_update:
        result = await client.mark_pr_ready(20)

    assert result == ready_pr
    mock_update.assert_awaited_once_with(20, draft=False)
    await client.close()
