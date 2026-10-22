"""The pipeline end to end on fake data, without the network: clean -> split -> freeze -> verify."""

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from pointsman.pipeline.clean import clean_snapshot
from pointsman.pipeline.snapshot import freeze, verify
from pointsman.pipeline.split import split_snapshot


@pytest.fixture
def snapshot_dir(tmp_path, make_issue):
    """A fake snapshot: 20 Issues on 20 consecutive days, plus three created in the same second."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    issues = [
        make_issue(number=i, created_at=(start + timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        for i in range(20)
    ]
    same_second = (start + timedelta(days=13, hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    issues += [make_issue(number=100 + i, created_at=same_second) for i in range(3)]

    directory = tmp_path / "2024-02-01"
    (directory / "raw").mkdir(parents=True)
    (directory / "raw/issues.jsonl").write_text("".join(json.dumps(issue) + "\n" for issue in issues))
    (directory / "raw/ingest_info.json").write_text(json.dumps({"complete": True, "taxonomy_version": {"id": "rulebook-test"}}))
    return directory


def read_split(directory):
    return {part: pd.read_parquet(directory / f"split/{part}.parquet") for part in ["train", "val", "test"]}


def test_split_parts_do_not_overlap_in_time(snapshot_dir):
    clean_snapshot(snapshot_dir)
    split_snapshot(snapshot_dir)
    parts = read_split(snapshot_dir)

    assert parts["train"]["created_at"].max() < parts["val"]["created_at"].min()
    assert parts["val"]["created_at"].max() < parts["test"]["created_at"].min()


def test_every_issue_lands_in_exactly_one_part(snapshot_dir):
    clean_snapshot(snapshot_dir)
    split_snapshot(snapshot_dir)
    numbers = pd.concat(read_split(snapshot_dir).values())["number"]

    assert len(numbers) == 23
    assert numbers.is_unique


def test_issues_from_the_same_second_stay_together(snapshot_dir):
    clean_snapshot(snapshot_dir)
    split_snapshot(snapshot_dir)
    parts_holding_them = [
        part for part, df in read_split(snapshot_dir).items() if df["number"].isin([100, 101, 102]).any()
    ]
    assert len(parts_holding_them) == 1


def test_frozen_snapshot_detects_any_change(snapshot_dir):
    clean_snapshot(snapshot_dir)
    split_snapshot(snapshot_dir)
    freeze(snapshot_dir)
    verify(snapshot_dir)  # unchanged: passes quietly

    with (snapshot_dir / "split/test.parquet").open("ab") as f:
        f.write(b"x")  # one extra byte in the locked test set
    with pytest.raises(SystemExit, match="CHANGED"):
        verify(snapshot_dir)


def test_frozen_snapshot_refuses_to_be_rewritten(snapshot_dir):
    clean_snapshot(snapshot_dir)
    split_snapshot(snapshot_dir)
    freeze(snapshot_dir)

    with pytest.raises(SystemExit, match="frozen"):
        clean_snapshot(snapshot_dir)
    with pytest.raises(SystemExit, match="frozen"):
        split_snapshot(snapshot_dir)
