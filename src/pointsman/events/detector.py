"""Team Split detector: turn taxonomy events into alerts a human will actually see.

Two events can mean Flutter's Teams are changing (a possible Team Split):
    TeamLabelCreated  a new team-* label appeared
    RulebookChanged   someone edited the Triage Rulebook

For each one the detector
  1. appends a line to data/live/alerts.jsonl (the permanent record), and
  2. sends a notification. On GitHub Actions that opens an Issue in the Pointsman repo
     and @mentions the owner, so the alert reaches their inbox.

The detector never edits the Team Change Log itself. The human regenerates it with
`python -m pointsman.pipeline.change_log` and commits the diff; that commit is the
approval of a new Taxonomy Version (ADR 0001).

Delivery is at least once, so the same event can arrive twice. Each alert has a key
(the label ID or the commit SHA) written into the Issue title, and the notifier skips
keys it has already opened an Issue for. That makes repeats harmless ("idempotent").
"""

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from pointsman.events.source import Event, RulebookChanged, TeamLabelCreated
from pointsman.pipeline.github_client import GitHubClient

APPROVAL_STEPS = """What to do:
1. Regenerate the Team Change Log: `uv run python -m pointsman.pipeline.change_log`
2. Read the diff. For a new label, look for the Rulebook commit that explains it; for a Rulebook edit, check whether any Team's responsibilities moved.
3. Commit the diff. That commit approves the new Taxonomy Version (ADR 0001).
4. Close this Issue."""


@dataclass(frozen=True)
class Alert:
    key: str  # the same event always gets the same key
    title: str
    body: str
    record: dict  # the line for alerts.jsonl


class Notifier(Protocol):
    def notify(self, alert: Alert) -> None: ...


def alert_for(event: TeamLabelCreated | RulebookChanged) -> Alert:
    if isinstance(event, TeamLabelCreated):
        url = f"https://github.com/flutter/flutter/labels/{quote(event.name)}"
        return Alert(
            key=event.label_id,
            title=f"Possible Team Split: new label {event.name} ({event.label_id})",
            body=(
                f"Flutter created a new Team label [{event.name}]({url}) on {event.created_at:%Y-%m-%d}.\n\n"
                "Pointsman's model does not know this Team, so its Issues will be misrouted "
                "until the Taxonomy Version is updated.\n\n" + APPROVAL_STEPS
            ),
            record={"kind": "team_label_created", "team": event.name, "label_id": event.label_id,
                    "created_at": event.created_at.isoformat()},
        )
    url = f"https://github.com/flutter/flutter/commit/{event.commit}"
    return Alert(
        key=event.commit[:7],
        title=f"Triage Rulebook changed: {event.summary} ({event.commit[:7]})",
        body=(
            f"Flutter's Triage Rulebook was edited on {event.committed_at:%Y-%m-%d}: [{event.summary}]({url})\n\n"
            "Rulebook edits often follow a Team Split by a few days.\n\n" + APPROVAL_STEPS
        ),
        record={"kind": "rulebook_changed", "commit": event.commit,
                "committed_at": event.committed_at.isoformat(), "summary": event.summary},
    )


def handle(events: list[Event], live_dir: Path, notifier: Notifier) -> Counter:
    """Record and send an alert for every taxonomy event. Other events are ignored."""
    counts = Counter()
    now = datetime.now(timezone.utc).isoformat()
    for event in events:
        if not isinstance(event, (TeamLabelCreated, RulebookChanged)):
            continue
        alert = alert_for(event)
        notifier.notify(alert)
        with (live_dir / "alerts.jsonl").open("a") as f:
            f.write(json.dumps({"seen_at": now, **alert.record}) + "\n")
        counts["alerts"] += 1
    return counts


class PrintNotifier:
    """For local runs: just print."""

    def notify(self, alert: Alert) -> None:
        print(f"  ALERT: {alert.title}")


REPO_QUERY = """
query($owner: String!, $name: String!) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    id
    issues(last: 100) { nodes { title } }
  }
}
"""

CREATE_ISSUE = """
mutation($repo: ID!, $title: String!, $body: String!) {
  createIssue(input: {repositoryId: $repo, title: $title, body: $body}) { issue { url } }
}
"""


class GitHubIssueNotifier:
    """Opens one Issue per alert in our own repo (for example "Taylor5132/pointsman")."""

    def __init__(self, client: GitHubClient, repo: str, mention: str | None = None):
        self.client = client
        self.owner, self.name = repo.split("/")
        self.mention = mention

    def notify(self, alert: Alert) -> None:
        repo = self.client.query(REPO_QUERY, {"owner": self.owner, "name": self.name})["repository"]
        if any(f"({alert.key})" in issue["title"] for issue in repo["issues"]["nodes"]):
            print(f"  ALERT already sent: {alert.title}")
            return
        body = alert.body + (f"\n\n@{self.mention}" if self.mention else "")
        created = self.client.query(CREATE_ISSUE, {"repo": repo["id"], "title": alert.title, "body": body})
        print(f"  ALERT: {alert.title} -> {created['createIssue']['issue']['url']}")


def send_test_alert() -> None:
    """Open one clearly marked test Issue, to check the real notification path works."""
    import os

    from pointsman.pipeline.github_client import get_token

    now = datetime.now(timezone.utc)
    alert = Alert(
        key=f"test-{now:%Y%m%d%H%M%S}",
        title=f"[test] Pointsman alert check (test-{now:%Y%m%d%H%M%S})",
        body="A test of the Team Split detector's notifications. Nothing changed in Flutter. Close this Issue.",
        record={},
    )
    GitHubIssueNotifier(GitHubClient(get_token()), os.environ["GITHUB_REPOSITORY"],
                        os.environ.get("GITHUB_REPOSITORY_OWNER")).notify(alert)


if __name__ == "__main__":
    send_test_alert()
