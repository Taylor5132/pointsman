"""Split a snapshot's clean Issues by time: oldest 70% train, next 15% val, newest 15% test.

Usage:
    uv run python -m pointsman.pipeline.split --snapshot 2026-10-20

Reads  data/snapshots/<date>/clean/issues.parquet
Writes data/snapshots/<date>/split/{train,val,test}.parquet and split/boundaries.json

Why by time and not at random: the model must predict *future* Issues from *past*
ones. A random split would let it train on next month's Issues and be tested on
last month's, which looks better than reality (temporal leakage).

All Issues are split, including Out-of-scope ones: training uses only In-scope
Issues, but val/test keep Out-of-scope Issues to check they go to Human review.
"""

import argparse
import json
from pathlib import Path

import duckdb

TRAIN_SHARE = 0.70
VAL_SHARE = 0.15  # the remaining 15% is test


def find_boundaries(con: duckdb.DuckDBPyConnection) -> tuple:
    """Return the two cut timestamps: val starts at the first, test at the second.

    We cut at timestamps, not row positions, so two Issues created in the same
    second always land on the same side. That keeps the guarantee strict:
    every train Issue is older than every val Issue, which is older than every test Issue.
    """
    return con.execute(
        """
        SELECT
            quantile_disc(created_at, ?) AS val_start,
            quantile_disc(created_at, ?) AS test_start
        FROM issues
        """,
        [TRAIN_SHARE, TRAIN_SHARE + VAL_SHARE],
    ).fetchone()


def check_no_leakage(con: duckdb.DuckDBPyConnection) -> None:
    """The Milestone 1 checkpoint, enforced every run: the three parts must not overlap in time."""
    rows = con.execute(
        """
        SELECT part, min(created_at), max(created_at), count(*)
        FROM split GROUP BY part
        """
    ).fetchall()
    span = {part: (first, last, n) for part, first, last, n in rows}
    assert span["train"][1] < span["val"][0], "train overlaps val in time"
    assert span["val"][1] < span["test"][0], "val overlaps test in time"
    total = con.execute("SELECT count(*) FROM issues").fetchone()[0]
    assert sum(n for _, _, n in span.values()) == total, "an Issue was lost or duplicated"


def split_snapshot(snapshot_dir: Path) -> dict:
    """Split a snapshot's clean Issues and write split/*.parquet and split/boundaries.json."""
    if (snapshot_dir / "manifest.json").exists():
        raise SystemExit(f"{snapshot_dir} is frozen (it has a manifest). Snapshots never change.")

    con = duckdb.connect()  # an in-memory database: nothing is written except the files below
    con.execute("CREATE TABLE issues AS SELECT * FROM read_parquet(?)", [str(snapshot_dir / "clean/issues.parquet")])

    val_start, test_start = find_boundaries(con)
    con.execute(
        """
        CREATE TABLE split AS
        SELECT *,
            CASE
                WHEN created_at < ? THEN 'train'
                WHEN created_at < ? THEN 'val'
                ELSE 'test'
            END AS part
        FROM issues
        """,
        [val_start, test_start],
    )
    check_no_leakage(con)

    out_dir = snapshot_dir / "split"
    out_dir.mkdir(exist_ok=True)
    counts = {}
    for part in ["train", "val", "test"]:
        out_file = out_dir / f"{part}.parquet"
        con.execute(
            f"COPY (SELECT * EXCLUDE (part) FROM split WHERE part = '{part}' ORDER BY created_at) "
            f"TO '{out_file}' (FORMAT parquet)"
        )
        counts[part] = con.execute(f"SELECT count(*) FROM split WHERE part = '{part}'").fetchone()[0]

    boundaries = {
        "val_start": val_start.isoformat(),
        "test_start": test_start.isoformat(),
        "counts": counts,
    }
    (out_dir / "boundaries.json").write_text(json.dumps(boundaries, indent=2) + "\n")
    return boundaries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", required=True, help="snapshot date, e.g. 2026-10-20")
    parser.add_argument("--root", type=Path, default=Path("data/snapshots"))
    args = parser.parse_args()

    b = split_snapshot(args.root / args.snapshot)
    c = b["counts"]
    print(f"train {c['train']} | val {c['val']} (from {b['val_start'][:10]}) | test {c['test']} (from {b['test_start'][:10]})")


if __name__ == "__main__":
    main()
