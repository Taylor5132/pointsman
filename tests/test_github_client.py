"""The GitHub client against a fake GitHub (no network), to check how it reacts to each kind of failure."""

import httpx
import pytest

from pointsman.pipeline.github_client import GitHubClient, QueryTimeout

OK = {"data": {"rateLimit": {"remaining": 4000, "resetAt": "2026-01-01T00:00:00Z"}, "hello": "world"}}
TOO_HEAVY = {"errors": [{"message": "Something went wrong while executing your query on 2026-10-22T16:21:41Z."}]}
TYPO = {"errors": [{"message": "Field 'teamOwner' doesn't exist on type 'Issue'"}]}


def fake_github(*answers):
    """A client whose fake GitHub gives these answers, one per request, in order."""
    calls = []

    def handle(request):
        calls.append(request)
        status, body = answers[len(calls) - 1]
        return httpx.Response(status, json=body)

    client = GitHubClient("fake-token", max_retries=3, base_wait=0, transport=httpx.MockTransport(handle))
    return client, calls


def test_too_heavy_is_retried():
    client, calls = fake_github((200, TOO_HEAVY), (200, OK))
    assert client.query("{ hello }", {})["hello"] == "world"
    assert len(calls) == 2


def test_server_overload_is_retried():
    client, calls = fake_github((502, {}), (200, OK))
    assert client.query("{ hello }", {})["hello"] == "world"
    assert len(calls) == 2


def test_real_errors_fail_at_once():
    client, calls = fake_github((200, TYPO))
    with pytest.raises(RuntimeError, match="teamOwner"):
        client.query("{ teamOwner }", {})
    assert len(calls) == 1


def test_always_too_heavy_raises_query_timeout():
    client, calls = fake_github((200, TOO_HEAVY), (200, TOO_HEAVY), (200, TOO_HEAVY))
    with pytest.raises(QueryTimeout):
        client.query("{ hello }", {})
    assert len(calls) == 3
