"""Live collection: save new Issues that no one has routed yet, frozen as first seen.

Usage (one poll):
    uv run python -m pointsman.live.collect

GitHub Actions runs this every ~15 minutes (.github/workflows/collect.yml) and commits
data/live/ to the live-data branch. Locally, data/live/ is a git worktree of that
branch: `git -C data/live pull` shows the latest. Do not poll locally as well, or the
two copies of the bookmark will drift apart.

Writes (all under data/live/):
    issues.jsonl       one line per collected Issue, text frozen at collection time
    collect_log.jsonl  one line per poll: how many Issues were seen, kept and skipped why
    alerts.jsonl       new team-* labels and Triage Rulebook edits (written by events/detector.py)
    poller_state.json  how far the poller has got

Rules that keep the Live Evaluation honest:
  - An Issue is stored once, the first time we see it, and never updated.
  - We never fetch a collected Issue's labels again until scoring day.
  - Issues that already carry a Team label when we first see them are skipped:
    someone (usually the author) routed them before we could predict.
"""

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pointsman.events import detector
from pointsman.events.detector import GitHubIssueNotifier, Notifier, PrintNotifier
from pointsman.events.source import Event, EventSource, GitHubPoller, IssueOpened
from pointsman.pipeline.github_client import GitHubClient, get_token

LIVE_DIR = Path("data/live")


def already_collected(issues_file: Path) -> set[int]:
    if not issues_file.exists():
        return set()
    with issues_file.open() as f:
        return {json.loads(line)["number"] for line in f}


def skip_reason(event: IssueOpened, collected: set[int]) -> str | None:
    """Why this Issue cannot join the live set, or None if it can."""
    issue = event.issue
    if event.number in collected:
        return "already collected"  # at-least-once delivery can repeat an event
    if issue["author"] is not None and issue["author"]["__typename"] == "Bot":
        return "bot author"
    if any(label["name"].startswith("team-") for label in issue["labels"]["nodes"]):
        return "already has a Team label"
    return None


def handle(events: list[Event], live_dir: Path) -> Counter:
    """Store collectable Issues. Returns counts for the poll log."""
    issues_file = live_dir / "issues.jsonl"
    collected = already_collected(issues_file)
    counts = Counter()
    now = datetime.now(timezone.utc).isoformat()

    with issues_file.open("a") as issues_out:
        for event in events:
            if not isinstance(event, IssueOpened):
                continue  # taxonomy events belong to the detector
            counts["seen"] += 1
            reason = skip_reason(event, collected)
            if reason:
                counts[f"skipped: {reason}"] += 1
                continue
            record = {"collected_at": now, **event.issue}
            issues_out.write(json.dumps(record) + "\n")
            collected.add(event.number)
            counts["collected"] += 1
    return counts


def run_once(source: EventSource, notifier: Notifier, live_dir: Path = LIVE_DIR) -> Counter:
    """One poll: get events, hand them to the collector and the detector, and only then commit progress."""
    live_dir.mkdir(parents=True, exist_ok=True)
    events = source.poll()
    counts = handle(events, live_dir) + detector.handle(events, live_dir, notifier)
    source.commit()
    with (live_dir / "collect_log.jsonl").open("a") as log:
        log.write(json.dumps({"polled_at": datetime.now(timezone.utc).isoformat(), **counts}) + "\n")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live-dir", type=Path, default=LIVE_DIR)
    args = parser.parse_args()

    client = GitHubClient(get_token())
    if "GITHUB_REPOSITORY" in os.environ:  # set by GitHub Actions, e.g. "Taylor5132/pointsman"
        notifier = GitHubIssueNotifier(client, os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_REPOSITORY_OWNER"))
    else:
        notifier = PrintNotifier()
    source = GitHubPoller(client, args.live_dir / "poller_state.json")
    counts = run_once(source, notifier, args.live_dir)
    print("Poll:", dict(counts) if counts else "nothing new")


if __name__ == "__main__":
    main()
