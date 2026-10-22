"""Freeze a snapshot with a manifest, and verify it has not changed since.

Usage:
    uv run python -m pointsman.pipeline.snapshot freeze --snapshot 2026-10-20
    uv run python -m pointsman.pipeline.snapshot verify --snapshot 2026-10-20

A snapshot can be re-downloaded and re-cleaned freely until it is frozen.
Freezing writes manifest.json, which records where the data came from, what
is in it, and a fingerprint (SHA-256 hash) of every data file. After that the
snapshot never changes: ingest refuses to overwrite it, and `verify` proves
the files are byte-for-byte what the manifest describes.
"""

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# The files a frozen snapshot contains, relative to its folder.
DATA_FILES = [
    "raw/issues.jsonl",
    "raw/label_events.jsonl",
    "raw/ingest_info.json",
    "clean/issues.parquet",
    "clean/dropped.json",
    "split/train.parquet",
    "split/val.parquet",
    "split/test.parquet",
    "split/boundaries.json",
]


def sha256_of(path: Path) -> str:
    """A fingerprint of the file: change a single byte and the hash is completely different."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):  # read 1 MB at a time
            digest.update(chunk)
    return digest.hexdigest()


def code_version() -> dict:
    """Which commit of Pointsman produced this snapshot, and were there uncommitted edits?"""
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    status = subprocess.run(["git", "status", "--porcelain", "src"], capture_output=True, text=True, check=True)
    return {"commit": commit.stdout.strip(), "uncommitted_changes": bool(status.stdout.strip())}


def summarize(df: pd.DataFrame) -> dict:
    """The counts a reader needs to know what is inside, without opening the data."""
    return {
        "issues": len(df),
        "created_at_range": [df["created_at"].min().isoformat(), df["created_at"].max().isoformat()],
        "per_team": df["team"].value_counts().sort_index().to_dict(),
        "in_scope": int(df["in_scope"].sum()),
        "confirmed": int(df["confirmed"].sum()),
        "routed": {
            "routed": int((df["routed"] == True).sum()),  # noqa: E712 (nullable boolean column)
            "self_labeled": int((df["routed"] == False).sum()),  # noqa: E712
            "unknown": int(df["routed"].isna().sum()),
        },
        "duplicates_with_original": int(df["duplicate_of"].notna().sum()),
        "open": int((df["state"] == "OPEN").sum()),
        "closed": int((df["state"] == "CLOSED").sum()),
    }


def freeze(snapshot_dir: Path) -> None:
    manifest_path = snapshot_dir / "manifest.json"
    if manifest_path.exists():
        raise SystemExit(f"{snapshot_dir} is already frozen.")
    missing = [name for name in DATA_FILES if not (snapshot_dir / name).exists()]
    if missing:
        raise SystemExit(f"Cannot freeze: missing {missing}. Run ingest, clean and split first.")

    ingest_info = json.loads((snapshot_dir / "raw/ingest_info.json").read_text())
    dropped = json.loads((snapshot_dir / "clean/dropped.json").read_text())
    df = pd.read_parquet(snapshot_dir / "clean/issues.parquet")

    manifest = {
        "snapshot": snapshot_dir.name,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "complete": ingest_info["complete"],
        "taxonomy_version": ingest_info["taxonomy_version"]["id"],
        "code": code_version(),
        "ingest": {key: value for key, value in ingest_info.items() if key != "taxonomy_version"},
        "clean": {"kept": len(df), "dropped": dropped},
        "split": json.loads((snapshot_dir / "split/boundaries.json").read_text()),
        "contents": summarize(df),
        "files": {name: {"sha256": sha256_of(snapshot_dir / name)} for name in DATA_FILES},
        "taxonomy": ingest_info["taxonomy_version"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"Froze {snapshot_dir} (Taxonomy Version {manifest['taxonomy_version']}, {len(df)} Issues)")
    if not manifest["complete"]:
        print("  Note: this is a sample (ingest ran with --limit), not a full download.")
    if manifest["code"]["uncommitted_changes"]:
        print("  Warning: src/ had uncommitted changes, so the code version is not exactly reproducible.")


def verify(snapshot_dir: Path) -> None:
    manifest = json.loads((snapshot_dir / "manifest.json").read_text())
    changed = [
        name
        for name, info in manifest["files"].items()
        if sha256_of(snapshot_dir / name) != info["sha256"]
    ]
    if changed:
        raise SystemExit(f"{snapshot_dir} has CHANGED since it was frozen: {changed}")
    print(f"{snapshot_dir} is unchanged ({len(manifest['files'])} files match the manifest).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["freeze", "verify"])
    parser.add_argument("--snapshot", required=True, help="snapshot date, e.g. 2026-10-20")
    parser.add_argument("--root", type=Path, default=Path("data/snapshots"))
    args = parser.parse_args()

    snapshot_dir = args.root / args.snapshot
    if args.command == "freeze":
        freeze(snapshot_dir)
    else:
        verify(snapshot_dir)


if __name__ == "__main__":
    main()
