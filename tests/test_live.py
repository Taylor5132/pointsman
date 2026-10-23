"""Live collection and the GitHub poller, with fakes instead of GitHub."""

import json
from datetime import datetime, timezone

import pytest

from pointsman.events.detector import PrintNotifier
from pointsman.events.source import GitHubPoller, IssueOpened, TeamLabelCreated
from pointsman.live.collect import run_once


def opened(number, labels=(), author_type="User"):
    issue = {
        "number": number,
        "title": f"Issue {number}",
        "body": "text",
        "createdAt": "2026-10-22T12:00:00Z",
        "author": {"login": "someone", "__typename": author_type},
        "labels": {"nodes": [{"id": f"LA_{name}", "name": name} for name in labels]},
    }
    return IssueOpened(number=number, created_at=datetime(2026, 10, 22, 12, tzinfo=timezone.utc), issue=issue)


class FakeSource:
    def __init__(self, events):
        self.events = events
        self.committed = False

    def poll(self):
        return self.events

    def commit(self):
        self.committed = True


def collected_numbers(live_dir):
    return [json.loads(line)["number"] for line in (live_dir / "issues.jsonl").read_text().splitlines()]


def test_only_unrouted_human_issues_are_collected(tmp_path):
    counts = run_once(FakeSource([
        opened(1),
        opened(2, labels=["team-engine"]),  # already routed: too late to predict
        opened(3, author_type="Bot"),
        opened(4, labels=["P2"]),  # non-Team labels are fine
    ]), PrintNotifier(), tmp_path)
    assert collected_numbers(tmp_path) == [1, 4]
    assert counts["skipped: already has a Team label"] == 1
    assert counts["skipped: bot author"] == 1


def test_an_issue_is_stored_once_even_if_delivered_twice(tmp_path):
    run_once(FakeSource([opened(1)]), PrintNotifier(), tmp_path)
    run_once(FakeSource([opened(1)]), PrintNotifier(), tmp_path)
    assert collected_numbers(tmp_path) == [1]


def test_progress_is_committed_only_after_events_are_handled(tmp_path):
    source = FakeSource([opened(1)])
    run_once(source, PrintNotifier(), tmp_path)
    assert source.committed

    malformed = opened(2)
    del malformed.issue["labels"]  # handling this Issue will crash
    crashing = FakeSource([malformed])
    with pytest.raises(KeyError):
        run_once(crashing, PrintNotifier(), tmp_path)
    assert not crashing.committed  # so the next poll delivers it again instead of losing it


# --- GitHubPoller ------------------------------------------------------------

class FakeGitHub:
    """Answers the poller's two queries from canned data."""

    def __init__(self, issues, labels, commits):
        self.issues, self.labels, self.commits = issues, labels, commits

    def query(self, query, variables):
        if "issues(" in query:
            return {"repository": {"issues": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": self.issues}}}
        return {"repository": {
            "labels": {"nodes": self.labels},
            "defaultBranchRef": {"target": {"history": {"nodes": self.commits}}},
        }}


def gh_issue(number, created_at):
    return {"number": number, "title": "t", "body": "b", "createdAt": created_at,
            "author": {"login": "a", "__typename": "User"}, "labels": {"nodes": []}}


LABEL = {"id": "LA_engine", "name": "team-engine", "createdAt": "2023-07-06T21:03:45Z"}
COMMIT = {"oid": "abc", "committedDate": "2026-10-14T22:30:30Z", "messageHeadline": "Update triage docs"}


def test_poller_delivers_only_issues_newer_than_last_commit(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"issues_since": "2026-10-22T10:00:00Z", "known_labels": ["LA_engine"],
                                 "rulebook_since": COMMIT["committedDate"]}))
    github = FakeGitHub([gh_issue(3, "2026-10-22T12:00:00Z"), gh_issue(2, "2026-10-22T11:00:00Z"),
                         gh_issue(1, "2026-10-22T09:00:00Z")], [LABEL], [COMMIT])
    poller = GitHubPoller(github, state)

    events = poller.poll()
    assert [e.number for e in events] == [3, 2]  # #1 is older than the marker

    poller.commit()
    assert json.loads(state.read_text())["issues_since"] == "2026-10-22T12:00:00+00:00"


def test_poller_alerts_on_a_new_team_label(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"issues_since": "2026-10-22T10:00:00Z", "known_labels": ["LA_engine"],
                                 "rulebook_since": COMMIT["committedDate"]}))
    new_label = {"id": "LA_gpu", "name": "team-fluttergpu", "createdAt": "2026-10-22T11:00:00Z"}
    poller = GitHubPoller(FakeGitHub([], [LABEL, new_label], [COMMIT]), state)

    events = poller.poll()
    assert events == [TeamLabelCreated(name="team-fluttergpu", label_id="LA_gpu",
                                       created_at=datetime(2026, 10, 22, 11, tzinfo=timezone.utc))]
