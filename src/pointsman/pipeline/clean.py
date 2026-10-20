"""Turn a snapshot's raw Issues into clean rows.

Usage:
    uv run python -m pointsman.pipeline.clean --snapshot 2026-10-20

Reads  data/snapshots/<date>/raw/issues.jsonl
Writes data/snapshots/<date>/clean/issues.parquet
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from pointsman.pipeline.schemas import CleanIssue, RawIssue
from pointsman.teams import IN_SCOPE_TEAMS, OUT_OF_SCOPE_TEAMS

KNOWN_TEAMS = set(IN_SCOPE_TEAMS) | set(OUT_OF_SCOPE_TEAMS)

HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
DETAILS_TAGS = re.compile(r"</?(details|summary)[^>]*>", re.IGNORECASE)
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)|<img[^>]*>", re.IGNORECASE)
NO_RESPONSE = re.compile(r"^_No response_\s*$", re.MULTILINE)  # GitHub's filler for empty form fields
CODE_FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.DOTALL | re.MULTILINE)
BLANK_LINES = re.compile(r"\n{3,}")

# A line of a Dart stack trace looks like:
#   #0      State.setState (package:flutter/src/widgets/framework.dart:1219:9)
DART_FRAME = re.compile(r"^#\d+\s+\S.*\(.+:\d+(:\d+)?\)", re.MULTILINE)
NATIVE_CRASH = re.compile(r"Thread \d+ Crashed|^\s+at [\w$.]+\(.*\)$|SIGSEGV|SIGABRT", re.MULTILINE)

# Triagers word it many ways: "Closing this as a duplicate of #192976",
# "Duping to https://github.com/flutter/flutter/issues/128713", "dupe of #123".
# So: any word starting with "dup", then the first Issue reference on the same line.
DUPLICATE_OF = re.compile(r"\bdup\w*\b[^\n]*?(?:github\.com/flutter/flutter/issues/|#)(\d+)", re.IGNORECASE)


def strip_markup(body: str) -> str:
    """Remove the parts of an Issue body that are formatting, not content."""
    text = HTML_COMMENT.sub("", body)
    text = DETAILS_TAGS.sub("", text)
    text = IMAGE.sub("[image]", text)
    text = NO_RESPONSE.sub("", text)
    return text


def split_code(text: str) -> tuple[str, list[str]]:
    """Separate fenced code blocks (```...```) from the prose around them."""
    blocks = [match.group(0) for match in CODE_FENCE.finditer(text)]
    prose = CODE_FENCE.sub("", text)
    prose = BLANK_LINES.sub("\n\n", prose).strip()
    return prose, blocks


def has_stack_trace(text: str) -> bool:
    return bool(DART_FRAME.search(text) or NATIVE_CRASH.search(text))


def find_duplicate_of(issue: RawIssue) -> int | None:
    """For an Issue closed as a Duplicate, read the Original's number from the triager's comment."""
    is_duplicate = issue.state_reason == "DUPLICATE" or any(l.name == "r: duplicate" for l in issue.labels)
    if not is_duplicate:
        return None
    for comment in reversed(issue.comments):  # the closing comment is usually the last one
        match = DUPLICATE_OF.search(comment.body)
        if match:
            return int(match.group(1))
    return None


def find_routed(issue: RawIssue) -> bool | None:
    """Was the first Team label applied by someone other than the author?

    Returns None when we cannot tell: no Team label event was found
    (for example the timeline was cut off at 100 events), or an account was deleted.
    """
    for event in issue.label_events:
        if event.kind == "LabeledEvent" and event.label.name.startswith("team-"):
            if event.actor is None or issue.author is None:
                return None
            return event.actor.login != issue.author.login
    return None


def clean_issue(issue: RawIssue) -> tuple[CleanIssue | None, str | None]:
    """Clean one Issue. Returns (row, None) to keep it, or (None, reason) to drop it."""
    if issue.author is not None and issue.author.type == "Bot":
        return None, "bot author"

    team_labels = [l for l in issue.labels if l.name in KNOWN_TEAMS]
    if len(team_labels) == 0:
        return None, "no known Team label now"
    if len(team_labels) > 1:
        return None, "more than one Team label"
    team = team_labels[0]

    prose, blocks = split_code(strip_markup(issue.body))
    code = "\n\n".join(blocks)
    label_names = {l.name for l in issue.labels}

    row = CleanIssue(
        number=issue.number,
        title=issue.title.strip(),
        prose=prose,
        code=code,
        num_code_blocks=len(blocks),
        has_stack_trace=has_stack_trace(issue.body),
        created_at=issue.created_at,
        closed_at=issue.closed_at,
        state=issue.state,
        state_reason=issue.state_reason,
        author=issue.author.login if issue.author else None,
        team=team.name,
        team_label_id=team.id,
        in_scope=team.name in IN_SCOPE_TEAMS,
        confirmed=team.name.replace("team-", "triaged-") in label_names,
        routed=find_routed(issue),
        team_label_events=sum(
            1 for e in issue.label_events if e.kind == "LabeledEvent" and e.label.name.startswith("team-")
        ),
        duplicate_of=find_duplicate_of(issue),
    )
    return row, None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", required=True, help="snapshot date, e.g. 2026-10-20")
    parser.add_argument("--root", type=Path, default=Path("data/snapshots"))
    args = parser.parse_args()

    snapshot_dir = args.root / args.snapshot
    rows = []
    dropped = Counter()

    with (snapshot_dir / "raw" / "issues.jsonl").open() as f:
        for line in f:
            issue = RawIssue.from_graphql(json.loads(line))
            row, reason = clean_issue(issue)
            if row is None:
                dropped[reason] += 1
            else:
                rows.append(row.model_dump())

    out_dir = snapshot_dir / "clean"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "issues.parquet"
    df = pd.DataFrame(rows)
    # Columns that can be empty get pandas' "nullable" types, so 128713 stays a whole
    # number and True/False/unknown stays a boolean, instead of turning into floats/objects.
    df["duplicate_of"] = df["duplicate_of"].astype("Int64")
    df["routed"] = df["routed"].astype("boolean")
    df.to_parquet(out_file, index=False)

    print(f"Kept {len(rows)} Issues -> {out_file}")
    for reason, count in dropped.most_common():
        print(f"  dropped {count}: {reason}")


if __name__ == "__main__":
    main()
