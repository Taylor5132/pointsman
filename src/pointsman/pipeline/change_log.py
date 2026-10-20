"""Build the Team Change Log: every dated change to Flutter's Teams and triage rules.

Usage:
    uv run python -m pointsman.pipeline.change_log

Writes taxonomy/team_change_log.csv, which is committed to git. Re-running it
regenerates the file; `git diff` then shows exactly which events are new, and
committing that diff is the human approval step (ADR 0001).

Two kinds of event:
  team_created     a team-* label appeared (its creation date and permanent ID)
  rulebook_changed a commit edited Flutter's Triage Rulebook (docs/triage/README.md)

Known gaps:
  - The Rulebook moved into the repo on 2024-05-28; earlier edits lived in the
    GitHub wiki and are not included.
  - A deleted label disappears from GitHub entirely, so removed Teams leave no
    team_created row (Rulebook commits sometimes mention them).
"""

import csv
from pathlib import Path

from pointsman.pipeline.github_client import GitHubClient, get_token

OUT_FILE = Path("taxonomy/team_change_log.csv")
COLUMNS = ["date", "event", "team", "label_id", "commit", "summary", "url"]

LABELS_QUERY = """
query($after: String) {
  rateLimit { cost remaining resetAt }
  repository(owner: "flutter", name: "flutter") {
    labels(first: 100, after: $after, query: "team-") {
      pageInfo { hasNextPage endCursor }
      nodes { id name createdAt url }
    }
  }
}
"""

RULEBOOK_QUERY = """
query($after: String) {
  rateLimit { cost remaining resetAt }
  repository(owner: "flutter", name: "flutter") {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $after, path: "docs/triage/README.md") {
            pageInfo { hasNextPage endCursor }
            nodes { oid committedDate messageHeadline url }
          }
        }
      }
    }
  }
}
"""


def team_created_events(client: GitHubClient) -> list[dict]:
    events = []
    cursor = None
    while True:
        page = client.query(LABELS_QUERY, {"after": cursor})["repository"]["labels"]
        for label in page["nodes"]:
            if label["name"].startswith("team-"):  # the search also matches words like "Fuchsia team"
                events.append({
                    "date": label["createdAt"],
                    "event": "team_created",
                    "team": label["name"],
                    "label_id": label["id"],
                    "commit": "",
                    "summary": f"Label {label['name']} created",
                    "url": label["url"],
                })
        if not page["pageInfo"]["hasNextPage"]:
            return events
        cursor = page["pageInfo"]["endCursor"]


def rulebook_events(client: GitHubClient) -> list[dict]:
    events = []
    cursor = None
    while True:
        data = client.query(RULEBOOK_QUERY, {"after": cursor})
        page = data["repository"]["defaultBranchRef"]["target"]["history"]
        for commit in page["nodes"]:
            events.append({
                "date": commit["committedDate"],
                "event": "rulebook_changed",
                "team": "",
                "label_id": "",
                "commit": commit["oid"],
                "summary": commit["messageHeadline"],
                "url": commit["url"],
            })
        if not page["pageInfo"]["hasNextPage"]:
            return events
        cursor = page["pageInfo"]["endCursor"]


def main() -> None:
    client = GitHubClient(get_token())
    events = team_created_events(client) + rulebook_events(client)
    events.sort(key=lambda e: (e["date"], e["event"], e["team"]))  # oldest first; ties in a fixed order

    OUT_FILE.parent.mkdir(exist_ok=True)
    with OUT_FILE.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(events)

    teams = sum(e["event"] == "team_created" for e in events)
    print(f"Wrote {len(events)} events ({teams} team_created, {len(events) - teams} rulebook_changed) to {OUT_FILE}")


if __name__ == "__main__":
    main()
