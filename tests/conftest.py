"""Shared test helpers. pytest loads this file automatically."""

import pytest


@pytest.fixture
def make_issue():
    """A factory for fake Issues shaped exactly like GitHub's GraphQL answer.

    Every argument has a sensible default, so a test only spells out what it cares about:
        make_issue(labels=["team-web"], author="bob")

    `events` is a list of (kind, label name, actor login) tuples, oldest first.
    """

    def factory(
        number=1,
        title="A title",
        body="",
        state="OPEN",
        state_reason=None,
        created_at="2024-01-01T00:00:00Z",
        author="alice",
        author_type="User",
        labels=("team-engine",),
        events=(),
        comments=(),
    ):
        return {
            "number": number,
            "title": title,
            "body": body,
            "state": state,
            "stateReason": state_reason,
            "createdAt": created_at,
            "closedAt": None,
            "author": None if author is None else {"login": author, "__typename": author_type},
            "labels": {"nodes": [{"id": f"LA_{name}", "name": name} for name in labels]},
            "timelineItems": {
                "totalCount": len(events),
                "nodes": [
                    {
                        "__typename": kind,
                        "createdAt": created_at,
                        "actor": None if actor is None else {"login": actor, "__typename": "User"},
                        "label": {"id": f"LA_{name}", "name": name},
                    }
                    for kind, name, actor in events
                ],
            },
            "comments": {
                "nodes": [{"body": text, "createdAt": created_at, "author": {"login": "triager"}} for text in comments]
            },
        }

    return factory
