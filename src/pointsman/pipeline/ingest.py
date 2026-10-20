"""Download raw Flutter Issues from GitHub into a dated snapshot folder.

Usage:
    uv run python -m pointsman.pipeline.ingest --limit 200

Writes one JSON object per line (JSONL) to data/snapshots/<today>/raw/issues.jsonl
(or <today>-sample<N>/ when --limit is used),
plus raw/ingest_info.json recording how and when the download was made and which
Taxonomy Version was in force. Nothing is cleaned here; raw data is kept exactly as
GitHub sent it, so cleaning can be re-run later without downloading again.
"""

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

from pointsman.pipeline.github_client import GitHubClient, get_token
from pointsman.teams import DATA_START, IN_SCOPE_TEAMS, OUT_OF_SCOPE_TEAMS

# One page of Issues, newest first, filtered to Issues carrying any of our Team labels.
ISSUES_QUERY = """
query($labels: [String!], $first: Int!, $after: String) {
  rateLimit { cost remaining resetAt }
  repository(owner: "flutter", name: "flutter") {
    issues(labels: $labels, states: [OPEN, CLOSED], first: $first, after: $after,
           orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        body
        state
        stateReason
        createdAt
        closedAt
        author { login __typename }
        labels(first: 50) { nodes { id name } }
        timelineItems(itemTypes: [LABELED_EVENT, UNLABELED_EVENT], first: 100) {
          totalCount
          nodes {
            __typename
            ... on LabeledEvent   { createdAt actor { login __typename } label { id name } }
            ... on UnlabeledEvent { createdAt actor { login __typename } label { id name } }
          }
        }
        comments(last: 5) { nodes { body createdAt author { login } } }
      }
    }
  }
}
"""


# The Taxonomy Version: which Team labels exist (by permanent ID) and which version
# of Flutter's Triage Rulebook is in force (its latest commit).
TAXONOMY_QUERY = """
query {
  rateLimit { cost remaining resetAt }
  repository(owner: "flutter", name: "flutter") {
    labels(first: 100, query: "team-") { nodes { id name createdAt } }
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 1, path: "docs/triage/README.md") { nodes { oid committedDate } }
        }
      }
    }
  }
}
"""


def fetch_taxonomy(client: GitHubClient) -> dict:
    data = client.query(TAXONOMY_QUERY, {})["repository"]
    commit = data["defaultBranchRef"]["target"]["history"]["nodes"][0]
    teams = {
        label["name"]: {"id": label["id"], "created_at": label["createdAt"]}
        for label in data["labels"]["nodes"]
        if label["name"].startswith("team-")
    }
    return {
        "id": f"rulebook-{commit['oid'][:7]}",
        "rulebook_commit": commit["oid"],
        "rulebook_committed_at": commit["committedDate"],
        "teams": dict(sorted(teams.items())),
    }


def fetch_issues(client: GitHubClient, limit: int | None, page_size: int = 50):
    """Yield Issues one by one, newest first, stopping at DATA_START or after `limit` Issues."""
    labels = IN_SCOPE_TEAMS + OUT_OF_SCOPE_TEAMS
    start = DATA_START.strftime("%Y-%m-%dT%H:%M:%SZ")
    cursor = None
    count = 0

    while True:
        data = client.query(ISSUES_QUERY, {"labels": labels, "first": page_size, "after": cursor})
        page = data["repository"]["issues"]

        for issue in page["nodes"]:
            # ISO-8601 timestamps sort correctly as plain strings.
            if issue["createdAt"] < start:
                return
            yield issue
            count += 1
            if limit is not None and count >= limit:
                return

        if not page["pageInfo"]["hasNextPage"]:
            return
        cursor = page["pageInfo"]["endCursor"]
        print(f"  {count} Issues so far (rate limit left: {data['rateLimit']['remaining']})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None, help="stop after N Issues (default: all)")
    parser.add_argument("--out", type=Path, default=Path("data/snapshots"))
    args = parser.parse_args()

    # A sample gets its own folder name, so it never takes the place of a full download.
    name = date.today().isoformat() if args.limit is None else f"{date.today().isoformat()}-sample{args.limit}"
    snapshot_dir = args.out / name
    if (snapshot_dir / "manifest.json").exists():
        raise SystemExit(f"{snapshot_dir} is frozen (it has a manifest). Snapshots never change.")

    raw_dir = snapshot_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_file = raw_dir / "issues.jsonl"

    client = GitHubClient(get_token())
    started_at = datetime.now(timezone.utc)
    taxonomy = fetch_taxonomy(client)

    count = 0
    with out_file.open("w") as f:
        for issue in fetch_issues(client, args.limit):
            f.write(json.dumps(issue) + "\n")
            count += 1

    info = {
        "repo": "flutter/flutter",
        "teams_queried": IN_SCOPE_TEAMS + OUT_OF_SCOPE_TEAMS,
        "data_start": DATA_START.isoformat(),
        "limit": args.limit,
        "complete": args.limit is None,  # False means this is only a sample
        "issues": count,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "taxonomy_version": taxonomy,
    }
    (raw_dir / "ingest_info.json").write_text(json.dumps(info, indent=2) + "\n")

    print(f"Wrote {count} Issues to {out_file} (Taxonomy Version {taxonomy['id']})")


if __name__ == "__main__":
    main()
