"""Where Pointsman hears about changes on GitHub.

Everything downstream (the live collector, the Team Split detector) reacts to three
kinds of event and never talks to GitHub directly:

    IssueOpened       a new Issue was filed
    TeamLabelCreated  a new team-* label appeared (a possible Team Split)
    RulebookChanged   Flutter's Triage Rulebook was edited

An EventSource produces these events. Today the only source is GitHubPoller, which
asks GitHub "what changed since last time?" every few minutes, because we cannot
install webhooks on flutter/flutter. On a repo we controlled, a webhook receiver
would produce the same three events the moment they happen, and nothing downstream
would change.

Delivery is "at least once": poll() returns events, the caller handles them, and
only then calls commit() to remember how far it got. If handling crashes, the next
poll() returns the same events again instead of losing them. So handlers must cope
with seeing an event twice.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from pointsman.pipeline.github_client import GitHubClient


@dataclass(frozen=True)
class IssueOpened:
    number: int
    created_at: datetime
    issue: dict  # the Issue exactly as GitHub sent it when we first saw it


@dataclass(frozen=True)
class TeamLabelCreated:
    name: str
    label_id: str
    created_at: datetime


@dataclass(frozen=True)
class RulebookChanged:
    commit: str
    committed_at: datetime
    summary: str


Event = IssueOpened | TeamLabelCreated | RulebookChanged


class EventSource(Protocol):
    """Anything that can be asked for new events. GitHubPoller is one; a webhook receiver could be another."""

    def poll(self) -> list[Event]: ...

    def commit(self) -> None: ...


NEW_ISSUES_QUERY = """
query($after: String) {
  rateLimit { cost remaining resetAt }
  repository(owner: "flutter", name: "flutter") {
    issues(first: 50, after: $after, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body createdAt
        author { login __typename }
        labels(first: 50) { nodes { id name } }
      }
    }
  }
}
"""

TAXONOMY_QUERY = """
query {
  rateLimit { cost remaining resetAt }
  repository(owner: "flutter", name: "flutter") {
    labels(first: 100, query: "team-") { nodes { id name createdAt } }
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 20, path: "docs/triage/README.md") { nodes { oid committedDate messageHeadline } }
        }
      }
    }
  }
}
"""


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text)


class GitHubPoller:
    """Turns "what changed since last time?" questions to GitHub into events.

    It remembers its progress in a small JSON state file:
        issues_since     created_at of the newest Issue already delivered
        known_labels     team-* label IDs already seen
        rulebook_since   commit time of the newest Rulebook commit already delivered
    """

    def __init__(self, client: GitHubClient, state_file: Path, first_run_lookback: timedelta = timedelta(hours=1)):
        self.client = client
        self.state_file = state_file
        self.first_run_lookback = first_run_lookback
        self.state = json.loads(state_file.read_text()) if state_file.exists() else None
        self.pending_state = None

    def poll(self) -> list[Event]:
        taxonomy = self.client.query(TAXONOMY_QUERY, {})["repository"]
        labels = [l for l in taxonomy["labels"]["nodes"] if l["name"].startswith("team-")]
        commits = taxonomy["defaultBranchRef"]["target"]["history"]["nodes"]

        if self.state is None:
            # First run ever: start from "now", without raising alerts for everything that already exists.
            now = datetime.now(timezone.utc)
            self.state = {
                "issues_since": (now - self.first_run_lookback).isoformat(),
                "known_labels": sorted(l["id"] for l in labels),
                "rulebook_since": commits[0]["committedDate"],
            }

        events: list[Event] = []
        events += self._new_issues(parse_time(self.state["issues_since"]))
        events += [
            TeamLabelCreated(name=l["name"], label_id=l["id"], created_at=parse_time(l["createdAt"]))
            for l in labels
            if l["id"] not in self.state["known_labels"]
        ]
        rulebook_since = parse_time(self.state["rulebook_since"])
        events += [
            RulebookChanged(commit=c["oid"], committed_at=parse_time(c["committedDate"]), summary=c["messageHeadline"])
            for c in reversed(commits)  # oldest first
            if parse_time(c["committedDate"]) > rulebook_since
        ]

        # Prepare the new progress marker, but only save it in commit().
        newest_issue = max((e.created_at for e in events if isinstance(e, IssueOpened)), default=None)
        self.pending_state = {
            "issues_since": (newest_issue or parse_time(self.state["issues_since"])).isoformat(),
            "known_labels": sorted(set(self.state["known_labels"]) | {l["id"] for l in labels}),
            "rulebook_since": commits[0]["committedDate"],
        }
        return events

    def commit(self) -> None:
        if self.pending_state is None:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.pending_state, indent=2) + "\n")
        self.state = self.pending_state
        self.pending_state = None

    def _new_issues(self, since: datetime) -> list[IssueOpened]:
        """All Issues created after `since`, newest first, walking pages until we pass it."""
        found = []
        cursor = None
        while True:
            page = self.client.query(NEW_ISSUES_QUERY, {"after": cursor})["repository"]["issues"]
            for issue in page["nodes"]:
                created_at = parse_time(issue["createdAt"])
                if created_at <= since:
                    return found
                found.append(IssueOpened(number=issue["number"], created_at=created_at, issue=issue))
            if not page["pageInfo"]["hasNextPage"]:
                return found
            cursor = page["pageInfo"]["endCursor"]
